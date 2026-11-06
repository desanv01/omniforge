"""Pure bounded UTF8 text/JSON/CSV intake; no routes, storage, discovery or I/O.

Callers supply byte chunks, a logical name, limits, association identity and an
optional validated content-identity snapshot. Only a complete result is returned.
Original bytes are never normalized. Collection/capture-time provenance and
durable publication remain caller responsibilities outside this boundary.
"""
import codecs
import csv
from dataclasses import asdict, dataclass
import hashlib
import io
import json
import unicodedata
from uuid import UUID, uuid5

from packages.contracts.evidence.models import Artifact, Derivation, Location

VERSION = "1.0.0"
NAMESPACE = UUID("730ef9b0-215e-59c0-9d51-1257092bbf9c")
ARTIFACT_MAX = 25 * 1024 * 1024
FORMATS = {"text/plain":"text", "application/json":"json", "text/csv":"csv"}
EXTENSIONS = {"txt":"text", "log":"text", "json":"json", "csv":"csv"}


class ImportFailure(ValueError):
    """Actionable fixed messages and numeric locations; no raw input in errors."""
    def __init__(self, code, message, *, byte_offset=None, line=None, column=None):
        self.code=code;self.message=message
        self.byte_offset=byte_offset;self.line=line;self.column=column
        super().__init__(message)


def fail(code,message,**location):raise ImportFailure(code,message,**location) from None


@dataclass(frozen=True)
class ImportLimits:
    max_bytes: int
    max_output_bytes: int
    max_chunks: int = 4096
    max_rows: int = 10000
    max_columns: int = 256
    max_field_chars: int = 65536
    max_json_depth: int = 64
    max_json_tokens: int = 20000
    max_number_chars: int = 256

    def __post_init__(self):
        ceilings=dict(max_bytes=ARTIFACT_MAX,max_output_bytes=ARTIFACT_MAX,max_chunks=65536,
            max_rows=100000,max_columns=1024,max_field_chars=65536,max_json_depth=64,
            max_json_tokens=100000,max_number_chars=256)
        if any(type(getattr(self,key)) is not int or not 1<=getattr(self,key)<=ceiling for key,ceiling in ceilings.items()):
            fail("invalid_limits","Supply positive integer limits within the documented hard ceilings.")


@dataclass(frozen=True)
class ArtifactRef:
    id: UUID
    sha256: str
    bytes: int

    @property
    def path(self):return "blobs/"+self.sha256

    def to_model(self):return Artifact(id=self.id,sha256=self.sha256,bytes=self.bytes,path=self.path)


@dataclass(frozen=True)
class ExtractionLineage:
    id: UUID
    input_artifact_id: UUID
    output_artifact_id: UUID
    options_sha256: str
    tool_version: str

    def to_model(self):
        return Derivation(id=self.id,input_artifact_ids=[self.input_artifact_id],output_artifact_id=self.output_artifact_id,
            tool="omniforge-import-core",tool_version=self.tool_version,options_sha256=self.options_sha256,coverage="complete",warnings=[])


@dataclass(frozen=True)
class ByteOrigin:
    id: UUID
    association_id: UUID
    sha256: str
    end: int

    def to_model(self):
        return Location(id=self.id,association_id=self.association_id,sha256=self.sha256,kind="bytes",start=0,end=self.end,encoding=None)


@dataclass(frozen=True)
class ImportResult:
    logical_name: str
    media_type: str
    original: bytes
    artifact: ArtifactRef
    is_duplicate: bool
    extracted: bytes
    extracted_media_type: str
    extracted_artifact: ArtifactRef
    lineage: ExtractionLineage
    origin: ByteOrigin | None
    record_count: int

    @property
    def original_name(self):return self.logical_name.rsplit("/",1)[-1]


def validate_name(name):
    if type(name) is not str or not 1<=len(name)<=255 or unicodedata.normalize("NFKC",name)!=name:
        fail("invalid_name","Use a relative logical name of 1–255 unambiguous characters.")
    segments=name.split("/")
    reserved={"con","prn","aux","nul",*("com"+str(i) for i in range(1,10)),*("lpt"+str(i) for i in range(1,10))}
    for segment in segments:
        if not segment or segment in (".","..") or segment.endswith(("."," ")) or segment.split(".",1)[0].rstrip(" ").casefold() in reserved:
            fail("invalid_name","Use nonempty relative path segments without traversal, device names or trailing dots/spaces.")
        if any(not (char in " ._-" or unicodedata.category(char)[0] in "LMN") for char in segment):
            fail("invalid_name","Use letters, numbers, spaces, dots, underscores or hyphens; separate folders with forward slash.")
    return name


def validate_media(name,media_type):
    if type(media_type) is not str or len(media_type)>128 or any(ord(char)<32 or ord(char)==127 for char in media_type):
        fail("unsupported_media_type","Supply text/plain, application/json or text/csv with optional UTF-8 charset.")
    parts=[part.strip().lower() for part in media_type.split(";")]
    if parts[0] not in FORMATS or len(parts)>2 or len(parts)==2 and parts[1] not in ("charset=utf-8",'charset="utf-8"'):
        fail("unsupported_media_type","Only text/plain, application/json and text/csv encoded as UTF-8 are supported.")
    extension=name.rsplit("/",1)[-1].rsplit(".",1)
    if len(extension)!=2 or extension[-1].lower() not in EXTENSIONS:
        fail("unsupported_extension","Use .txt, .log, .json or .csv for this import boundary.")
    if EXTENSIONS[extension[-1].lower()]!=FORMATS[parts[0]]:
        fail("format_mismatch","Match the logical filename extension to the declared media type.")
    return parts[0],FORMATS[parts[0]]


def registry_snapshot(known):
    if type(known) is not tuple or len(known)>64:
        fail("invalid_registry","Supply at most 64 known Artifact models in an immutable tuple.")
    hashes={};ids=set()
    for item in known:
        try:
            if type(item) is not Artifact:raise ValueError()
            model=Artifact.model_validate(item.model_dump())
        except Exception:
            fail("invalid_registry","Every known artifact must satisfy the existing portable artifact contract.")
        if model.sha256 in hashes or model.id in ids:
            fail("ambiguous_registry","Known artifacts must have unique hashes and identities.")
        hashes[model.sha256]=ArtifactRef(model.id,model.sha256,model.bytes);ids.add(model.id)
    return hashes


def read_stream(chunks,limits):
    if type(chunks) in (str,bytes,bytearray,memoryview):
        fail("invalid_stream","Supply an iterable of immutable byte chunks, not a single string or buffer.")
    try:iterator=iter(chunks)
    except Exception:fail("invalid_stream","Supply an iterable of immutable byte chunks.")
    decoder=codecs.getincrementaldecoder("utf-8")("strict")
    originals=[];texts=[];hasher=hashlib.sha256();total=0;count=0
    while True:
        try:chunk=next(iterator)
        except StopIteration:break
        except Exception:fail("stream_read_failed","The input stream failed; supply the complete source again.")
        count+=1
        if count>limits.max_chunks:fail("chunk_limit","The stream exceeds max_chunks; supply fewer chunks or raise that explicit limit.")
        if type(chunk) is not bytes:fail("invalid_chunk","Every input chunk must be immutable bytes.")
        if len(chunk)>limits.max_bytes-total:
            fail("byte_limit","The input exceeds max_bytes; choose a smaller source or raise that explicit limit.",byte_offset=total)
        pending=len(decoder.getstate()[0]);offset=total-pending
        total+=len(chunk);hasher.update(chunk);originals.append(chunk)
        try:texts.append(decoder.decode(chunk,final=False))
        except UnicodeDecodeError as error:
            fail("invalid_utf8","Input is not valid UTF-8; transcode it before import.",byte_offset=offset+error.start)
    pending=len(decoder.getstate()[0])
    try:texts.append(decoder.decode(b"",final=True))
    except UnicodeDecodeError as error:
        fail("truncated_utf8","The stream ends inside a UTF-8 character; supply complete bytes.",byte_offset=total-pending+error.start)
    return b"".join(originals),"".join(texts).removeprefix("\ufeff"),hasher.hexdigest()


def json_extract(text,limits):
    # Bound nesting and lexical token count BEFORE allocating the JSON tree.
    # Keys count as tokens too; all primitive numbers stay lexical (no float or
    # integer coercion/precision loss). Exact validated JSON text is the output.
    depth=0;tokens=0;quoted=False;escaped=False;primitive=False
    for char in text:
        if quoted:
            if escaped:escaped=False
            elif char=="\\":escaped=True
            elif char=='"':quoted=False
            continue
        if char.isspace():primitive=False;continue
        if char in "{}[],:":primitive=False
        if char in "{[":depth+=1;tokens+=1
        elif char in "}]":depth-=1
        elif char=='"':quoted=True;tokens+=1;primitive=False
        elif char not in ",:" and not primitive:primitive=True;tokens+=1
        if depth>limits.max_json_depth:fail("json_depth_limit","JSON nesting exceeds max_json_depth; flatten the input or raise that limit.")
        if tokens>limits.max_json_tokens:fail("json_token_limit","JSON exceeds max_json_tokens; split the document or raise that limit.")
    def number(token):
        if len(token)>limits.max_number_chars:fail("json_number_limit","A JSON numeric token exceeds max_number_chars.")
        return None  # Validation only; original lexical value remains in text.
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:fail("duplicate_json_key","JSON object keys must be unique, including equivalent escaped keys.")
            result[key]=value
        return result
    def constant(value):fail("invalid_json_constant","NaN and Infinity are not supported JSON values.")
    try:value=json.loads(text,parse_int=number,parse_float=number,parse_constant=constant,object_pairs_hook=pairs)
    except json.JSONDecodeError as error:
        fail("invalid_json","Malformed or truncated JSON; supply one complete JSON value.",line=error.lineno,column=error.colno)
    except RecursionError:fail("json_depth_limit","JSON nesting exceeds the parser depth budget.")
    stack=[value]
    while stack:
        item=stack.pop()
        if isinstance(item,dict):stack.extend(item.keys());stack.extend(item.values())
        elif isinstance(item,list):stack.extend(item)
        elif isinstance(item,str) and any(0xD800<=ord(char)<=0xDFFF for char in item):
            fail("invalid_json_unicode","JSON strings must contain complete Unicode scalar values, not unpaired surrogates.")
    return text.encode("utf-8"),1


def csv_extract(text,limits):
    if any(unicodedata.category(char)=="Cc" and char not in "\t\r\n" for char in text):
        fail("binary_csv","CSV contains unsupported control characters; supply UTF-8 CSV text.")
    reader=csv.reader(io.StringIO(text,newline=""),dialect="excel",strict=True)
    rows=[];header=None
    try:
        for row in reader:
            if len(row)>limits.max_columns:fail("csv_column_limit","CSV exceeds max_columns; reduce its width.",line=reader.line_num)
            if any(len(field)>limits.max_field_chars for field in row):
                fail("csv_field_limit","A CSV field exceeds max_field_chars; shorten it.",line=reader.line_num)
            if header is None:
                if not row or any(field=="" for field in row) or len(set(row))!=len(row):
                    fail("invalid_csv_header","CSV needs a nonempty first record of unique, nonempty column names.",line=reader.line_num)
                header=row
            else:
                if len(row)!=len(header):fail("csv_row_width","Each CSV record must have the header's field count.",line=reader.line_num)
                if len(rows)>=limits.max_rows:fail("csv_row_limit","CSV exceeds max_rows; split the input.",line=reader.line_num)
                rows.append(row)
    except csv.Error:
        fail("invalid_csv","Malformed, truncated or overlong CSV field; check quoting and field sizes.",line=reader.line_num)
    if header is None:fail("invalid_csv_header","CSV needs a first header record.",line=1)
    # Bound serialized extraction without first building an oversized output.
    output=[];size=0
    for piece in json.JSONEncoder(ensure_ascii=False,separators=(",",":"),allow_nan=False).iterencode({"columns":header,"rows":rows}):
        data=piece.encode("utf-8")
        if len(data)>limits.max_output_bytes-size:fail("output_limit","CSV extraction exceeds max_output_bytes; split the source or raise that limit.")
        size+=len(data);output.append(data)
    return b"".join(output),len(rows)


def import_chunks(chunks,*,logical_name,media_type,association_id,limits,known_artifacts=()):
    """Return complete immutable bytes/metadata, or raise without publishing state.

    Duplicate identity is by original SHA256+byte count, not filename. Supplied
    registry is never changed, and duplicates still undergo full format validation.
    UTF8 BOM is retained in original and removed only from extraction. Text/JSON
    extraction preserves remaining text exactly; CSV becomes JSON string arrays.
    """
    if type(limits) is not ImportLimits:fail("invalid_limits","Supply an ImportLimits value with explicit input/output byte limits.")
    limits=ImportLimits(**asdict(limits))  # Recheck forged/mutated dataclass values.
    if type(association_id) is not UUID:fail("invalid_association","Supply the caller's explicit UUID association identity.")
    name=validate_name(logical_name);mime,format_name=validate_media(name,media_type)
    known=registry_snapshot(known_artifacts)
    original,text,sha256=read_stream(chunks,limits)
    if format_name=="json":extracted,count=json_extract(text,limits)
    elif format_name=="csv":extracted,count=csv_extract(text,limits)
    else:
        if any(unicodedata.category(char)=="Cc" and char not in "\t\r\n" for char in text):
            fail("binary_text","Plain text contains unsupported control characters; supply UTF-8 text or another supported format.")
        extracted=text.encode("utf-8");count=int(bool(text))
    if len(extracted)>limits.max_output_bytes:fail("output_limit","Extraction exceeds max_output_bytes; split the source or raise that limit.")
    def reference(value,size):
        if value in known:
            if known[value].bytes!=size:fail("identity_conflict","The known hash has a different byte count; repair the supplied identity snapshot.")
            return known[value]
        result=ArtifactRef(uuid5(NAMESPACE,"artifact:"+value),value,size);result.to_model()
        if any(item.id==result.id for item in known.values()):
            fail("identity_conflict","A content identity conflicts with a known artifact identity; repair the supplied snapshot.")
        known[value]=result
        return result
    duplicate=sha256 in known
    artifact=reference(sha256,len(original))
    output_hash=hashlib.sha256(extracted).hexdigest();output_artifact=reference(output_hash,len(extracted))
    options=dict(tool_version=VERSION,format=format_name,encoding="utf-8-sig",csv_header="unique-first-record",csv_values="strings",
        json_numbers="validated-lexemes",limits=asdict(limits))
    options_hash=hashlib.sha256(json.dumps(options,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    lineage_identity=":".join((str(artifact.id),sha256,str(output_artifact.id),output_hash,options_hash))
    lineage=ExtractionLineage(uuid5(NAMESPACE,lineage_identity),artifact.id,output_artifact.id,options_hash,VERSION)
    lineage.to_model()
    origin=None
    if original:
        origin=ByteOrigin(uuid5(NAMESPACE,str(association_id)+":"+sha256),association_id,sha256,len(original));origin.to_model()
    return ImportResult(name,mime,original,artifact,duplicate,extracted,"application/json" if format_name=="csv" else mime,
        output_artifact,lineage,origin,count)

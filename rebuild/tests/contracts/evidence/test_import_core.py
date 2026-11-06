"""Actual pure import calls over small in-memory streams; no storage/runtime."""
from dataclasses import FrozenInstanceError
import hashlib
import json
import traceback
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from packages.contracts.evidence.models import Artifact
from services.api.import_core import ImportFailure, ImportLimits, import_chunks

ASSOCIATION = UUID("d47884cf-207a-4052-b6b9-87e9a8c54445")


class ImportCoreTests(unittest.TestCase):
    def limits(self,**changes):return ImportLimits(**dict(dict(max_bytes=8192,max_output_bytes=8192),**changes))
    def intake(self,chunks,**changes):
        arguments=dict(logical_name="sources/note.txt",media_type="text/plain",association_id=ASSOCIATION,limits=self.limits())
        arguments.update(changes);return import_chunks(chunks,**arguments)
    def error(self,code,chunks,**changes):
        with self.assertRaises(ImportFailure) as caught:self.intake(chunks,**changes)
        self.assertEqual(caught.exception.code,code);return caught.exception

    def test_streaming_byte_limit_stops_consuming_at_first_excess(self):
        observed=[];results=[]
        def chunks():
            for chunk in (b"abc",b"def",b"MUST_NOT_READ"):
                observed.append(chunk);yield chunk
        with self.assertRaises(ImportFailure) as caught:results.append(self.intake(chunks(),limits=self.limits(max_bytes=5)))
        self.assertEqual(caught.exception.code,"byte_limit");self.assertEqual(caught.exception.byte_offset,3)
        self.assertEqual(observed,[b"abc",b"def"]);self.assertEqual(results,[])

    def test_single_oversized_chunk_and_empty_chunk_count_are_bounded(self):
        observed=[]
        def source():
            for chunk in (b"12345",b"later"):observed.append(chunk);yield chunk
        self.error("byte_limit",source(),limits=self.limits(max_bytes=4));self.assertEqual(observed,[b"12345"])
        pulled=[]
        def empty():
            while True:pulled.append(1);yield b""
        self.error("chunk_limit",empty(),limits=self.limits(max_chunks=3));self.assertEqual(len(pulled),4)

    def test_all_split_multibyte_and_bom_boundaries_preserve_original_hash(self):
        original=b"\xef\xbb\xbf"+"é😀\r\nlast".encode()
        for index in range(len(original)+1):
            with self.subTest(index=index):
                result=self.intake((original[:index],original[index:]))
                self.assertEqual(result.original,original);self.assertEqual(result.artifact.sha256,hashlib.sha256(original).hexdigest())
                self.assertEqual(result.extracted,"é😀\r\nlast".encode())
                self.assertEqual(result.origin.to_model().end,len(original));self.assertEqual(result.origin.to_model().sha256,result.artifact.sha256)
                self.assertEqual(result.artifact.to_model().path,"blobs/"+hashlib.sha256(original).hexdigest())

    def test_invalid_and_truncated_utf8_report_original_byte_offsets(self):
        error=self.error("invalid_utf8",(b"\xef\xbb\xbf",b"ab\xff"));self.assertEqual(error.byte_offset,5)
        self.assertEqual(self.error("truncated_utf8",(b"a\xf0",b"\x9f")).byte_offset,1)
        self.error("truncated_utf8",(b"\xef",b"\xbb"))
        self.error("invalid_utf8",(b"\xff\xfea\x00",))

    def test_traversal_absolute_mixed_and_portability_names_reject_before_read(self):
        for name in ("../x.txt","a/../x.txt","./x.txt","/x.txt","C:/x.txt",r"C:\x.txt",r"a\b.txt",r"a/b\c.txt",
            "//host/x.txt","a//x.txt","a/", "a/%2e%2e/x.txt","x.txt:stream","CON.txt","AUX .txt","x .", "x.txt ",
            "x\x00.txt","x\u202e.txt","a／b.txt","e\u0301.txt"):
            observed=[]
            def source():observed.append(1);yield b"x"
            with self.subTest(name=name):self.error("invalid_name",source(),logical_name=name)
            self.assertEqual(observed,[])
        result=self.intake((b"x",),logical_name="records/évidence 2.log")
        self.assertEqual(result.original_name,"évidence 2.log")

    def test_mime_charset_extension_and_unsupported_formats(self):
        for name,mime,code in (("x.json","text/plain","format_mismatch"),("x.txt","application/json","format_mismatch"),
            ("x.html","text/html","unsupported_media_type"),("x.zip","text/plain","unsupported_extension"),
            ("x.txt","text/plain; charset=latin-1","unsupported_media_type"),("x.txt","text/plain; x=y","unsupported_media_type"),
            ("x.txt","text/plain\r\n","unsupported_media_type"),("x.txt","text/plain; charset=utf-8; extra=1","unsupported_media_type")):
            with self.subTest(name=name,mime=mime):self.error(code,(b"x",),logical_name=name,media_type=mime)
        result=self.intake((b"ok",),media_type='Text/Plain; charset="UTF-8"')
        self.assertEqual(result.media_type,"text/plain")

    def test_text_is_not_rendered_or_normalized_and_controls_reject(self):
        content=b"<script>not executed</script>\r\n\ttext"
        self.assertEqual(self.intake((content,)).extracted,content)
        self.error("binary_text",(b"hello\x00world",))
        self.error("output_limit",(b"hello",),limits=self.limits(max_output_bytes=4))

    def test_json_validates_one_complete_value_without_number_precision_loss(self):
        original=b'\xef\xbb\xbf{"exact":123456789012345678901234567890,"huge":1e9999,"zero":-0,"s":"\\ud83d\\ude00"}'
        result=self.intake((original[:7],original[7:]),logical_name="source/data.json",media_type="application/json")
        self.assertEqual(result.original,original);self.assertEqual(result.extracted,original[3:]);self.assertEqual(result.record_count,1)
        for scalar in (b"null",b"true",b'"value"',b"-0",b"[1,2]"):
            self.assertEqual(self.intake((scalar,),logical_name="a.json",media_type="application/json").extracted,scalar)

    def test_json_malformed_duplicate_nonstandard_unicode_and_budget_errors(self):
        options=dict(logical_name="data.json",media_type="application/json")
        for data in (b"",b'{"x":',b"[1,]",b"{} {}",b"true trailing"):
            error=self.error("invalid_json",(data,),**options);self.assertIsNotNone(error.line);self.assertIsNotNone(error.column)
        for data in (b'{"a":1,"a":2}',b'{"a":1,"\\u0061":2}'):
            self.error("duplicate_json_key",(data,),**options)
        for data in (b"NaN",b"Infinity",b"-Infinity"):self.error("invalid_json_constant",(data,),**options)
        self.error("invalid_json_unicode",(b'{"bad":"\\ud800"}',),**options)
        self.error("json_depth_limit",(b"[[[]]]",),limits=self.limits(max_json_depth=2),**options)
        self.error("json_token_limit",(b'{"a":1}',),limits=self.limits(max_json_tokens=2),**options)
        self.error("json_number_limit",(b"123",),limits=self.limits(max_number_chars=2),**options)

    def test_csv_quotes_newlines_bom_and_string_semantics(self):
        original=b'\xef\xbb\xbfname,value\r\n"a,b","line1\r\nline2"\r\nzero,001\r\n'
        result=self.intake(tuple(original[i:i+1] for i in range(len(original))),logical_name="data.csv",media_type="text/csv")
        self.assertEqual(result.original,original);self.assertEqual(result.record_count,2)
        self.assertEqual(json.loads(result.extracted),{"columns":["name","value"],"rows":[["a,b","line1\r\nline2"],["zero","001"]]})
        self.assertEqual(result.extracted_media_type,"application/json")
        self.assertNotEqual(result.artifact.sha256,result.extracted_artifact.sha256)

    def test_csv_malformed_truncated_width_headers_controls_and_limits(self):
        options=dict(logical_name="x.csv",media_type="text/csv")
        for data in (b"",b"a,a\n1,2",b",b\n1,2"):self.error("invalid_csv_header",(data,),**options)
        self.error("invalid_csv",(b'a,b\n"unfinished,x',),**options)
        self.error("csv_row_width",(b"a,b\n1\n",),**options)
        self.error("csv_row_width",(b"a,b\n\n",),**options)
        self.error("binary_csv",(b"a\n\x00",),**options)
        self.error("csv_column_limit",(b"a,b\n1,2",),limits=self.limits(max_columns=1),**options)
        self.error("csv_field_limit",(b"a\nlong",),limits=self.limits(max_field_chars=3),**options)
        self.error("csv_row_limit",(b"a\n1\n2",),limits=self.limits(max_rows=1),**options)
        self.error("output_limit",(b"a\n1",),limits=self.limits(max_output_bytes=4),**options)

    def test_duplicate_reuses_content_identity_across_names_without_mutating_registry(self):
        content=b"same original";sha=hashlib.sha256(content).hexdigest();identity=uuid4()
        known=Artifact(id=identity,sha256=sha,bytes=len(content),path="blobs/"+sha)
        before=known.model_dump()
        result=self.intake((content[:3],content[3:]),logical_name="another.txt",known_artifacts=(known,))
        self.assertTrue(result.is_duplicate);self.assertEqual(result.artifact.id,identity)
        self.assertEqual(result.extracted_artifact.id,identity);self.assertEqual(known.model_dump(),before)
        first=self.intake((content,));second=self.intake((content,),logical_name="renamed.txt")
        self.assertFalse(first.is_duplicate);self.assertEqual(first.artifact,second.artifact)
        self.assertEqual(first.original,content)
        self.assertNotEqual(first.lineage.id,result.lineage.id)
        self.assertEqual(result.lineage.to_model().input_artifact_ids,[identity])

    def test_duplicate_cannot_bypass_validation_and_identity_conflicts_are_atomic(self):
        data=b'{"broken":';sha=hashlib.sha256(data).hexdigest()
        known=Artifact(id=uuid4(),sha256=sha,bytes=len(data),path="blobs/"+sha)
        before=known.model_dump()
        self.error("invalid_json",(data,),logical_name="bad.json",media_type="application/json",known_artifacts=(known,))
        self.assertEqual(known.model_dump(),before)
        self.error("ambiguous_registry",(b"ok",),known_artifacts=(known,known))
        wrong=known.model_copy(update={"bytes":len(data)+1})
        self.error("identity_conflict",(data,),known_artifacts=(wrong,),logical_name="known.txt")
        good=self.intake((b"good",))
        collision=Artifact(id=good.artifact.id,sha256="0"*64,bytes=2,path="blobs/"+"0"*64)
        self.error("identity_conflict",(b"good",),known_artifacts=(collision,))

    def test_immutable_original_and_lineage_match_existing_contracts(self):
        result=self.intake((b"a,b\n1,2",),logical_name="a.csv",media_type="text/csv")
        derivation=result.lineage.to_model();location=result.origin.to_model()
        self.assertEqual(derivation.input_artifact_ids,[result.artifact.id]);self.assertEqual(derivation.output_artifact_id,result.extracted_artifact.id)
        self.assertEqual(derivation.coverage,"complete");self.assertEqual((location.start,location.end,location.encoding),(0,len(result.original),None))
        self.assertEqual(location.association_id,ASSOCIATION)
        with self.assertRaises(FrozenInstanceError):result.original=b"changed"
        with self.assertRaises(FrozenInstanceError):result.artifact.sha256="f"*64
        copied=result.artifact.to_model();copied.sha256="f"*64
        self.assertNotEqual(result.artifact.sha256,copied.sha256)
        self.assertNotEqual(result.lineage.options_sha256,self.intake((result.original,),logical_name="a.csv",media_type="text/csv",
            limits=self.limits(max_rows=5)).lineage.options_sha256)
        with patch("services.api.import_core.VERSION","1.0.1"):
            changed=self.intake((result.original,),logical_name="a.csv",media_type="text/csv")
        self.assertNotEqual(result.lineage.id,changed.lineage.id)
        self.assertEqual(result.artifact,changed.artifact)
        self.assertEqual(changed.lineage.to_model().tool_version,"1.0.1")
        self.assertEqual(result.lineage.to_model().tool_version,"1.0.0")

    def test_empty_text_has_exact_identity_without_fabricating_nonempty_location(self):
        result=self.intake(())
        self.assertEqual((result.original,result.extracted,result.record_count),(b"",b"",0))
        self.assertEqual(result.artifact.sha256,hashlib.sha256(b"").hexdigest());self.assertIsNone(result.origin)

    def test_bad_limits_chunks_stream_failure_and_error_messages(self):
        for changes in (dict(max_bytes=True),dict(max_output_bytes=0),dict(max_json_depth=65)):
            with self.assertRaises(ImportFailure):self.limits(**changes)
        forged=self.limits();object.__setattr__(forged,"max_chunks",0)
        self.error("invalid_limits",(b"x",),limits=forged)
        self.error("invalid_stream",b"not chunks")
        self.error("invalid_chunk",(bytearray(b"mutable"),))
        def broken():yield b"prefix";raise RuntimeError("SENSITIVE_STREAM_SENTINEL")
        error=self.error("stream_read_failed",broken())
        self.assertNotIn("SENSITIVE_STREAM_SENTINEL","".join(traceback.format_exception(error)))
        self.error("invalid_association",(b"ok",),association_id=str(ASSOCIATION))

    def test_callable_performs_no_filesystem_network_or_subprocess_operations(self):
        with patch("builtins.open",side_effect=AssertionError("no files")),\
            patch("socket.create_connection",side_effect=AssertionError("no network")),\
            patch("subprocess.Popen",side_effect=AssertionError("no process")):
            result=self.intake((b"local",))
        self.assertEqual(result.original,b"local")


if __name__=="__main__":unittest.main(failfast=True)

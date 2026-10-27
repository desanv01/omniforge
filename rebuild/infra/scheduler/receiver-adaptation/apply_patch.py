"""Deterministic eight-file derivative applicator, never an installed SDK patcher."""
import hashlib
import json
from pathlib import Path
import re


FILES=('hatchet_sdk/config.py', 'hatchet_sdk/connection.py', 'hatchet_sdk/clients/dispatcher/dispatcher.py', 'hatchet_sdk/clients/dispatcher/action_listener.py', 'hatchet_sdk/clients/admin.py', 'hatchet_sdk/worker/action_listener_process.py', 'hatchet_sdk/worker/worker.py', 'hatchet_sdk/worker/runner/run_loop_manager.py')


def sha(data): return hashlib.sha256(data).hexdigest()


def patched(original,lines):
    source=original.decode("utf-8").splitlines(keepends=True)
    output=[]
    cursor=0
    index=0
    while index<len(lines):
        match=re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)\n?",lines[index])
        if not match: raise ValueError("Invalid derivative patch")
        start=int(match[1])-1
        old_count=int(match[2] or 1)
        new_count=int(match[4] or 1)
        if start<cursor or start>len(source): raise ValueError("Patch context mismatch")
        output.extend(source[cursor:start]);cursor=start
        index+=1;seen_old=seen_new=0
        while index<len(lines) and not lines[index].startswith("@@ "):
            line=lines[index];index+=1
            if not line or line[0] not in " +-": raise ValueError("Invalid derivative patch")
            value=line[1:]
            if line[0] in " -":
                if cursor>=len(source) or source[cursor]!=value: raise ValueError("Patch context mismatch")
                cursor+=1;seen_old+=1
            if line[0] in " +": output.append(value);seen_new+=1
        if (seen_old,seen_new)!=(old_count,new_count): raise ValueError("Patch size mismatch")
    output.extend(source[cursor:])
    return "".join(output).encode()


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("Duplicate manifest key")
        result[key]=value
    return result


def apply(source,destination):
    base=Path(__file__).resolve().parent
    source=Path(source).resolve(strict=True)
    destination=Path(destination).resolve()
    if source==destination or source in destination.parents or destination in source.parents or destination.exists():
        raise ValueError("Requires a new separate disposable destination")
    metadata=source/"hatchet_sdk-1.41.1.dist-info"/"METADATA"
    raw=metadata.read_bytes()
    if b"Name: hatchet-sdk\n" not in raw.replace(b"\r\n",b"\n") or b"Version: 1.41.1\n" not in raw.replace(b"\r\n",b"\n"):
        raise ValueError("Upstream version mismatch")
    manifest=json.loads((base/"upstream-manifest.json").read_text(),object_pairs_hook=unique_object)
    if set(manifest["files"]) != set(FILES): raise ValueError("Manifest surface mismatch")
    patch=(base/"receiver-policy.patch").read_text(encoding="utf-8").splitlines(keepends=True)
    sections={};index=0
    while index<len(patch):
        if not patch[index].startswith("--- a/") or index+1>=len(patch): raise ValueError("Invalid patch header")
        name=patch[index][6:].strip()
        if name not in FILES or patch[index+1]!="+++ b/"+name+"\n" or name in sections: raise ValueError("Patch surface mismatch")
        index+=2;start=index
        while index<len(patch) and not patch[index].startswith("--- a/"): index+=1
        sections[name]=patch[start:index]
    if set(sections)!=set(FILES): raise ValueError("Patch surface mismatch")
    results={}
    for name in FILES:
        path=source/name
        if any(part.is_symlink() for part in (path, *path.parents)) or source not in path.resolve().parents: raise ValueError("Upstream symlink rejected")
        original=path.read_bytes()
        entry=manifest["files"][name]
        if sha(original)!=entry["upstream_sha256"]: raise ValueError("Upstream hash mismatch")
        normalized=original.replace(b"\r\n",b"\n")
        if sha(normalized)!=entry["upstream_lf_sha256"]: raise ValueError("Upstream LF hash mismatch")
        result=patched(normalized,sections[name])
        if sha(result)!=entry["derivative_sha256"]: raise ValueError("Derivative hash mismatch")
        results[name]=result
    # Validate everything before creating output; copy only the exact eight files.
    destination.mkdir(parents=True,exist_ok=False)
    for name,data in results.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    return {name:sha(data) for name,data in results.items()}


if __name__=="__main__":
    import sys
    try:
        if len(sys.argv)!=3: raise ValueError()
        print(json.dumps(apply(sys.argv[1],sys.argv[2]),sort_keys=True))
    except Exception:
        print("Derivative verification failed",file=sys.stderr)
        raise SystemExit(1) from None

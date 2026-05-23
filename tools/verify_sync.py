#!/usr/bin/env python3
import hashlib, json, sys
from pathlib import Path

DEFAULT_GLOBS = [
    "orchestrator/**/*.py", "orchestrator/**/*.yaml", "orchestrator/**/*.yml",
    "ebs_backup_pkg/**/*.py", "ami_build_pkg/**/*.py",
    "conf/**/*.json", "conf/**/*.yaml", "conf/**/*.yml",
    "*.py", "pyproject.toml", "requirements*.txt",
]

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def make_manifest(root: Path, globs=DEFAULT_GLOBS):
    files = []
    for pat in globs:
        for p in root.glob(pat):
            if p.is_file():
                files.append({"path": str(p.relative_to(root)), "sha256": sha256(p)})
    return {"root": str(root), "files": sorted(files, key=lambda x: x["path"])}

def compare(a: dict, b: dict):
    A = {f["path"]: f["sha256"] for f in a["files"]}
    B = {f["path"]: f["sha256"] for f in b["files"]}
    adds = sorted(set(B) - set(A))
    dels = sorted(set(A) - set(B))
    mods = sorted(p for p in set(A) & set(B) if A[p] != B[p])
    return adds, dels, mods

def main():
    root = Path(".").resolve()
    if len(sys.argv) == 1:
        manifest = make_manifest(root)
        print(json.dumps(manifest, indent=2))
        return
    if sys.argv[1] == "--compare" and len(sys.argv) == 3:
        current = make_manifest(root)
        baseline = json.loads(Path(sys.argv[2]).read_text())
        adds, dels, mods = compare(baseline, current)
        print(json.dumps({"added": adds, "deleted": dels, "modified": mods}, indent=2))
        sys.exit(0 if not (adds or dels or mods) else 1)
    print("Usage: verify_sync.py [--compare BASELINE.json]"); sys.exit(2)

if __name__ == "__main__":
    main()

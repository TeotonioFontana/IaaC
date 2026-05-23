#!/usr/bin/env python3
import os, json, hashlib, sys
from pathlib import Path
from zipfile import ZipFile

def main(zip_path: str):
    z = Path(zip_path)
    if not z.exists():
        print(f"Zip not found: {z}")
        sys.exit(1)

    with ZipFile(z, "r") as zf:
        names = [n.replace("\\", "/").lstrip("./") for n in zf.namelist()]

    dirs = sorted({p for p in names if p.endswith("/")})
    files = sorted([p for p in names if not p.endswith("/")])

    # Build manifest with sizes + sha256 (without extracting)
    items = []
    with ZipFile(z, "r") as zf:
        for p in files:
            info = zf.getinfo(p)
            # sha256 of compressed stream is meaningless; compute of uncompressed bytes:
            data = zf.read(p)
            sha = hashlib.sha256(data).hexdigest()
            items.append({"path": p, "size": len(data), "sha256": sha})

    summary = {
        "zip_path": str(z.resolve()),
        "total_entries": len(names),
        "dirs_count": len(dirs),
        "files_count": len(files),
        "top_level": sorted({e.split("/", 1)[0] for e in names if e.strip()}),
        "package_roots": sorted({str(Path(x).parent) for x in files if x.endswith("__init__.py")}),
    }

    Path("codebase_zip_tree.txt").write_text("\n".join(names), encoding="utf-8")
    Path("codebase_zip_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path("codebase_zip_manifest.json").write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")

    print("Wrote:")
    print(" - codebase_zip_tree.txt")
    print(" - codebase_zip_summary.json")
    print(" - codebase_zip_manifest.json")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "codebase.zip")

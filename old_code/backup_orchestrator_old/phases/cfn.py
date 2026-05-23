# -*- coding: utf-8 -*-
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from ..utils import ensure_dir, run_cmd

def _cfn_export_completeness_check(path: Path) -> Tuple[bool, Dict[str, Any]]:
    exists = path.exists(); size = path.stat().st_size if exists else 0
    parsed_ok, resources_count, parse_error = False, None, None
    if exists and size > 0:
        try:
            try: import yaml  # type: ignore
            except Exception: yaml = None
            if yaml:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                parsed_ok = isinstance(data, dict)
                if isinstance(data, dict) and isinstance(data.get("Resources"), dict):
                    resources_count = len(data["Resources"])
            else:
                parsed_ok = "Resources:" in path.read_text(encoding="utf-8")
        except Exception as e:
            parse_error = str(e)
    missing = []
    if not exists: missing.append(str(path))
    elif size == 0: missing.append(f"{path} (empty)")
    elif parse_error: missing.append(f"{path} (YAML parse error: {parse_error})")
    complete = exists and size > 0 and (parsed_ok or parse_error is None)
    return complete, {"Result": "COMPLETE" if complete else "INCOMPLETE",
                      "Path": str(path), "Exists": exists, "SizeBytes": size,
                      "ParsedOK": parsed_ok, "ResourcesCount": resources_count,
                      "Missing": missing}

def _cfn_split_completeness_check(split_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    exists = split_dir.exists() and split_dir.is_dir()
    files, total_bytes, non_empty = [], 0, 0
    if exists:
        for p in list(split_dir.rglob("*.yaml")) + list(split_dir.rglob("*.yml")):
            files.append(p); sz = p.stat().st_size
            total_bytes += sz; non_empty += (1 if sz>0 else 0)
    missing=[]
    if not exists: missing.append(str(split_dir))
    elif not files: missing.append(f"{split_dir}/*.yaml (none)")
    elif non_empty==0: missing.append(f"{split_dir}/*.yaml (all empty)")
    complete = exists and bool(files) and non_empty>0
    return complete, {"Result": "COMPLETE" if complete else "INCOMPLETE",
                      "SplitDir": str(split_dir), "FilesFound": len(files),
                      "NonEmptyFiles": non_empty, "TotalBytes": total_bytes,
                      "Missing": missing, "Examples": [str(p) for p in files[:5]]}

def run_phase_2_export(args, scripts, tools_dir: Path, base_env: Dict[str,str]) -> bool:
    cf_root = ensure_dir(Path(args.out_root).expanduser().resolve()
                         / "cloud-formation" / "production" / args.source_region)
    exported_stack = cf_root / "exported_stack.yaml"
    cmd = [sys.executable, str(scripts["cfn_exporter"]),
           "--stack-name", args.stack_name or "tf-stack",
           "--output", str(exported_stack),
           "--regions", args.source_region]
    if isinstance(getattr(args,"module_configs",{}), dict):
        cfg = args.module_configs.get("cfn_exporter")
        if cfg: cmd += ["--config", cfg]
    res = run_cmd("CFN Export (cfn_exporter)", cmd, tools_dir, base_env, args.preview, args.simulate)
    if not res.ok and not args.keep_going: return False

    ok, summ = _cfn_export_completeness_check(exported_stack)
    print("-"*78); print("CFN Export Completeness Check — Phase 2"); print("-"*78)
    print(f"  Result ............. {summ.get('Result')}")
    print(f"  File ............... {summ.get('Path')}")
    print(f"  Exists/Size ........ {summ.get('Exists')}/{summ.get('SizeBytes')}")
    print(f"  Parsed OK .......... {summ.get('ParsedOK')}")
    if summ.get("ResourcesCount") is not None:
        print(f"  Resources (YAML) ... {summ['ResourcesCount']}")
    miss = summ.get("Missing", [])
    print(f"  Missing ............ {', '.join(miss) if miss else '(none)'}")
    print("-"*78)
    return ok or args.keep_going

def run_phase_3_split(args, scripts, tools_dir: Path, base_env: Dict[str,str]) -> bool:
    cf_root = ensure_dir(Path(args.out_root).expanduser().resolve()
                         / "cloud-formation" / "production" / args.source_region)
    split_dir = ensure_dir(cf_root / "split")
    input_path = cf_root / "exported_stack.yaml"
    cmd = [sys.executable, str(scripts["cfn_splitter"]), str(input_path),
           "--output", str(split_dir), "--region", args.source_region]
    if isinstance(getattr(args,"module_configs",{}), dict):
        cfg = args.module_configs.get("cfn_splitter")
        if cfg: cmd += ["--config", cfg]
    if args.dest_region: cmd += ["--dest-region", args.dest_region]
    if args.simulate: cmd += ["--dry-run"]
    res = run_cmd("CFN Split (cfn_splitter)", cmd, tools_dir, base_env, args.preview, args.simulate)
    if not res.ok and not args.keep_going: return False

    ok, summ = _cfn_split_completeness_check(split_dir)
    print("-"*78); print("CFN Split Completeness Check — Phase 3"); print("-"*78)
    print(f"  Result ............. {summ.get('Result')}")
    print(f"  Split Dir .......... {summ.get('SplitDir')}")
    print(f"  Files Found ........ {summ.get('FilesFound')} (non-empty={summ.get('NonEmptyFiles')})")
    print(f"  Total Bytes ........ {summ.get('TotalBytes')}")
    ex = summ.get("Examples") or []
    if ex: print("  Examples ........... " + "; ".join(ex))
    miss = summ.get("Missing", [])
    print(f"  Missing ............ {', '.join(miss) if miss else '(none)'}")
    print("-"*78)
    return ok or args.keep_going

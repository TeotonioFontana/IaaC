# -*- coding: utf-8 -*-
from __future__ import annotations
import json, sys
from typing import Any, Dict, List, Tuple
from pathlib import Path
from ..utils import run_cmd_capture, mode_label

def _extract_runs(raw: str) -> List[Dict[str, Any]]:
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and isinstance(obj.get("Runs"), list):
            return obj["Runs"]
    except Exception: pass
    idx = raw.rfind('"Runs"')
    if idx != -1:
        start = raw.rfind("{", 0, idx)
        if start != -1:
            cand = raw[start:].strip()
            for cut in range(len(cand), max(len(cand)-2000, 0), -1):
                chunk = cand[:cut]
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict) and isinstance(obj.get("Runs"), list):
                        return obj["Runs"]
                except Exception:
                    continue
    return []

def _completeness(tool_ok: bool, runs: List[Dict[str,Any]], mode_lbl: str) -> Tuple[bool, Dict[str,Any]]:
    count = len(runs); succ = sum(1 for r in runs if not r.get("Error")); fail = count - succ
    missing, notes = [], []
    if not tool_ok: missing.append("ami_build exited non-zero")
    if mode_lbl.startswith("PREVIEW"): notes.append("preview mode: no side effects or artifacts expected"); complete = tool_ok
    elif mode_lbl.startswith("SIMULATE"): notes.append("simulate mode: dry-run only; no AMIs created"); complete = tool_ok
    else:
        if count == 0: missing.append("no instances matched filters (Runs is empty)")
        if succ == 0: missing.append("no AMIs succeeded")
        complete = tool_ok and count>0 and succ>0
    return complete, {"Result": "COMPLETE" if complete else "INCOMPLETE", "Mode": mode_lbl,
                      "Counts": {"runs": count, "succeeded": succ, "failed": fail},
                      "Missing": missing, "Notes": notes, "Examples": runs[:3]}

def run_phase_5_ami(args, scripts, tools_dir: Path, base_env: Dict[str,str]) -> bool:
    print(f"[PLAN] ami_build: mode={'PREVIEW' if args.preview else 'SIMULATE' if args.simulate else 'EXECUTE'}  region={args.source_region}  dst={(args.dest_region or '(none)')}")
    cmd = [sys.executable, str(scripts["ami_build"]), "--region", args.source_region, "--yes"]
    if isinstance(getattr(args,"module_configs",{}), dict):
        ab_cfg = args.module_configs.get("ami_build")
        if ab_cfg: cmd += ["--config", ab_cfg]
    if args.dest_region: cmd += ["--dst-region", args.dest_region]
    if args.preview: cmd += ["--preview"]
    if args.simulate: cmd += ["--simulate"]

    res, raw = run_cmd_capture("AMI Build (ami_build)", cmd, tools_dir, base_env)
    runs = _extract_runs(raw)
    if runs:
        succ = sum(1 for r in runs if not r.get("Error")); fail = sum(1 for r in runs if r.get("Error"))
        print(f"[AMI] Summary: runs={len(runs)} succeeded={succ} failed={fail}")
    else:
        print("[AMI] No JSON run summary detected (normal in preview/simulate).")

    ok, summ = _completeness(res.ok, runs, mode_label(args.preview, args.simulate))
    print("-"*78); print("AMI Build Completeness Check — Phase 5"); print("-"*78)
    print(f"  Result ............. {summ.get('Result')}"); print(f"  Mode ............... {summ.get('Mode')}")
    cnt = summ.get("Counts", {})
    print(f"  Counts ............. runs={cnt.get('runs',0)} succeeded={cnt.get('succeeded',0)} failed={cnt.get('failed',0)}")
    notes = summ.get("Notes", [])
    if notes: print("  Notes .............. " + " | ".join(notes))
    miss = summ.get("Missing", [])
    print(f"  Missing ............ {', '.join(miss) if miss else '(none)'}"); print("-"*78)
    return ok or args.keep_going

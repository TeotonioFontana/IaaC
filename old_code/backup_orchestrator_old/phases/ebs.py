# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils import (
    ensure_dir,
    file_exists,
    run_cmd_capture,
    now_utc_iso,
    now_utc_for_filename,
    mode_label,
)

# ---------------- internal helpers ----------------

def _peek_config(path: Optional[Path]) -> dict:
    """Load a small subset of the ebs_backup config for printing a plan."""
    if not path or not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except Exception:
                return {}
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _print_ebs_plan(args, cfg_path: Optional[Path]) -> None:
    cfg = _peek_config(cfg_path) if cfg_path else {}
    backup_type   = cfg.get("backup_type") or "snapshot"
    src_region    = cfg.get("src_region") or args.source_region or "(default)"
    dst_region    = cfg.get("dst_region") or "(tool default)"
    states        = cfg.get("states") or "in-use,available"
    s3_bucket     = cfg.get("s3_bucket") or "(none)"
    s3_prefix     = cfg.get("s3_prefix") or "tf-backup/"
    helper        = cfg.get("helper_instance_id") or "(none)"
    full_bucket   = cfg.get("fullvol_s3_bucket") or s3_bucket or "(none)"
    full_format   = cfg.get("fullvol_format") or "raw.gz"
    encrypt_dst   = bool(cfg.get("encrypt_dst", True))
    kms_key       = cfg.get("kms_key_id") or "(default-key)"
    preview       = bool(cfg.get("preview", False) or args.preview)
    simulate      = bool(cfg.get("simulate", False) or args.simulate)
    mode = "PREVIEW" if preview else "SIMULATE" if simulate else "EXECUTE"

    print(
        f"[PLAN] ebs_backup: mode={mode}  type={backup_type}  src={src_region}  "
        f"dst={dst_region}  s3={s3_bucket or '(none)'}  helper={helper}  "
        f"enc={encrypt_dst}  kms={kms_key}"
    )
    print("       details:")
    print(f"         - states ............. {states}")
    print(f"         - s3 prefix .......... {s3_prefix}")
    print(f"         - full-volume bucket . {full_bucket}")
    print(f"         - full-volume format . {full_format}")
    if cfg_path:
        print(f"         - config file ........ {cfg_path}")
    else:
        print("         - config file ........ (not provided; using tool defaults)")

def _build_ebs_cmd(python_exec: str, script_path: Path, cfg_path: Optional[Path], args) -> List[str]:
    cmd = [python_exec, str(script_path)]
    if cfg_path:
        cmd += ["--config", str(cfg_path)]
    cmd += ["--yes", "--verbose"]
    if args.preview:
        cmd += ["--preview"]
    if args.simulate:
        cmd += ["--simulate"]
    return cmd

def _summarize_ebs_output(raw_text: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Parse ebs_backup console output for a discovery rollup and a few examples."""
    items: List[Dict[str, Any]] = []
    total_found: Optional[int] = None

    for line in raw_text.splitlines():
        if "DISCOVER:FOUND" in line:
            m = re.search(r"\{.*\}", line)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    if isinstance(obj, dict) and "Count" in obj:
                        total_found = int(obj["Count"])
                except Exception:
                    pass
        if "DISCOVER:ITEM" in line:
            m = re.search(r"\{.*\}\s*$", line)
            if not m:
                continue
            try:
                obj = json.loads(m.group(0))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            v = {
                "VolumeId": obj.get("VolumeId"),
                "SizeGiB": obj.get("SizeGiB"),
                "State": obj.get("State"),
                "AZ": obj.get("AZ"),
                "InstanceName": None,
            }
            atts = obj.get("Attachments") or []
            if isinstance(atts, list) and atts:
                first = atts[0] or {}
                v["InstanceName"] = first.get("InstanceName")
            items.append(v)

    by_state: Dict[str, int] = {}
    by_az: Dict[str, int] = {}
    attached = 0
    for it in items:
        st = it.get("State") or "unknown"
        az = it.get("AZ") or "unknown"
        by_state[st] = by_state.get(st, 0) + 1
        by_az[az] = by_az.get(az, 0) + 1
        if st == "in-use":
            attached += 1

    available = by_state.get("available", 0)
    total = total_found if total_found is not None else len(items)
    examples = items[:5]

    return {
        "total": total,
        "attached": attached,
        "available": available,
        "by_state": by_state,
        "by_az": by_az,
    }, examples

def _ebs_completeness_check(tool_ok: bool, summary: Dict[str, Any], mode: str) -> Tuple[bool, Dict[str, Any]]:
    missing: List[str] = []
    notes: List[str] = []
    total = int(summary.get("total", 0))

    if not tool_ok:
        missing.append("ebs_backup exited non-zero")

    if total == 0:
        missing.append("no EBS volumes matched the discovery filters")

    if mode.startswith("PREVIEW"):
        notes.append("preview mode: no side effects or artifacts expected")
    elif mode.startswith("SIMULATE"):
        notes.append("simulate mode: dry-run only; no snapshots/copies created")

    complete = tool_ok and total > 0
    return complete, {
        "Result": "COMPLETE" if complete else "INCOMPLETE",
        "Mode": mode,
        "Discovery": {
            "total": total,
            "attached": summary.get("attached", 0),
            "available": summary.get("available", 0),
            "by_state": summary.get("by_state", {}),
            "by_az": summary.get("by_az", {}),
        },
        "Missing": missing,
        "Notes": notes,
    }

def _resolve_ebs_config(args, tools_dir: Path) -> Optional[Path]:
    """
    Priority:
      1) args.module_configs['ebs_backup'] (if present and exists)
      2) args.ebs_config (if provided and exists)
      3) tools_dir/conf/backup-full-volumes.(json|yaml|yml) (first that exists)
    """
    # 1) module_configs
    mc = getattr(args, "module_configs", {}) or {}
    mc_path = mc.get("ebs_backup")
    if mc_path:
        p = Path(str(mc_path)).expanduser()
        if p.exists():
            return p.resolve()

    # 2) explicit ebs_config
    if getattr(args, "ebs_config", None):
        p = Path(str(args.ebs_config)).expanduser()
        if p.exists():
            return p.resolve()

    # 3) fallback defaults
    candidates = [
        tools_dir / "conf" / "backup-full-volumes.json",
        tools_dir / "conf" / "backup-full-volumes.yaml",
        tools_dir / "conf" / "backup-full-volumes.yml",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()

    return None

# ---------------- public phase entrypoint ----------------

def run_phase_4_ebs(args, scripts: Dict[str, Path], tools_dir: Path, base_env: Dict[str, str]) -> bool:
    ebs_script = scripts.get("ebs_backup")
    if not ebs_script or not file_exists(ebs_script):
        print(f"[FATAL] EBS backup module enabled but not found at {ebs_script}", file=sys.stderr)
        return False

    # Resolve config with the requested priority
    cfg_path = _resolve_ebs_config(args, tools_dir)
    if not cfg_path:
        print("[FATAL] EBS backup config not found.\n"
              "        Looked for:\n"
              f"          - module_configs.ebs_backup ({getattr(args, 'module_configs', {}).get('ebs_backup', '(unset)')})\n"
              f"          - --ebs-config ({getattr(args, 'ebs_config', '(unset)')})\n"
              f"          - {tools_dir/'conf'/'backup-full-volumes.json'}|.yaml|.yml",
              file=sys.stderr)
        return False

    # Update args so downstream prints show the chosen file
    args.ebs_config = str(cfg_path)

    # Print human plan
    _print_ebs_plan(args, cfg_path)

    # Build & show wrapped command
    cmd = _build_ebs_cmd(sys.executable, ebs_script, cfg_path, args)
    wrapped = " \\\n           ".join(shlex.quote(c) for c in cmd)
    print("       command (wrapped):")
    print(f"           {wrapped}")

    # Run and capture combined output
    step, raw = run_cmd_capture("EBS Backup (ebs_backup)", cmd, tools_dir, base_env)

    # Persist raw log
    out_root = ensure_dir(Path(args.out_root).expanduser().resolve())
    ebs_log_dir = ensure_dir(out_root / "backups" / "ebs")
    raw_name = f"ebs_raw_{now_utc_for_filename()}.log"
    raw_path = ebs_log_dir / raw_name
    try:
        raw_path.write_text(raw, encoding="utf-8")
        print(f"[EBS] Full raw log saved to: {raw_path}")
    except Exception as e:
        print(f"[WARN] Could not write raw ebs log: {e}", file=sys.stderr)

    # Summarize discovery
    summary, examples = _summarize_ebs_output(raw)
    print("[EBS] Summary (discovery):")
    print(f"       volumes .......... {summary.get('total', 0)} "
          f"(attached={summary.get('attached', 0)}, available={summary.get('available', 0)})")
    if summary.get("by_state"):
        pretty = ", ".join(f"{k}={v}" for k, v in sorted(summary["by_state"].items()))
        print(f"       by state ......... {pretty}")
    if summary.get("by_az"):
        pretty = ", ".join(f"{k}={v}" for k, v in sorted(summary["by_az"].items()))
        print(f"       by AZ ............ {pretty}")
    if examples:
        print("       examples:")
        for ex in examples:
            inst = ex.get("InstanceName") or "-"
            print(f"         - {ex.get('VolumeId')}  {ex.get('SizeGiB')} GiB  {ex.get('State')}  {ex.get('AZ')}  inst={inst}")

    if step.ok:
        print("[RESULT] ebs_backup finished OK (see summary above and raw log for details).")
    else:
        print(f"[RESULT] ebs_backup exited with code {step.returncode}. See raw log for details.", file=sys.stderr)

    # Completeness check
    ok, report = _ebs_completeness_check(step.ok, summary, mode_label(args.preview, args.simulate))
    print("-" * 78)
    print("EBS Backup Completeness Check — Phase 4")
    print("-" * 78)
    print(f"  Result ............. {report.get('Result')}")
    print(f"  Mode ............... {report.get('Mode')}")
    disc = report.get("Discovery", {})
    print(f"  Discovery .......... total={disc.get('total',0)} "
          f"attached={disc.get('attached',0)} available={disc.get('available',0)}")
    if disc.get("by_state"):
        print("  By State ........... " + ", ".join(f"{k}={v}" for k, v in sorted(disc["by_state"].items())))
    if disc.get("by_az"):
        print("  By AZ .............. " + ", ".join(f"{k}={v}" for k, v in sorted(disc["by_az"].items())))
    notes = report.get("Notes", [])
    if notes:
        print("  Notes .............. " + " | ".join(notes))
    missing = report.get("Missing", [])
    if missing:
        print("  Missing ............ " + ", ".join(missing))
    else:
        print("  Missing ............ (none)")
    print("-" * 78)

    return ok

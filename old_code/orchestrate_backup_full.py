#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orchestrate_backup.py — One-click snapshot for full-region recovery
===================================================================

Improved logging, human summaries, end-of-phase prompts (EXECUTE only),
inclusion of sso_assignments_exporter in Phase 1, real ami_build execution in
Phase 5 (honoring --preview/--simulate), and completeness checks for:

- Phase 1 (IDC)  + S3 mirror verification (NEW)
- Phase 2 (CFN export)
- Phase 3 (CFN split)
- Phase 4 (EBS backup)
- Phase 5 (AMI build)

Phase 4 always uses config file "backup-full-volumes" from tools_dir/conf/
(if --ebs-config is not provided).

Version: v0.2.1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------- constants / version ---------
VERSION = "v0.2.1"


# --------- tiny utils ---------
def now_utc_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def file_exists(p: Path) -> bool:
    try:
        return p.exists()
    except Exception:
        return False


def json_dump(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ----- Config helpers -----
def _load_config_file(path: str) -> dict:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        print(f"[FATAL] Config file not found: {cfg_path}", file=sys.stderr)
        sys.exit(2)
    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except Exception:
            print("[FATAL] YAML config supplied but PyYAML is not installed. Install with: pip install pyyaml", file=sys.stderr)
            sys.exit(2)
        return yaml.safe_load(text) or {}
    # fallback: JSON
    return json.loads(text or "{}")


def _normalize_modules(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        if "," in val:
            return [t.strip() for t in val.split(",") if t.strip()]
        return [val.strip()] if val.strip() else []
    return []


def _apply_config_defaults(args: argparse.Namespace, cfg: dict) -> argparse.Namespace:
    """Merge config into argparse result with CLI precedence (CLI wins)."""
    keymap = {
        "profile": "profile",
        "source_region": "source_region",
        "home_region": "home_region",
        "dest_region": "dest_region",
        "instance_arn": "instance_arn",
        "identity_store_id": "identity_store_id",
        "assume": "assume",
        "assume_sts_region": "assume_sts_region",
        "out_root": "out_root",
        "tools_dir": "tools_dir",
        "stack_name": "stack_name",
        "ebs_config": "ebs_config",
        "enabled_modules": "enabled_modules",
        # NEW: module_configs
        "module_configs": "module_configs",
        # Optional S3 mirror for Phase 3 CFN split
        "backup_region": "backup_region",
        "cfn_backup_path": "cfn_backup_path",
        # Optional S3 overrides for Phase 1 (IDC exporter), if you pass them via orchestrator CLI/config
        "s3_bucket": "s3_bucket",
        "s3_prefix": "s3_prefix",
        "s3_region": "s3_region",
        "s3_storage_class": "s3_storage_class",
        "s3_kms_key_id": "s3_kms_key_id",
    }

    for ck, attr in keymap.items():
        cur = getattr(args, attr, None)
        if (cur is None or cur == "" or (attr == "enabled_modules" and not cur)) and ck in cfg and cfg[ck] is not None:
            setattr(args, attr, cfg[ck])

    # store_true booleans: if CLI didn’t explicitly set True, adopt config value
    for ck, attr in [
        ("enable_ebs", "enable_ebs"),
        ("enable_ami", "enable_ami"),
        ("preview", "preview"),
        ("simulate", "simulate"),
        ("keep_going", "keep_going"),
    ]:
        cli_val = getattr(args, attr, False)
        if not cli_val and isinstance(cfg.get(ck), bool):
            setattr(args, attr, bool(cfg[ck]))

    # normalize modules
    args.enabled_modules = _normalize_modules(getattr(args, "enabled_modules", None))

    # module_configs should be dict-like
    if not isinstance(getattr(args, "module_configs", {}), dict):
        args.module_configs = {}

    return args


def _scripts_map(tools_dir: Path) -> Dict[str, Path]:
    return {
        "sso_exporter": tools_dir / "sso_exporter.py",
        "sso_assignments_exporter": tools_dir / "sso_assignments_exporter.py",
        "cfn_exporter": tools_dir / "cfn_exporter.py",
        "cfn_splitter": tools_dir / "cfn_splitter.py",
        "ebs_backup": tools_dir / "ebs_backup.py",
        "ami_build": tools_dir / "ami_build.py",
    }


def _mode_label(args: argparse.Namespace) -> str:
    if args.preview:
        return "PREVIEW (no side effects)"
    if args.simulate:
        return "SIMULATE (read-only + dry-run where supported)"
    return "EXECUTE"


def print_banner(args: argparse.Namespace) -> None:
    print(f"[START] Orchestrator — Full region snapshot — {VERSION}")
    print("        Purpose: produce a portable, consistent export for IDC + CFN + AMI/EBS")
    print(f"        Started (UTC): {now_utc_iso()}")
    print(f"        Source region (read-only): {args.source_region}")
    print(f"        Home region (IDC APIs)   : {args.home_region}")
    print(f"        Profile: {args.profile or '(default)'}")
    print(f"        Mode: {_mode_label(args)}")
    if args.enabled_modules:
        print(f"        Enabled modules: {', '.join(args.enabled_modules)}")
    if getattr(args, "module_configs", None):
        print("        Module configs:")
        for k, v in args.module_configs.items():
            print(f"          - {k}: {v}")


def phase_banner(idx: int, total: int, title: str, module: str) -> None:
    print("=" * 78)
    print(f"===== PHASE {idx}/{total}: {title} =====")
    print(f"      Module: {module}")
    print("=" * 78)


def _maybe_pause_after_phase(args: argparse.Namespace, title: str) -> None:
    """In EXECUTE mode, prompt the operator before continuing."""
    if args.preview or args.simulate:
        return
    try:
        ans = input(f"[PROMPT] {title} complete. Continue to next phase? [Y/n]: ").strip().lower()
    except EOFError:
        ans = ""
    if ans in ("n", "no"):
        print("[ABORTED] operator chose to stop.", file=sys.stderr)
        sys.exit(1)


# ----- Phase-4 friendly summary helpers (EBS) -----
def _peek_config(path: Path) -> dict:
    """Load a small subset of ebs_backup config to print a concise plan."""
    if not path:
        return {}
    try:
        txt = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except Exception:
                return {}
            data = yaml.safe_load(txt) or {}
        else:
            data = json.loads(txt or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _print_ebs_plan(args: argparse.Namespace) -> None:
    cfg_path = Path(args.ebs_config).expanduser() if getattr(args, "ebs_config", None) else None
    cfg = _peek_config(cfg_path) if cfg_path and cfg_path.exists() else {}

    backup_type = (cfg.get("backup_type") or "snapshot")
    src_region = (cfg.get("src_region") or args.source_region or "(default)")
    dst_region = (cfg.get("dst_region") or "(tool default)")
    states = (cfg.get("states") or "in-use,available")
    s3_bucket = (cfg.get("s3_bucket") or "(none)")
    s3_prefix = (cfg.get("s3_prefix") or "tf-backup/")
    helper = (cfg.get("helper_instance_id") or "(none)")
    fullvol_bucket = (cfg.get("fullvol_s3_bucket") or s3_bucket or "(none)")
    fullvol_format = (cfg.get("fullvol_format") or "raw.gz")
    encrypt_dst = cfg.get("encrypt_dst", True)
    kms_key = (cfg.get("kms_key_id") or "(default-key)")
    preview = bool(cfg.get("preview", False) or args.preview)
    simulate = bool(cfg.get("simulate", False) or args.simulate)

    mode = "PREVIEW" if preview else "SIMULATE" if simulate else "EXECUTE"
    print(f"[PLAN] ebs_backup: mode={mode}  type={backup_type}  src={src_region}  dst={dst_region}  "
          f"s3={s3_bucket or '(none)'}  helper={helper}  enc={encrypt_dst}  kms={kms_key}")
    print("       details:")
    print(f"         - states ............. {states}")
    print(f"         - s3 prefix .......... {s3_prefix}")
    print(f"         - full-volume bucket . {fullvol_bucket}")
    print(f"         - full-volume format . {fullvol_format}")
    if not cfg_path:
        print("         - config file ........ (not provided; using tool defaults)")
    else:
        print(f"         - config file ........ {cfg_path}")


def _build_ebs_cmd(args: argparse.Namespace, script_path: Path) -> List[str]:
    ebs_cmd = [sys.executable, str(script_path)]
    if getattr(args, "ebs_config", None):
        ebs_cmd += ["--config", args.ebs_config]
    ebs_cmd += ["--yes", "--verbose"]
    if args.preview:
        ebs_cmd += ["--preview"]
    if args.simulate:
        ebs_cmd += ["--simulate"]
    return ebs_cmd


def _summarize_ebs_output(raw_text: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Parse the ebs_backup console output to build:
      - summary dict (counts by state, by AZ, total)
      - few representative volume examples
    """
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

    summary = {
        "total": total,
        "attached": attached,
        "available": available,
        "by_state": by_state,
        "by_az": by_az,
    }
    return summary, examples


# ----- IDC completeness helper (Phase 1) -----
def _idc_completeness_check(idc_region_root: Path) -> Tuple[bool, Dict[str, Any]]:
    def _read_json(p: Path) -> dict:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    ident_dir = idc_region_root / "identity-store"
    ps_dir = ident_dir / "permission-sets"
    asg_dir = idc_region_root / "assignments"

    users_count = _read_json(ident_dir / "users.json").get("Count", 0)
    groups_count = _read_json(ident_dir / "groups.json").get("Count", 0)
    memberships_count = _read_json(ident_dir / "group-memberships.json").get("Count", 0)

    ps_index = _read_json(ps_dir / "index.json")
    if ps_index:
        ps_count = int(ps_index.get("Count") or len(ps_index.get("Items") or []))
    else:
        ps_count = sum(1 for p in ps_dir.glob("*.json") if p.name != "index.json")

    asg_manifest = _read_json(asg_dir / "manifest.json")
    assignment_files = 0
    by_acct = asg_dir / "by-account"
    if by_acct.exists():
        for acct_dir in by_acct.iterdir():
            if acct_dir.is_dir():
                assignment_files += sum(1 for f in acct_dir.glob("*.json") if f.name != "_index.json")

    missing: List[str] = []
    if users_count == 0:
        missing.append("identity-store/users.json")
    if groups_count == 0:
        missing.append("identity-store/groups.json")
    if memberships_count == 0:
        missing.append("identity-store/group-memberships.json")
    if ps_count == 0:
        missing.append("identity-store/permission-sets/*.json")
    if not asg_manifest or assignment_files == 0:
        missing.append("assignments/*.json")

    complete = len(missing) == 0

    summary = {
        "Result": "COMPLETE" if complete else "INCOMPLETE",
        "Counts": {
            "users": users_count,
            "groups": groups_count,
            "group_memberships": memberships_count,
            "permission_sets": ps_count,
            "assignment_files": assignment_files,
        },
        "Missing": missing,
    }
    return complete, summary


# ----- NEW: S3 verification for Phase 1 (IDC) when mirroring is enabled -----
# boto3 optional import (only used here). If unavailable, we report gracefully.
try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError, BotoCoreError  # type: ignore
except Exception:
    boto3 = None  # type: ignore
    ClientError = None  # type: ignore
    BotoCoreError = None  # type: ignore


def _gather_idc_paths(out_dir: Path) -> List[Path]:
    """Match the SSO exporter’s file layout under identity-store/."""
    paths: List[Path] = []
    for name in ("users.json", "groups.json", "group-memberships.json"):
        p = out_dir / name
        if p.exists():
            paths.append(p)
    ps_dir = out_dir / "permission-sets"
    if ps_dir.exists():
        paths.extend(sorted(ps_dir.glob("*.json")))
    return paths


def _verify_idc_s3_mirror(
    out_dir: Path,
    bucket: str,
    prefix: Optional[str],
    s3_region: Optional[str],
    profile: Optional[str],
) -> Tuple[bool, Dict[str, Any]]:
    if boto3 is None:
        return False, {"Error": "boto3 not installed; cannot verify S3 mirror"}

    # Build S3 client with optional profile/region
    sess_kwargs: Dict[str, Any] = {}
    if profile:
        sess_kwargs["profile_name"] = profile
    session = boto3.Session(region_name=s3_region, **sess_kwargs)
    s3 = session.client("s3")

    files = _gather_idc_paths(out_dir)
    px = (prefix or "").strip("/")
    missing: List[str] = []
    checked = 0

    for p in files:
        rel = p.relative_to(out_dir).as_posix()
        key = f"{px}/{rel}" if px else rel
        try:
            s3.head_object(Bucket=bucket, Key=key)
            checked += 1
        except Exception:
            missing.append(key)

    ok = len(missing) == 0 and checked == len(files)
    return ok, {
        "Bucket": bucket,
        "Prefix": px,
        "Checked": checked,
        "Expected": len(files),
        "Missing": missing,
    }


# ----- CFN completeness helpers (Phase 2 & 3) -----
def _cfn_export_completeness_check(exported_stack_path: Path) -> Tuple[bool, Dict[str, Any]]:
    exists = exported_stack_path.exists()
    size = exported_stack_path.stat().st_size if exists else 0
    parsed_ok = False
    resources_count = None
    parse_error = None

    if exists and size > 0:
        try:
            try:
                import yaml  # type: ignore
            except Exception:
                yaml = None
            if yaml:
                data = yaml.safe_load(exported_stack_path.read_text(encoding="utf-8")) or {}
                parsed_ok = isinstance(data, dict)
                if isinstance(data, dict) and "Resources" in data and isinstance(data["Resources"], dict):
                    resources_count = len(data["Resources"])
            else:
                text = exported_stack_path.read_text(encoding="utf-8")
                parsed_ok = "Resources:" in text
        except Exception as e:
            parse_error = str(e)

    missing: List[str] = []
    if not exists:
        missing.append(str(exported_stack_path))
    elif size == 0:
        missing.append(f"{exported_stack_path} (empty)")
    elif parse_error:
        missing.append(f"{exported_stack_path} (YAML parse error: {parse_error})")

    complete = exists and size > 0 and (parsed_ok or parse_error is None)

    summary = {
        "Result": "COMPLETE" if complete else "INCOMPLETE",
        "Path": str(exported_stack_path),
        "Exists": exists,
        "SizeBytes": size,
        "ParsedOK": parsed_ok,
        "ResourcesCount": resources_count,
        "Missing": missing,
    }
    return complete, summary


def _cfn_split_completeness_check(split_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    exists = split_dir.exists() and split_dir.is_dir()
    yaml_files: List[Path] = []
    total_bytes = 0
    non_empty = 0

    if exists:
        for p in list(split_dir.rglob("*.yaml")) + list(split_dir.rglob("*.yml")):
            yaml_files.append(p)
            try:
                sz = p.stat().st_size
            except Exception:
                sz = 0
            total_bytes += sz
            if sz > 0:
                non_empty += 1

    missing: List[str] = []
    if not exists:
        missing.append(str(split_dir))
    elif len(yaml_files) == 0:
        missing.append(f"{split_dir}/*.yaml (none)")
    elif non_empty == 0:
        missing.append(f"{split_dir}/*.yaml (all empty)")

    complete = exists and len(yaml_files) > 0 and non_empty > 0

    summary = {
        "Result": "COMPLETE" if complete else "INCOMPLETE",
        "SplitDir": str(split_dir),
        "FilesFound": len(yaml_files),
        "NonEmptyFiles": non_empty,
        "TotalBytes": total_bytes,
        "Missing": missing,
        "Examples": [str(p) for p in yaml_files[:5]],
    }
    return complete, summary


# ----- Resolve EBS config (Phase 4 helper) -----
def _resolve_ebs_config(args: argparse.Namespace, tools_dir: Path) -> Path:
    """
    Use --ebs-config if provided, else try:
      tools_dir/conf/backup-full-volumes.json
      tools_dir/conf/backup-full-volumes.yaml
      tools_dir/conf/backup-full-volumes.yml
    Fail fast if no candidate exists.
    """
    if getattr(args, "ebs_config", None):
        return Path(args.ebs_config).expanduser().resolve()

    candidates = [
        tools_dir / "conf" / "backup-full-volumes.json",
        tools_dir / "conf" / "backup-full-volumes.yaml",
        tools_dir / "conf" / "backup-full-volumes.yml",
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()

    print("[FATAL] EBS backup config not found. Expected one of:", file=sys.stderr)
    for p in candidates:
        print(f"        - {p}", file=sys.stderr)
    print("        Or pass --ebs-config <path> in your YAML/CLI.", file=sys.stderr)
    sys.exit(2)


# ----- EBS completeness helper (Phase 4) -----
def _ebs_completeness_check(
    tool_ok: bool,
    raw_summary: Dict[str, Any],
    mode_label: str
) -> Tuple[bool, Dict[str, Any]]:
    """
    A pragmatic completeness check based on the tool's exit code and the discovery
    rollup parsed from its logs.
    """
    missing: List[str] = []
    notes: List[str] = []
    total = int(raw_summary.get("total", 0))

    if not tool_ok:
        missing.append("ebs_backup exited non-zero")

    if total == 0:
        missing.append("no EBS volumes matched the discovery filters")

    # Mode awareness
    if mode_label.startswith("PREVIEW"):
        notes.append("preview mode: no side effects or artifacts expected")
    elif mode_label.startswith("SIMULATE"):
        notes.append("simulate mode: dry-run only; no snapshots/copies created")

    complete = tool_ok and total > 0

    return complete, {
        "Result": "COMPLETE" if complete else "INCOMPLETE",
        "Mode": mode_label,
        "Discovery": {
            "total": total,
            "by_state": raw_summary.get("by_state", {}),
            "by_az": raw_summary.get("by_az", {}),
            "attached": raw_summary.get("attached", 0),
            "available": raw_summary.get("available", 0),
        },
        "Missing": missing,
        "Notes": notes,
    }


# ----- AMI completeness helpers (Phase 5) -----
def _extract_ami_runs(raw_text: str) -> List[Dict[str, Any]]:
    """
    ami_build.py writes a human banner to stderr and a JSON object with {"Runs":[...]} to stdout.
    Since we capture both, try to parse the JSON block heuristically.
    """
    # Fast path: whole blob is JSON
    try:
        obj = json.loads(raw_text)
        if isinstance(obj, dict) and "Runs" in obj and isinstance(obj["Runs"], list):
            return obj["Runs"]
    except Exception:
        pass

    # Heuristic: find last JSON-looking chunk that starts with '{' and contains "Runs"
    idx = raw_text.rfind('"Runs"')
    if idx != -1:
        # Walk back to a '{' before "Runs"
        start = raw_text.rfind("{", 0, idx)
        if start != -1:
            candidate = raw_text[start:].strip()
            # Try parse progressively trimming trailing noise
            for cut in range(len(candidate), max(len(candidate) - 2000, 0), -1):
                chunk = candidate[:cut]
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict) and isinstance(obj.get("Runs"), list):
                        return obj["Runs"]
                except Exception:
                    continue
    return []


def _ami_completeness_check(tool_ok: bool, runs: List[Dict[str, Any]], mode_label: str) -> Tuple[bool, Dict[str, Any]]:
    count = len(runs)
    succeeded = sum(1 for r in runs if not r.get("Error"))
    failed = sum(1 for r in runs if r.get("Error"))

    missing: List[str] = []
    notes: List[str] = []

    if not tool_ok:
        missing.append("ami_build exited non-zero")

    if mode_label.startswith("PREVIEW"):
        notes.append("preview mode: no side effects or artifacts expected")
        complete = tool_ok
    elif mode_label.startswith("SIMULATE"):
        notes.append("simulate mode: dry-run only; no AMIs created")
        complete = tool_ok
    else:
        # EXECUTE: require at least one success
        if count == 0:
            missing.append("no instances matched filters (Runs is empty)")
        if succeeded == 0:
            missing.append("no AMIs succeeded")
        complete = tool_ok and count > 0 and succeeded > 0

    summary = {
        "Result": "COMPLETE" if complete else "INCOMPLETE",
        "Mode": mode_label,
        "Counts": {"runs": count, "succeeded": succeeded, "failed": failed},
        "Missing": missing,
        "Notes": notes,
        "Examples": runs[:3],
    }
    return complete, summary


@dataclass
class StepResult:
    name: str
    ok: bool
    returncode: int
    cmd: List[str]
    cwd: str
    started: str
    ended: str
    notes: Dict[str, Any] = field(default_factory=dict)


def run_cmd(name: str, cmd: List[str], cwd: Path, env: Dict[str, str],
            preview: bool, simulate: bool) -> StepResult:
    started = now_utc_iso()
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"[STEP] {name}")
    print(f"       cwd={cwd}")
    print(f"       cmd={printable}")

    if preview:
        print("       preview: skipped")
        return StepResult(name, True, 0, cmd, str(cwd), started, now_utc_iso(), {"mode": "preview"})

    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=False)
        ok = proc.returncode == 0
        return StepResult(name, ok, proc.returncode, cmd, str(cwd), started, now_utc_iso())
    except KeyboardInterrupt:
        print("\n[ABORTED] by user")
        raise
    except Exception as e:
        print(f"[FATAL] Step {name} failed to launch: {e}", file=sys.stderr)
        return StepResult(name, False, 127, cmd, str(cwd), started, now_utc_iso(), {"exception": str(e)})


def run_cmd_capture(name: str, cmd: List[str], cwd: Path, env: Dict[str, str]) -> Tuple[StepResult, str]:
    """Run a command and capture BOTH stdout and stderr as text."""
    started = now_utc_iso()
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"[STEP] {name}")
    print(f"       cwd={cwd}")
    print(f"       cmd={printable}")
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False
        )
        raw = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
        res = StepResult(name, ok, proc.returncode, cmd, str(cwd), started, now_utc_iso())
        return res, raw
    except KeyboardInterrupt:
        print("\n[ABORTED] by user")
        raise
    except Exception as e:
        print(f"[FATAL] Step {name} failed to launch: {e}", file=sys.stderr)
        res = StepResult(name, False, 127, cmd, str(cwd), started, now_utc_iso(), {"exception": str(e)})
        return res, ""


# --------- Orchestration ---------
def orchestrate(args: argparse.Namespace) -> int:
    print_banner(args)

    tools_dir = Path(args.tools_dir).expanduser().resolve()
    scripts = _scripts_map(tools_dir)

    # Default modules if none specified
    if not args.enabled_modules:
        args.enabled_modules = ["sso_exporter", "cfn_exporter", "cfn_splitter"]

    # Early fatal: any explicitly enabled module must exist
    missing_required = [m for m in args.enabled_modules if not file_exists(scripts.get(m, Path("/nonexistent")))]
    if missing_required:
        for m in missing_required:
            print(f"[FATAL] Required module '{m}' not found at {scripts.get(m)}", file=sys.stderr)
        return 2

    # Resolve output directories
    out_root = Path(args.out_root).expanduser().resolve()
    cf_root = ensure_dir(out_root / "cloud-formation" / "production" / args.source_region)
    idc_root = ensure_dir(out_root / "idc")
    backups_root = ensure_dir(out_root / "backups")
    ebs_logs_root = ensure_dir(backups_root / "ebs")

    manifest: Dict[str, Any] = {
        "version": VERSION,
        "started_utc": now_utc_iso(),
        "source_region": args.source_region,
        "home_region": args.home_region,
        "profile": args.profile or "(default)",
        "mode": "preview" if args.preview else "simulate" if args.simulate else "execute",
        "enabled_modules": args.enabled_modules,
        "steps": [],
    }

    # Common env for child processes
    base_env = os.environ.copy()
    if args.profile:
        base_env["AWS_PROFILE"] = args.profile

    step_results: List[StepResult] = []
    phase_total = 5
    phase_idx = 0

    # ---- Phase 1: IDC export(s) ----
    if "sso_exporter" in args.enabled_modules:
        phase_idx += 1
        phase_banner(phase_idx, phase_total, "IDC Export", "sso_exporter (+ assignments)")

        # Paths
        idc_out = ensure_dir(idc_root / args.source_region / "identity-store")

        # Build sso_exporter command
        sso_cmd = [
            sys.executable, str(scripts["sso_exporter"]),
            "--region", args.home_region,
            "--out-dir", str(idc_out),
        ]
        # module config, if present
        sso_cfg_path = None
        if isinstance(getattr(args, "module_configs", {}), dict):
            sso_cfg_path = args.module_configs.get("sso_exporter")
            if sso_cfg_path:
                sso_cmd += ["--config", sso_cfg_path]

        if args.instance_arn:
            sso_cmd += ["--instance-arn", args.instance_arn]
        if args.identity_store_id:
            sso_cmd += ["--identity-store-id", args.identity_store_id]
        if args.assume:
            sso_cmd += ["--assume", args.assume]
            if args.assume_sts_region:
                sso_cmd += ["--assume-sts-region", args.assume_sts_region]

        # Optional: allow orchestrator-level overrides for S3 (not required if module config sets them)
        for flag, attr in [
            ("--s3-bucket", "s3_bucket"),
            ("--s3-prefix", "s3_prefix"),
            ("--s3-region", "s3_region"),
            ("--s3-storage-class", "s3_storage_class"),
            ("--s3-kms-key-id", "s3_kms_key_id"),
        ]:
            val = getattr(args, attr, None)
            if val:
                sso_cmd += [flag, str(val)]

        res = run_cmd("IDC Export (sso_exporter)", sso_cmd, tools_dir, base_env, args.preview, args.simulate)
        step_results.append(res)
        manifest["steps"].append(res.__dict__)
        if not res.ok and not args.keep_going:
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return res.returncode or 1

        # Assignments (optional module)
        if "sso_assignments_exporter" in args.enabled_modules and file_exists(scripts["sso_assignments_exporter"]):
            idc_base = ensure_dir(idc_root / args.source_region)
            ssoa_cmd = [
                sys.executable, str(scripts["sso_assignments_exporter"]),
                "--region", args.home_region,
                "--out-dir", str(idc_base),
            ]
            # module config for assignments, if present
            ssoa_cfg_path = None
            if isinstance(getattr(args, "module_configs", {}), dict):
                ssoa_cfg_path = args.module_configs.get("sso_assignments_exporter")
                if ssoa_cfg_path:
                    ssoa_cmd += ["--config", ssoa_cfg_path]

            if args.instance_arn:
                ssoa_cmd += ["--instance-arn", args.instance_arn]
            if args.assume:
                ssoa_cmd += ["--assume", args.assume]
                if args.assume_sts_region:
                    ssoa_cmd += ["--assume-sts-region", args.assume_sts_region]
            if args.preview:
                ssoa_cmd += ["--preview"]
            if args.simulate:
                ssoa_cmd += ["--simulate"]

            res2 = run_cmd("IDC Assignments Export (sso_assignments_exporter)", ssoa_cmd, tools_dir, base_env, args.preview, args.simulate)
            step_results.append(res2)
            manifest["steps"].append(res2.__dict__)
            if not res2.ok and not args.keep_going:
                manifest["ended_utc"] = now_utc_iso()
                json_dump(out_root / "manifest.json", manifest)
                return res2.returncode or 1

        # 1C) IDC completeness check (local)
        idc_region_root = ensure_dir(idc_root / args.source_region)
        ok_local, s_local = _idc_completeness_check(idc_region_root)
        print("-" * 78)
        print("IDC Completeness Check — required artifacts for full IDC recovery")
        print("-" * 78)
        print(f"  Result ............. {s_local.get('Result')}")
        c = s_local.get("Counts", {})
        print(f"  Counts ............. users={c.get('users',0)} groups={c.get('groups',0)} "
              f"group-memberships={c.get('group_memberships',0)} permission-sets={c.get('permission_sets',0)} "
              f"assignment-files={c.get('assignment_files',0)}")
        missing_local = s_local.get("Missing", [])
        if missing_local:
            print(f"  Missing ............ {', '.join(missing_local)}")
        else:
            print("  Missing ............ (none)")
        print("-" * 78)

        # 1D) NEW — S3 mirror verification if sso_exporter config has S3
        s3_verified = True
        if sso_cfg_path:
            try:
                sso_cfg = _load_config_file(sso_cfg_path)
            except Exception as e:
                sso_cfg = {}
                print(f"[WARN] Could not read sso_exporter config for S3 verification: {e}", file=sys.stderr)

            s3_bucket = (sso_cfg or {}).get("s3_bucket") or getattr(args, "s3_bucket", None)
            s3_prefix = (sso_cfg or {}).get("s3_prefix") or getattr(args, "s3_prefix", None)
            s3_region = (sso_cfg or {}).get("s3_region") or getattr(args, "s3_region", None) or args.home_region

            if s3_bucket:
                idc_out_dir = idc_region_root / "identity-store"
                if args.preview or args.simulate:
                    print("S3 Mirror Check ..... skipped (preview/simulate)")
                else:
                    ok_s3, s3_summary = _verify_idc_s3_mirror(
                        idc_out_dir, s3_bucket, s3_prefix, s3_region, args.profile
                    )
                    s3_verified = ok_s3
                    status = "OK" if ok_s3 else "MISSING"
                    miss = s3_summary.get("Missing", [])
                    print(f"S3 Mirror Check ..... {status} (checked={s3_summary.get('Checked',0)}/{s3_summary.get('Expected',0)} in s3://{s3_summary.get('Bucket')}/{s3_summary.get('Prefix','')})")
                    if miss:
                        sample = "; ".join(miss[:5])
                        print(f"  Missing keys ...... {len(miss)} (e.g., {sample}{' ...' if len(miss)>5 else ''})")
                    print("-" * 78)

        # Fold S3 verification into completeness
        complete_phase1 = ok_local and s3_verified

        # Stop immediately if Phase 1 failed and keep_going is not set
        if not complete_phase1 and not args.keep_going:
            print("[FATAL] Phase 1 completeness failed; aborting.", file=sys.stderr)
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return 2

        _maybe_pause_after_phase(args, "Phase 1 (IDC Export)")

    # ---- Phase 2: CFN export ----
    if "cfn_exporter" in args.enabled_modules:
        phase_idx += 1
        phase_banner(phase_idx, phase_total, "CFN Export", "cfn_exporter")

        exported_stack = cf_root / "exported_stack.yaml"
        cfnexp_cmd = [
            sys.executable, str(scripts["cfn_exporter"]),
            "--stack-name", args.stack_name or "tf-stack",
            "--output", str(exported_stack),
            "--regions", args.source_region,
        ]
        # module config, if present
        if isinstance(getattr(args, "module_configs", {}), dict):
            cfn_cfg = args.module_configs.get("cfn_exporter")
            if cfn_cfg:
                cfnexp_cmd += ["--config", cfn_cfg]

        res = run_cmd("CFN Export (cfn_exporter)", cfnexp_cmd, tools_dir, base_env, args.preview, args.simulate)
        step_results.append(res)
        manifest["steps"].append(res.__dict__)
        if not res.ok and not args.keep_going:
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return res.returncode or 1

        ok2, s2 = _cfn_export_completeness_check(exported_stack)
        print("-" * 78)
        print("CFN Export Completeness Check — Phase 2")
        print("-" * 78)
        print(f"  Result ............. {s2.get('Result')}")
        print(f"  File ............... {s2.get('Path')}")
        print(f"  Exists/Size ........ {s2.get('Exists')}/{s2.get('SizeBytes')}")
        print(f"  Parsed OK .......... {s2.get('ParsedOK')}")
        rcnt = s2.get("ResourcesCount")
        if rcnt is not None:
            print(f"  Resources (YAML) ... {rcnt}")
        miss2 = s2.get("Missing", [])
        if miss2:
            print(f"  Missing ............ {', '.join(miss2)}")
        else:
            print("  Missing ............ (none)")
        print("-" * 78)

        if not ok2 and not args.keep_going:
            print("[FATAL] Phase 2 completeness failed; aborting.", file=sys.stderr)
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return 2

        _maybe_pause_after_phase(args, "Phase 2 (CFN Export)")

    # ---- Phase 3: CFN splitter ----
    if "cfn_splitter" in args.enabled_modules:
        phase_idx += 1
        phase_banner(phase_idx, phase_total, "CFN Split", "cfn_splitter")

        split_dir = ensure_dir(cf_root / "split")
        input_path = cf_root / "exported_stack.yaml"
        splitter_cmd = [
            sys.executable, str(scripts["cfn_splitter"]),
            str(input_path),
            "--output", str(split_dir),
            "--region", args.source_region,
        ]
        # module config, if present
        if isinstance(getattr(args, "module_configs", {}), dict):
            cfs_cfg = args.module_configs.get("cfn_splitter")
            if cfs_cfg:
                splitter_cmd += ["--config", cfs_cfg]

        if args.dest_region:
            splitter_cmd += ["--dest-region", args.dest_region]
        if args.simulate:
            splitter_cmd += ["--dry-run"]
        res = run_cmd("CFN Split (cfn_splitter)", splitter_cmd, tools_dir, base_env, args.preview, args.simulate)
        step_results.append(res)
        manifest["steps"].append(res.__dict__)
        if not res.ok and not args.keep_going:
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return res.returncode or 1

        ok3, s3 = _cfn_split_completeness_check(split_dir)
        print("-" * 78)
        print("CFN Split Completeness Check — Phase 3")
        print("-" * 78)
        print(f"  Result ............. {s3.get('Result')}")
        print(f"  Split Dir .......... {s3.get('SplitDir')}")
        print(f"  Files Found ........ {s3.get('FilesFound')} (non-empty={s3.get('NonEmptyFiles')})")
        print(f"  Total Bytes ........ {s3.get('TotalBytes')}")
        ex = s3.get("Examples") or []
        if ex:
            print("  Examples ........... " + "; ".join(ex))
        miss3 = s3.get("Missing", [])
        if miss3:
            print(f"  Missing ............ {', '.join(miss3)}")
        else:
            print("  Missing ............ (none)")
        print("-" * 78)

        if not ok3 and not args.keep_going:
            print("[FATAL] Phase 3 completeness failed; aborting.", file=sys.stderr)
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return 2

        _maybe_pause_after_phase(args, "Phase 3 (CFN Split)")

    # ---- Phase 4: EBS backups (using config file + completeness check) ----
    if args.enable_ebs:
        phase_idx += 1
        phase_banner(phase_idx, phase_total, "EBS Backups", "ebs_backup")

        if not file_exists(scripts["ebs_backup"]):
            print(f"[FATAL] EBS backup module enabled but not found at {scripts['ebs_backup']}", file=sys.stderr)
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return 2

        # Resolve ebs config (prefer --ebs-config, else backup-full-volumes.* in tools_dir/conf/)
        cfg_path = _resolve_ebs_config(args, tools_dir)
        args.ebs_config = str(cfg_path)

        # Human plan
        _print_ebs_plan(args)

        ebs_cmd = _build_ebs_cmd(args, scripts["ebs_backup"])
        wrapped = " \\\n           ".join(shlex.quote(c) for c in ebs_cmd)
        print("       command (wrapped):")
        print(f"           {wrapped}")

        # Run & capture raw log
        res, raw = run_cmd_capture("EBS Backup (ebs_backup)", ebs_cmd, tools_dir, base_env)

        # Save raw log
        ebs_logs_root = ensure_dir(out_root / "backups" / "ebs")
        raw_name = f"ebs_raw_{now_utc_for_filename()}.log"
        raw_path = ebs_logs_root / raw_name
        try:
            raw_path.write_text(raw, encoding="utf-8")
            print(f"[EBS] Full raw log saved to: {raw_path}")
        except Exception as e:
            print(f"[WARN] Could not write raw ebs log: {e}", file=sys.stderr)

        # Human summary of discovery
        summary, examples = _summarize_ebs_output(raw)
        print("[EBS] Summary (discovery):")
        print(f"       volumes .......... {summary.get('total', 0)} "
              f"(attached={summary.get('attached', 0)}, available={summary.get('available', 0)})")
        by_state = summary.get("by_state", {})
        if by_state:
            pretty = ", ".join(f"{k}={v}" for k, v in sorted(by_state.items()))
            print(f"       by state ......... {pretty}")
        by_az = summary.get("by_az", {})
        if by_az:
            pretty = ", ".join(f"{k}={v}" for k, v in sorted(by_az.items()))
            print(f"       by AZ ............ {pretty}")

        if examples:
            print("       examples:")
            for ex in examples:
                iid = ex.get("InstanceName") or "-"
                print(f"         - {ex.get('VolumeId')}  {ex.get('SizeGiB')} GiB  {ex.get('State')}  {ex.get('AZ')}  inst={iid}")

        if res.ok:
            print("[RESULT] ebs_backup finished OK (see summary above and raw log for details).")
        else:
            print(f"[RESULT] ebs_backup exited with code {res.returncode}. See raw log for details.", file=sys.stderr)

        # Phase-4 completeness check
        mode = _mode_label(args)
        ok4, s4 = _ebs_completeness_check(res.ok, summary, mode)
        print("-" * 78)
        print("EBS Backup Completeness Check — Phase 4")
        print("-" * 78)
        print(f"  Result ............. {s4.get('Result')}")
        print(f"  Mode ............... {s4.get('Mode')}")
        disc = s4.get("Discovery", {})
        print(f"  Discovery .......... total={disc.get('total',0)} attached={disc.get('attached',0)} available={disc.get('available',0)}")
        if disc.get("by_state"):
            print("  By State ........... " + ", ".join(f"{k}={v}" for k,v in sorted(disc["by_state"].items())))
        if disc.get("by_az"):
            print("  By AZ .............. " + ", ".join(f"{k}={v}" for k,v in sorted(disc["by_az"].items())))
        notes = s4.get("Notes", [])
        if notes:
            print("  Notes .............. " + " | ".join(notes))
        missing4 = s4.get("Missing", [])
        if missing4:
            print(f"  Missing ............ {', '.join(missing4)}")
        else:
            print("  Missing ............ (none)")
        print("-" * 78)

        step_results.append(res)
        manifest["steps"].append(res.__dict__)
        if not ok4 and not args.keep_going:
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return res.returncode or 1

        _maybe_pause_after_phase(args, "Phase 4 (EBS Backups)")
    else:
        print("[INFO] EBS backup step disabled (skipped).")

    # ---- Phase 5: AMI build (with completeness check) ----
    phase_idx += 1
    phase_banner(phase_idx, phase_total, "AMI Build", "ami_build")
    if args.enable_ami:
        if not file_exists(scripts["ami_build"]):
            print(f"[FATAL] AMI build module enabled but not found at {scripts['ami_build']}", file=sys.stderr)
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return 2

        mode = "PREVIEW" if args.preview else "SIMULATE" if args.simulate else "EXECUTE"
        print(f"[PLAN] ami_build: mode={mode}  region={args.source_region}  dst={(args.dest_region or '(none)')}")

        ami_cmd = [sys.executable, str(scripts["ami_build"]),
                   "--region", args.source_region,
                   "--yes"]
        if isinstance(getattr(args, "module_configs", {}), dict):
            ab_cfg = args.module_configs.get("ami_build")
            if ab_cfg:
                ami_cmd += ["--config", ab_cfg]
        if args.dest_region:
            ami_cmd += ["--dst-region", args.dest_region]
        if args.preview:
            ami_cmd += ["--preview"]
        if args.simulate:
            ami_cmd += ["--simulate"]

        # Capture stdout+stderr so we can parse the {"Runs":[...]} JSON
        res, raw = run_cmd_capture("AMI Build (ami_build)", ami_cmd, tools_dir, base_env)

        # Extract runs summary from the emitted JSON (if present)
        runs = _extract_ami_runs(raw)

        # Human mini-summary
        if runs:
            succ = sum(1 for r in runs if not r.get("Error"))
            fail = sum(1 for r in runs if r.get("Error"))
            print(f"[AMI] Summary: runs={len(runs)} succeeded={succ} failed={fail}")
        else:
            print("[AMI] No JSON run summary detected in tool output (this can be normal in preview/simulate).")

        # Phase-5 completeness check
        ok5, s5 = _ami_completeness_check(res.ok, runs, _mode_label(args))
        print("-" * 78)
        print("AMI Build Completeness Check — Phase 5")
        print("-" * 78)
        print(f"  Result ............. {s5.get('Result')}")
        print(f"  Mode ............... {s5.get('Mode')}")
        cnt = s5.get("Counts", {})
        print(f"  Counts ............. runs={cnt.get('runs',0)} succeeded={cnt.get('succeeded',0)} failed={cnt.get('failed',0)}")
        notes5 = s5.get("Notes", [])
        if notes5:
            print("  Notes .............. " + " | ".join(notes5))
        miss5 = s5.get("Missing", [])
        if miss5:
            print(f"  Missing ............ {', '.join(miss5)}")
        else:
            print("  Missing ............ (none)")
        print("-" * 78)

        step_results.append(res)
        manifest["steps"].append(res.__dict__)
        if not res.ok and not args.keep_going:
            manifest["ended_utc"] = now_utc_iso()
            json_dump(out_root / "manifest.json", manifest)
            return res.returncode or 1
    else:
        print("[INFO] AMI backup step disabled (skipped).")

    manifest["ended_utc"] = now_utc_iso()
    json_dump(out_root / "manifest.json", manifest)
    print(f"[DONE] Orchestration complete. Manifest -> {out_root / 'manifest.json'}")
    return 0 if all(r.ok for r in step_results) else 1


# --------- CLI ---------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Orchestrate full-region snapshot (IDC + CFN + AMI/EBS)")

    # Config file (YAML/JSON)
    p.add_argument("--config", help="YAML/JSON config file with run settings, including module_configs")

    # Core flags
    p.add_argument("--profile", help="AWS named profile (Architect for source account)")

    # Regions
    p.add_argument("--source-region", help="Region to EXPORT from (treated as read-only)")
    p.add_argument("--home-region", help="IAM Identity Center HOME region (sso-admin/identitystore)")
    p.add_argument("--dest-region", help="Optional target region to prepare artifacts for (splitter hint)")

    # IDC instance identifiers (optional if discovery is allowed by permissions)
    p.add_argument("--instance-arn", help="Identity Center InstanceArn (arn:aws:sso:::instance/ssoins-...)")
    p.add_argument("--identity-store-id", help="IdentityStoreId (d-xxxxxxxxxx)")

    # Assume-role for IDC export (recommended)
    p.add_argument("--assume", dest="assume", help="Role ARN to assume for sso_exporter (read-only)")
    p.add_argument("--assume-sts-region", default=None, help="Region to call STS AssumeRole for --assume")

    # Output & tools
    p.add_argument("--out-root", help="Root directory for all outputs (idc/, cloud-formation/, backups/...)")
    p.add_argument("--tools-dir", help="Directory containing the helper scripts (sso_exporter.py, cfn_exporter.py, ...)")

    # CFN export options
    p.add_argument("--stack-name", default=None, help="Logical name to label the exported CFN template")

    # Backups
    p.add_argument("--enable-ebs", action="store_true", help="Run EBS backup step if ebs_backup.py is present")
    p.add_argument("--ebs-config", help="Path to ebs_backup.py config JSON (used if --enable_ebs)")
    p.add_argument("--enable-ami", action="store_true", help="Run AMI build step if ami_build.py is present")

    # Optional S3 mirror for Phase 3 CFN split (not required)
    p.add_argument("--backup-region", help="Region for S3 uploads (CFN split mirror).")
    p.add_argument("--cfn-backup-path", help="S3 URI (s3://bucket/prefix/) to mirror CFN split outputs.")

    # Optional S3 overrides for Phase 1 (IDC exporter) — useful if you prefer passing via orchestrator CLI
    p.add_argument("--s3-bucket", help="Destination S3 bucket to mirror the IDC export.")
    p.add_argument("--s3-prefix", help="Key prefix inside the destination bucket.")
    p.add_argument("--s3-region", help="S3 client region (default: --region of sso_exporter).")
    p.add_argument("--s3-storage-class",
                   choices=["STANDARD","STANDARD_IA","ONEZONE_IA","INTELLIGENT_TIERING","GLACIER_IR","GLACIER","DEEP_ARCHIVE","REDUCED_REDUNDANCY","EXPRESS_ONEZONE","OUTPOSTS","SNOW","FSX_OPENZFS"],
                   help="S3 storage class for mirrored objects (default: DEEP_ARCHIVE).")
    p.add_argument("--s3-kms-key-id", help="KMS key ARN/alias for SSE-KMS in destination account.")

    # Safety controls
    p.add_argument("--preview", action="store_true", help="Print what would run; do not execute")
    p.add_argument("--simulate", action="store_true", help="Safe simulation; pass dry-run flags where supported")
    p.add_argument("--keep-going", action="store_true", help="Continue remaining steps even if one fails")

    # Module selection
    p.add_argument("--enabled-modules", nargs="*", help="List or comma string: sso_exporter sso_assignments_exporter cfn_exporter cfn_splitter ebs_backup ami_build")

    return p.parse_args(argv)


def _require_after_merge(args: argparse.Namespace) -> None:
    missing = []
    for req in ("source_region", "home_region", "out_root", "tools_dir"):
        if not getattr(args, req, None):
            missing.append(req.replace("_", "-"))
    if missing:
        print("[FATAL] Missing required arguments (after applying --config): " + ", ".join(missing), file=sys.stderr)
        sys.exit(2)

    if not args.stack_name:
        args.stack_name = "tf-stack"
    if args.assume and not args.assume_sts_region:
        args.assume_sts_region = "us-east-1"

    args.enabled_modules = _normalize_modules(args.enabled_modules)
    if not isinstance(getattr(args, "module_configs", {}), dict):
        args.module_configs = {}


def main() -> None:
    args = parse_args()
    if args.config:
        cfg = _load_config_file(args.config)
        args = _apply_config_defaults(args, cfg)
    _require_after_merge(args)
    rc = orchestrate(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()

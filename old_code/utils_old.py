# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os, shlex, subprocess, sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

def now_utc_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def now_utc_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True); return p

def file_exists(p: Path) -> bool:
    try: return p.exists()
    except Exception: return False

def json_dump(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_config_file(path: str) -> dict:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        print(f"[FATAL] Config file not found: {cfg_path}", file=sys.stderr); sys.exit(2)
    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in (".yaml",".yml"):
        try: import yaml  # type: ignore
        except Exception:
            print("[FATAL] YAML config provided but PyYAML not installed. pip install pyyaml", file=sys.stderr); sys.exit(2)
        return (yaml.safe_load(text) or {})  # type: ignore
    return json.loads(text or "{}")

def normalize_list(val: Any) -> List[str]:
    if val is None: return []
    if isinstance(val, list): return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        if "," in val: return [t.strip() for t in val.split(",") if t.strip()]
        v = val.strip(); return [v] if v else []
    return []

def scripts_map(tools_dir: Path) -> Dict[str, Path]:
    return {
        "sso_exporter": tools_dir / "sso_exporter.py",
        "sso_assignments_exporter": tools_dir / "sso_assignments_exporter.py",
        "cfn_exporter": tools_dir / "cfn_exporter.py",
        "cfn_splitter": tools_dir / "cfn_splitter.py",
        "ebs_backup": tools_dir / "ebs_backup.py",
        "ami_build": tools_dir / "ami_build.py",
    }

def mode_label(arg_or_preview, simulate=None) -> str:
    """
    Back-compat shim:
      - mode_label(args)                 -> works
      - mode_label(preview, simulate)    -> works
    """
    if simulate is None:
        preview = bool(getattr(arg_or_preview, "preview", False))
        simulate = bool(getattr(arg_or_preview, "simulate", False))
    else:
        preview = bool(arg_or_preview)
        simulate = bool(simulate)

    if preview:
        return "PREVIEW (no side effects)"
    if simulate:
        return "SIMULATE (read-only + dry-run where supported)"
    return "EXECUTE"

def print_banner(name: str, version: str, args) -> None:
    print(f"[START] {name} — {version}")
    print("        Purpose: produce a portable, consistent export for IDC + CFN + AMI/EBS")
    print(f"        Started (UTC): {now_utc_iso()}")
    print(f"        Source region (read-only): {args.source_region}")
    print(f"        Home region (IDC APIs)   : {args.home_region}")
    print(f"        Profile: {args.profile or '(default)'}")
    print(f"        Mode: {mode_label(args.preview, args.simulate)}")
    if args.enabled_modules:
        print(f"        Enabled modules: {', '.join(args.enabled_modules)}")
    if getattr(args, 'module_configs', None):
        print("        Module configs:")
        for k, v in args.module_configs.items():
            print(f"          - {k}: {v}")

def phase_banner(idx: int, total: int, title: str, module: str) -> None:
    print("="*78)
    print(f"===== PHASE {idx}/{total}: {title} =====")
    print(f"      Module: {module}")
    print("="*78)

def maybe_pause_after_phase(args, title: str) -> None:
    if args.preview or args.simulate: return
    try: ans = input(f"[PROMPT] {title} complete. Continue to next phase? [Y/n]: ").strip().lower()
    except EOFError: ans = ""
    if ans in ("n","no"):
        print("[ABORTED] operator chose to stop.", file=sys.stderr); sys.exit(1)

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

def run_cmd(name: str, cmd: List[str], cwd: Path, env: Dict[str,str],
            preview: bool, simulate: bool) -> StepResult:
    started = now_utc_iso()
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"[STEP] {name}"); print(f"       cwd={cwd}"); print(f"       cmd={printable}")
    if preview:
        print("       preview: skipped")
        return StepResult(name, True, 0, cmd, str(cwd), started, now_utc_iso(), {"mode":"preview"})
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=False)
        ok = (proc.returncode == 0)
        return StepResult(name, ok, proc.returncode, cmd, str(cwd), started, now_utc_iso())
    except KeyboardInterrupt:
        print("\n[ABORTED] by user"); raise
    except Exception as e:
        print(f"[FATAL] Step {name} failed to launch: {e}", file=sys.stderr)
        return StepResult(name, False, 127, cmd, str(cwd), started, now_utc_iso(), {"exception": str(e)})

def run_cmd_capture(name: str, cmd: List[str], cwd: Path, env: Dict[str,str]) -> Tuple[StepResult, str]:
    started = now_utc_iso()
    printable = " ".join(shlex.quote(c) for c in cmd)
    print(f"[STEP] {name}"); print(f"       cwd={cwd}"); print(f"       cmd={printable}")
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, check=False)
        raw = (proc.stdout or "") + (proc.stderr or "")
        ok = (proc.returncode == 0)
        res = StepResult(name, ok, proc.returncode, cmd, str(cwd), started, now_utc_iso())
        return res, raw
    except KeyboardInterrupt:
        print("\n[ABORTED] by user"); raise
    except Exception as e:
        print(f"[FATAL] Step {name} failed to launch: {e}", file=sys.stderr)
        res = StepResult(name, False, 127, cmd, str(cwd), started, now_utc_iso(), {"exception": str(e)})
        return res, ""

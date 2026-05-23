# -*- coding: utf-8 -*-
"""
===============================================================================
 audit_config_validator.py — v2.0.0 (2025-11-02)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Recovery Audit Package
 Purpose............: Core subsystem of the IaaC Recovery Suite (Audit + Recovery)
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 This module is part of the v2.0 refactor: modular, testable, SaaS‑ready.
===============================================================================
"""

from __future__ import annotations

import sys
import re
import json
import argparse
from pathlib import Path
from typing import Any, Dict, Tuple

RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")  # e.g., 20251031T235959Z
ALLOWED_DETAIL = {"summary", "detailed", "full"}
ALLOWED_LOG_FORMAT = {"text", "json", "both"}
ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}

SCHEMA = {
    "audit": ["profile", "region", "bucket", "root_prefix", "simulate", "run_id", "report_path"],
    "prefixes": ["base", "discover", "plan", "prep", "backup", "manifest", "logs", "artifacts", "indexes", "latest"],
    "policy": ["stop_on_missing_manifest", "validate_snapshots", "validate_fullvol_exports", "check_latest_pointer", "detect_orphans"],
    "report": ["s3_upload_prefix", "detail_level"],
    "recovery_test": ["enable_recovery_simulation", "test_region", "restore_prefix"],
    "logging": ["log_file", "format", "level"],
}

PREFIX_KEYS_REQUIRE_RUN_ID = {"discover", "plan", "prep", "backup", "manifest", "logs", "artifacts", "indexes"}

def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        print(f"[FATAL] Config file not found: {path}")
        sys.exit(3)
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    try:
        import yaml  # type: ignore
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data is None:
                data = {}
            return data
    except Exception as e:
        print(f"[FATAL] Unable to read YAML config: {e}")
        sys.exit(3)

def _require_sections(cfg: Dict[str, Any]) -> None:
    for section in SCHEMA.keys():
        if section not in cfg:
            raise ValueError(f"Missing required section: '{section}'")
    for top in cfg.keys():
        if top not in SCHEMA:
            raise ValueError(f"Unknown top-level key: '{top}'")

def _validate_prefixes(cfg: Dict[str, Any]) -> None:
    pfx = cfg["prefixes"]
    base = pfx["base"].rstrip("/")
    for key in SCHEMA["prefixes"]:
        val = pfx[key]
        if key in PREFIX_KEYS_REQUIRE_RUN_ID and "{run_id}" not in val:
            raise ValueError(f"'prefixes.{key}' must include '{{run_id}}' placeholder (got {val!r})")
        if key != "latest":
            if not val.startswith(base):
                raise ValueError(f"'prefixes.{key}' must start with base prefix '{base}' (got '{val}')")

def _validate_types_and_values(cfg: Dict[str, Any]) -> None:
    if cfg["logging"]["format"] not in ALLOWED_LOG_FORMAT:
        raise ValueError("logging.format must be one of: text|json|both")
    if cfg["logging"]["level"] not in ALLOWED_LOG_LEVELS:
        raise ValueError("logging.level must be one of: DEBUG|INFO|WARNING|ERROR")
    if cfg["report"]["detail_level"] not in ALLOWED_DETAIL:
        raise ValueError("report.detail_level must be one of: summary|detailed|full")

def _apply_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    cfg["audit"]["run_id"] = args.run_id
    if args.report:
        cfg["audit"]["report_path"] = args.report
    if args.simulate:
        cfg["audit"]["simulate"] = True
    if args.verify_snapshots:
        cfg["policy"]["validate_snapshots"] = True
    if args.log_level:
        cfg["logging"]["level"] = args.log_level
    if args.verbose:
        cfg["logging"]["level"] = "DEBUG"
    if args.log_format:
        cfg["logging"]["format"] = args.log_format

def print_config_summary(cfg: Dict[str, Any]) -> None:
    a = cfg["audit"]; pfx = cfg["prefixes"]; pol = cfg["policy"]; rep = cfg["report"]; rct = cfg["recovery_test"]; log = cfg["logging"]
    print("✓ Configuration validated successfully\n")
    print("[Audit]")
    for k in ("profile","region","bucket","root_prefix","simulate","run_id","report_path"):
        print(f"  {k:12s}: {a.get(k)}")
    print("\n[Prefixes]")
    for k in ("base","discover","plan","prep","backup","manifest","logs","artifacts","indexes","latest"):
        print(f"  {k:12s}: {pfx.get(k)}")
    print("\n[Policy]")
    for k in ("stop_on_missing_manifest","validate_snapshots","validate_fullvol_exports","check_latest_pointer","detect_orphans"):
        print(f"  {k:25s}: {pol.get(k)}")
    print("\n[Report]")
    print(f"  s3_upload_prefix: {rep.get('s3_upload_prefix')}")
    print(f"  detail_level    : {rep.get('detail_level')}")
    print("\n[Recovery Test]")
    for k in ("enable_recovery_simulation","test_region","restore_prefix"):
        print(f"  {k:25s}: {rct.get(k)}")
    print("\n[Logging]")
    for k in ("log_file","format","level"):
        print(f"  {k:12s}: {log.get(k)}")
    print()

def parse_args() -> Tuple[argparse.Namespace, Dict[str, Any]]:
    parser = argparse.ArgumentParser(description="S3 Recovery Audit Tool — v2.0 (strict validation)")
    parser.add_argument("--config", required=True, help="Path to config (.yaml/.yml/.json)")
    parser.add_argument("--run-id", required=True, help="Run identifier (UTC, e.g., 20251031T235959Z)")
    parser.add_argument("--report", help="Override audit.report_path")
    parser.add_argument("--simulate", action="store_true", help="Simulation mode (no AWS writes)")
    parser.add_argument("--verify-snapshots", action="store_true", help="Force EC2 snapshot validation")
    parser.add_argument("--validate-config", action="store_true", help="Validate and exit")
    parser.add_argument("--test-pdf", action="store_true", help="Generate synthetic PDF and exit")
    parser.add_argument("--log-level", default=None, help="Override log level (DEBUG|INFO|WARNING|ERROR)")
    parser.add_argument("--log-format", default=None, help="Override log format (text|json|both)")
    parser.add_argument("--verbose", action="store_true", help="Alias for --log-level DEBUG")
    args = parser.parse_args()

    if not RUN_ID_PATTERN.match(args.run_id):
        print("FATAL: Invalid --run-id format (expected YYYYMMDDTHHMMSSZ)")
        sys.exit(1)

    cfg = _load_config(Path(args.config))
    _require_sections(cfg)
    _validate_prefixes(cfg)
    _validate_types_and_values(cfg)

    _apply_overrides(cfg, args)

    if args.validate_config:
        print_config_summary(cfg)
        sys.exit(0)

    return args, cfg

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 audit_config_validator.py — v1.8.1 (2025-11-02)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Recovery Audit Package
 Purpose............: CLI + YAML/JSON validation and configuration management
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 v1.8.1 changes:
   • Enforces presence of all 9 S3 phase prefixes (discover → latest)
   • Validates region in audit section (mandatory)
   • Adds 'version' key at root (optional but logged)
   • Ensures base prefix consistency with other phase prefixes
   • Adds safer type checks and cleaner error messages
===============================================================================
"""

from __future__ import annotations

import sys
import re
import json
import argparse
from pathlib import Path
from typing import Any, Dict, Tuple, Mapping

# Safer YAML loader
from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError

# -----------------------------------------------------------------------------
# ANSI colors for CLI output
# -----------------------------------------------------------------------------
ANSI = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "RED": "\033[31m",
    "GRAY": "\033[90m",
}


def color_text(text: str, color: str) -> str:
    return f"{ANSI.get(color, '')}{text}{ANSI['RESET']}"


# -----------------------------------------------------------------------------
# Strict schema (ALL keys mandatory; unknown keys refused)
# -----------------------------------------------------------------------------
SCHEMA: Dict[str, Dict[str, Any]] = {
    "audit": {
        "profile": str,
        "region": str,
        "bucket": str,
        "root_prefix": str,
        "simulate": bool,
        "run_id": (str, type(None)),        # allow null in file; CLI overrides
        "report_path": str,
    },
    "prefixes": {
        "base": str,
        "discover": str,
        "plan": str,
        "prep": str,
        "backup": str,
        "manifest": str,
        "logs": str,
        "artifacts": str,
        "indexes": str,
        "latest": str,                      # may omit {run_id}
    },
    "policy": {
        "stop_on_missing_manifest": bool,
        "validate_snapshots": bool,
        "validate_fullvol_exports": bool,
        "check_latest_pointer": bool,
        "detect_orphans": bool,
    },
    "report": {
        "s3_upload_prefix": (str, type(None)),
        "detail_level": str,
        "pdf_output_dir": str,       # <-- new
    },
    "recovery_test": {
        "enable_recovery_simulation": bool,
        "test_region": str,
        "restore_prefix": str,
    },
    "logging": {
        "log_file": str,
        "format": str,
        "level": str,
    },
}

RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")  # e.g. 20251031T235959Z
ALLOWED_DETAIL = {"summary", "detailed", "full"}
ALLOWED_LOG_FORMAT = {"text", "json"}
ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}

# Prefix keys that MUST include {run_id}
PREFIX_KEYS_REQUIRE_RUN_ID = {
    "discover", "plan", "prep", "backup", "manifest", "logs", "artifacts", "indexes"
}


# -----------------------------------------------------------------------------
# YAML/JSON loading
# -----------------------------------------------------------------------------
def _load_yaml(path: Path) -> Dict[str, Any]:
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.load(f)
    except DuplicateKeyError as e:
        print(color_text(f"[FATAL] Duplicate YAML key: {e}", "RED"))
        sys.exit(3)
    except Exception as e:
        print(color_text(f"[FATAL] YAML parse error: {e}", "RED"))
        sys.exit(3)

    if data is None:
        data = {}
    if not isinstance(data, dict):
        print(color_text("[FATAL] Top-level YAML structure must be a mapping", "RED"))
        sys.exit(3)
    return data


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(color_text(f"[FATAL] JSON parse error: {e}", "RED"))
        sys.exit(3)
    if not isinstance(data, dict):
        print(color_text("[FATAL] Top-level JSON structure must be a mapping", "RED"))
        sys.exit(3)
    return data


def load_config_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        print(color_text(f"[FATAL] Config file not found: {path}", "RED"))
        sys.exit(3)
    ext = path.suffix.lower()
    if ext in (".yaml", ".yml"):
        return _load_yaml(path)
    if ext == ".json":
        return _load_json(path)
    print(color_text(f"[FATAL] Unsupported config format: {ext}", "RED"))
    sys.exit(3)


# -----------------------------------------------------------------------------
# Validation helpers
# -----------------------------------------------------------------------------
def _type_label(t: Any) -> str:
    if isinstance(t, tuple):
        return " | ".join(_type_label(x) for x in t)
    if t is type(None):
        return "null"
    return getattr(t, "__name__", str(t))


def _validate_section(name: str, data: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"Section '{name}' must be a mapping (got {type(data).__name__})")

    # Unknown keys
    for k in data.keys():
        if k not in schema:
            raise ValueError(f"Unknown key '{name}.{k}'")

    # Missing keys + type checks
    for k, expected in schema.items():
        if k not in data:
            raise ValueError(f"Missing key '{name}.{k}'")
        v = data[k]
        if not isinstance(v, expected):
            raise ValueError(
                f"Invalid type for '{name}.{k}': expected {_type_label(expected)}, got {type(v).__name__}"
            )

    # Value constraints (detail level, log format/level, prefix tokens)
    if name == "report":
        dl = data.get("detail_level")
        if dl not in ALLOWED_DETAIL:
            raise ValueError(f"Invalid 'report.detail_level'={dl!r}; expected one of {sorted(ALLOWED_DETAIL)}")
    if name == "logging":
        fmt = data.get("format")
        lvl = data.get("level")
        if fmt not in ALLOWED_LOG_FORMAT:
            raise ValueError(f"Invalid 'logging.format'={fmt!r}; expected one of {sorted(ALLOWED_LOG_FORMAT)}")
        if lvl not in ALLOWED_LOG_LEVELS:
            raise ValueError(f"Invalid 'logging.level'={lvl!r}; expected one of {sorted(ALLOWED_LOG_LEVELS)}")
    if name == "prefixes":
        base = data.get("base", "")
        for key, val in data.items():
            if key in PREFIX_KEYS_REQUIRE_RUN_ID and "{run_id}" not in val:
                raise ValueError(f"'prefixes.{key}' must include '{{run_id}}' placeholder (got {val!r})")
            if not val.startswith(base):
                raise ValueError(f"'prefixes.{key}' must start with base prefix '{base}' (got {val!r})")


def _validate_config_structure(cfg: Dict[str, Any]) -> None:
    # Optional version tracking
    if "version" in cfg and not isinstance(cfg["version"], (str, float)):
        raise ValueError("Top-level 'version' must be a string or numeric value.")

    # Top-level presence
    for section in SCHEMA.keys():
        if section not in cfg:
            raise ValueError(f"Missing required section: '{section}'")

    # Per-section validation + unknown top keys
    for section, schema in SCHEMA.items():
        _validate_section(section, cfg[section], schema)

    for top_key in cfg.keys():
        if top_key not in SCHEMA and top_key != "version":
            raise ValueError(f"Unknown top-level key: '{top_key}'")


# -----------------------------------------------------------------------------
# CLI argument parser (keeps your legacy flags)
# -----------------------------------------------------------------------------
def parse_args() -> Tuple[argparse.Namespace, Dict[str, Any]]:
    parser = argparse.ArgumentParser(
        description="S3 Recovery Audit Tool — Strict Validation Mode"
    )

    parser.add_argument("--config", required=True, help="Path to config file (.yaml/.yml/.json).")
    parser.add_argument("--run-id", required=True,
                        help="Run identifier (UTC, e.g., 20251031T235959Z). Mandatory by policy.")
    parser.add_argument("--report", help="Override output JSON report path (maps to audit.report_path).")
    parser.add_argument("--simulate", action="store_true",
                        help="Run in simulation mode (no AWS write operations).")
    parser.add_argument("--verify-snapshots", action="store_true",
                        help="Force EC2 snapshot validation regardless of config.")
    parser.add_argument("--test-pdf", action="store_true",
                        help="Generate a synthetic PDF report and exit (integration self-test).")
    parser.add_argument("--validate-config", action="store_true",
                        help="Validate config and exit without executing audit.")
    parser.add_argument("--log-level", default=None,
                        help="Override logging level (DEBUG, INFO, WARNING, ERROR).")
    parser.add_argument("--verbose", action="store_true",
                        help="Alias for --log-level DEBUG.")

    args = parser.parse_args()

    # Validate run-id format early
    if not RUN_ID_PATTERN.match(args.run_id):
        print(color_text("FATAL: Invalid --run-id format (expected YYYYMMDDTHHMMSSZ)", "RED"))
        sys.exit(1)

    cfg = load_config_file(Path(args.config))

    # Strict schema validation
    try:
        _validate_config_structure(cfg)
    except ValueError as e:
        print(color_text(f"[FATAL] {e}", "RED"))
        sys.exit(3)

    # Apply CLI overrides (only after successful validation)
    _apply_overrides(cfg, args)

    # Optional config validation summary-and-exit
    if args.validate_config:
        print_config_summary(cfg)
        sys.exit(0)

    # Sanity on region
    region = cfg.get("audit", {}).get("region", "")
    if not region:
        print(color_text("FATAL: Region not defined (audit.region).", "RED"))
        sys.exit(3)

    # Verbosity
    effective_level = args.log_level or cfg.get("logging", {}).get("level", "INFO")
    if args.verbose:
        effective_level = "DEBUG"
    if effective_level not in ALLOWED_LOG_LEVELS:
        print(color_text(f"FATAL: Invalid log level '{effective_level}'", "RED"))
        sys.exit(3)
    args.log_level = effective_level

    # Display short confirmation
    print(color_text(f"Run-ID: {args.run_id}   Region: {region}", "GRAY"))
    if "version" in cfg:
        print(color_text(f"Config schema version: {cfg['version']}", "GRAY"))

    return args, cfg


def _apply_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    """Apply CLI overrides over a validated config."""
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


# -----------------------------------------------------------------------------
# Presentation
# -----------------------------------------------------------------------------
def print_config_summary(cfg: Dict[str, Any]) -> None:
    a = cfg.get("audit", {})
    pfx = cfg.get("prefixes", {})
    pol = cfg.get("policy", {})
    rep = cfg.get("report", {})
    rct = cfg.get("recovery_test", {})
    log = cfg.get("logging", {})

    print(color_text("✓ Configuration validated successfully\n", "GREEN"))
    if "version" in cfg:
        print(f"Schema Version: {cfg['version']}\n")

    print(color_text("[Audit]", "BOLD"))
    print(f"  Profile:     {a.get('profile')}")
    print(f"  Region:      {a.get('region')}")
    print(f"  Bucket:      {a.get('bucket')}")
    print(f"  RootPrefix:  {a.get('root_prefix')}")
    print(f"  Simulate:    {a.get('simulate')}")
    print(f"  Run ID:      {a.get('run_id') or '(not set in file; provided via CLI)'}")
    print(f"  ReportPath:  {a.get('report_path')}\n")

    print(color_text("[Prefixes]", "BOLD"))
    for k in ("base", "discover", "plan", "prep", "backup", "manifest", "logs", "artifacts", "indexes", "latest"):
        print(f"  {k:10s}: {pfx.get(k)}")
    print()

    print(color_text("[Policy]", "BOLD"))
    for k in ("stop_on_missing_manifest", "validate_snapshots",
              "validate_fullvol_exports", "check_latest_pointer", "detect_orphans"):
        print(f"  {k:25s}: {pol.get(k)}")
    print()

    print(color_text("[Report]", "BOLD"))
    print(f"  s3_upload_prefix: {rep.get('s3_upload_prefix')}")
    print(f"  detail_level:     {rep.get('detail_level')}\n")

    print(color_text("[Recovery Test]", "BOLD"))
    print(f"  enable_recovery_simulation: {rct.get('enable_recovery_simulation')}")
    print(f"  test_region:                {rct.get('test_region')}")
    print(f"  restore_prefix:             {rct.get('restore_prefix')}\n")

    print(color_text("[Logging]", "BOLD"))
    print(f"  log_file: {log.get('log_file')}")
    print(f"  format:   {log.get('format')}")
    print(f"  level:    {log.get('level')}")
    print()


# -----------------------------------------------------------------------------
# Direct use guard
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    args, cfg = parse_args()
    print(color_text("Config+CLI successfully parsed (validator entrypoint).", "GREEN"))

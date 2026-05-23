#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 backup_config_validator.py — v4.0.0-alpha1
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestrator
 Purpose............: Strict YAML/JSON configuration and CLI validator
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Loads, validates, and merges runtime configuration for the Backup Orchestrator.
  • Enforces schema validation via JSON Schema (version-agnostic)
  • Provides CLI overrides for critical flags
  • Auto-generates run_id when missing
  • Uses unified ANSI palette for readable terminal feedback
===============================================================================
"""
from backup_orchestrator_pkg.result_envelope import enveloped

from __future__ import annotations
import sys, json, argparse, datetime
from pathlib import Path
from typing import Any, Dict, Tuple
from jsonschema import validate, ValidationError
import yaml

# Local imports
from iaactools.codebase.utils.logger_utils import color_text
from iaactools.codebase.utils.schema_loader import load_schema


# -----------------------------------------------------------------------------
# Helper — Generate ISO run_id if not provided
# -----------------------------------------------------------------------------
@enveloped(schema={})
def generate_run_id() -> str:
    return datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


# -----------------------------------------------------------------------------
# CLI Argument Parser
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="IaacTools Backup Orchestrator — Configuration Validator (v4.0.0-alpha1)"
    )

    parser.add_argument("--config", required=True,
                        help="Path to YAML or JSON configuration file.")
    parser.add_argument("--run-id", required=False,
                        help="Unique run identifier (UTC ISO format).")
    parser.add_argument("--simulate", action="store_true",
                        help="Run in simulation mode (no AWS write operations).")
    parser.add_argument("--mode", choices=["execute", "verify", "dryrun"], default=None,
                        help="Execution mode for orchestrator.")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        default=None, help="Override log verbosity.")
    parser.add_argument("--full-volume", action="store_true",
                        help="Force full-volume backup regardless of config.")
    parser.add_argument("--verbose", action="store_true",
                        help="Alias for --log-level DEBUG.")
    return parser.parse_args()


# -----------------------------------------------------------------------------
# Configuration Loader
# -----------------------------------------------------------------------------
def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        print(color_text(f"[FATAL] Config file not found: {path}", "RED"))
        sys.exit(3)

    try:
        with open(path, "r", encoding="utf-8") as f:
            if path.suffix.lower() in (".yaml", ".yml"):
                return yaml.safe_load(f) or {}
            if path.suffix.lower() == ".json":
                return json.load(f)
            raise ValueError("Unsupported config format (use .yaml or .json)")
    except Exception as e:
        print(color_text(f"[FATAL] Failed to load config: {e}", "RED"))
        sys.exit(3)


# -----------------------------------------------------------------------------
# Merge CLI Overrides
# -----------------------------------------------------------------------------
def apply_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    """Apply CLI flags after schema validation."""
    backup = cfg.get("backup", {})
    orchestrator = cfg.get("orchestrator", {})
    logging_cfg = cfg.get("logging", {})

    if args.run_id:
        backup["run_id"] = args.run_id
    else:
        backup["run_id"] = generate_run_id()
        print(color_text(f"[WARN] Run-ID not provided; auto-generated → {backup['run_id']}", "YELLOW"))

    if args.simulate:
        backup["simulate"] = True
    if args.mode:
        backup["mode"] = args.mode
    if args.full_volume:
        orchestrator["full_volume"] = True
    if args.verbose:
        logging_cfg["level"] = "DEBUG"
    elif args.log_level:
        logging_cfg["level"] = args.log_level

    cfg["backup"] = backup
    cfg["orchestrator"] = orchestrator
    cfg["logging"] = logging_cfg


# -----------------------------------------------------------------------------
# Schema Validation
# -----------------------------------------------------------------------------
def validate_schema(cfg: Dict[str, Any]) -> None:
    """Validate the config dict against backup_config_schema.json."""
    schema = load_schema("backup_config_schema.json")
    try:
        validate(instance=cfg, schema=schema)
        print(color_text("[OK] Schema validation passed.", "GREEN"))
    except ValidationError as e:
        print(color_text(f"[FATAL] Schema validation failed: {e.message}", "RED"))
        sys.exit(3)


# -----------------------------------------------------------------------------
# Entry Function — Used by Orchestrator
# -----------------------------------------------------------------------------
def parse_and_validate() -> Tuple[argparse.Namespace, Dict[str, Any]]:
    args = parse_args()
    cfg = load_config(Path(args.config))
    validate_schema(cfg)
    apply_overrides(cfg, args)
    run_id = cfg["backup"]["run_id"]
    print(color_text(f"[INFO] Configuration loaded successfully. Run-ID: {run_id}", "GREEN"))
    return args, cfg


# -----------------------------------------------------------------------------
# Direct Execution Guard
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    args, cfg = parse_and_validate()
    print(color_text(json.dumps(cfg, indent=2), "GRAY"))

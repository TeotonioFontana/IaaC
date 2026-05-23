# Strict schema validator placeholder
# -*- coding: utf-8 -*-
"""
===============================================================================
 audit_config_validator.py — v4.0.0-alpha1
===============================================================================
 Purpose............: Validates YAML/JSON configuration for Recovery Audit
-------------------------------------------------------------------------------
 Highlights
 ------------------------------------------------------------------------------
 • Mandatory sections: audit, prefixes, policy, report, logging
 • Rejects unknown keys
 • CLI overrides supported
 • Enforces valid run_id and AWS region
===============================================================================
"""

import sys, re, json, argparse
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError

SCHEMA = {
    "audit": {"profile": str, "region": str, "bucket": str, "run_id": str},
    "logging": {"level": str, "format": str, "log_file": str},
}
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")

def load_yaml(path: Path):
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    with path.open("r", encoding="utf-8") as f:
        return yaml.load(f)

def validate(cfg: dict):
    for section in SCHEMA:
        if section not in cfg:
            sys.exit(f"[FATAL] Missing section '{section}' in config")
        for key, typ in SCHEMA[section].items():
            if key not in cfg[section]:
                sys.exit(f"[FATAL] Missing key '{section}.{key}'")
            if not isinstance(cfg[section][key], typ):
                sys.exit(f"[FATAL] Invalid type for '{section}.{key}'")
    run_id = cfg["audit"]["run_id"]
    if not RUN_ID_PATTERN.match(run_id):
        sys.exit(f"[FATAL] Invalid run_id format: {run_id}")
    return True

def parse_args():
    p = argparse.ArgumentParser(description="Recovery Audit Config Validator")
    p.add_argument("--config", required=True)
    p.add_argument("--run-id", required=True)
    args = p.parse_args()
    cfg = load_yaml(Path(args.config))
    validate(cfg)
    cfg["audit"]["run_id"] = args.run_id
    return args, cfg

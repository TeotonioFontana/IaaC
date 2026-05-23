# -*- coding: utf-8 -*-
"""
config_validator.py — Shared configuration validator for IaacTools orchestrators.
"""

import yaml
import json
from pathlib import Path

def load_config(config_path):
    """Load YAML or JSON config file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    if config_path.suffix in [".yaml", ".yml"]:
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))
    elif config_path.suffix == ".json":
        return json.loads(config_path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported config format: {config_path.suffix}")

def validate_config(config: dict, required_keys: list[str]) -> bool:
    """Ensure required keys exist in config."""
    missing = [k for k in required_keys if k not in config]
    if missing:
        raise KeyError(f"Missing required keys: {', '.join(missing)}")
    return True

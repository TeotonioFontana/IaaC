# -*- coding: utf-8 -*-
"""
===============================================================================
 schema_loader.py — v1.0.0 (2025-11-05)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Shared JSON Schema Registry
 Purpose............: Centralized loader for all JSON schema definitions.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides a unified and version-agnostic interface for loading JSON schemas
 used by all IaaC Tools components — including backup, recovery, compliance,
 and audit orchestrators.

 This module prevents hardcoded paths and schema duplication, guaranteeing
 that all packages validate data using the same canonical JSON definitions.
===============================================================================
"""

import json
from importlib import resources
from typing import Dict, Any


def load_schema(name: str) -> Dict[str, Any]:
    """
    Load a JSON schema by filename (without extension).

    Args:
        name (str): Logical schema name (e.g., "backup_manifest_schema")

    Returns:
        dict: Parsed JSON schema

    Raises:
        RuntimeError: If schema file not found or malformed.
    """
    try:
        with resources.files(__package__).joinpath(f"{name}.json").open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"[FATAL] Schema not found: {name}.json in {__package__}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"[FATAL] Invalid JSON schema '{name}.json': {e}")
    except Exception as e:
        raise RuntimeError(f"[FATAL] Unexpected error loading schema '{name}.json': {e}") from e


def list_available_schemas() -> list[str]:
    """
    List all available schema JSON files under this package.

    Returns:
        list[str]: Available schema base names (without .json extension)
    """
    try:
        return [
            path.name.replace(".json", "")
            for path in resources.files(__package__).iterdir()
            if path.name.endswith(".json")
        ]
    except Exception as e:
        raise RuntimeError(f"Failed to list schemas in {__package__}: {e}") from e


# -----------------------------------------------------------------------------
# Smoke Test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== JSON Schema Loader Smoke Test ===")
    try:
        schemas = list_available_schemas()
        if not schemas:
            print("No schemas found.")
        for name in schemas:
            data = load_schema(name)
            print(f"✓ {name}.json loaded ({len(data)} keys)")
    except Exception as e:
        print(f"[FATAL] {e}")

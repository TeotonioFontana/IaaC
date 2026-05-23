#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 integrity_utils.py — v1.0.0
===============================================================================
 Purpose............: Shared integrity verification utilities for all IaacTools.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides standardized hashing and verification for all orchestrator phases.
 Every phase output JSON should be self-hashed (SHA-256) using these helpers.
===============================================================================
"""

import hashlib
import json
from pathlib import Path
import logging

# ----------------------------------------------------------------------
# ANSI color codes (shared for clarity in logs)
# ----------------------------------------------------------------------
ANSI = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "RED": "\033[31m",
    "GRAY": "\033[90m",
}


def color_text(text: str, color: str) -> str:
    """Return ANSI-colored text."""
    return f"{ANSI.get(color, '')}{text}{ANSI['RESET']}"


# ----------------------------------------------------------------------
# Core functions
# ----------------------------------------------------------------------
def compute_sha256(file_path: Path) -> str:
    """Compute a SHA-256 checksum for any file."""
    sha = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def embed_integrity_hash(file_path: Path, logger: logging.Logger | None = None) -> str:
    """
    Compute SHA256 and embed it inside a JSON file as 'IntegrityHash'.
    Returns the computed hash string.
    """
    hash_value = compute_sha256(file_path)

    try:
        with file_path.open("r+", encoding="utf-8") as f:
            data = json.load(f)
            data["IntegrityHash"] = hash_value
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
        if logger:
            logger.debug(color_text(f"Integrity hash embedded → {hash_value}", "GRAY"))
    except Exception as e:
        if logger:
            logger.error(color_text(f"Failed to embed hash: {e}", "RED"))
        raise
    return hash_value


def verify_integrity_hash(file_path: Path, logger: logging.Logger | None = None) -> bool:
    """
    Verify that the 'IntegrityHash' embedded in the JSON matches the current file hash.
    Returns True if valid, False if mismatched or missing.
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        saved_hash = data.get("IntegrityHash")
        if not saved_hash:
            if logger:
                logger.warning(color_text(f"No IntegrityHash found in {file_path.name}", "YELLOW"))
            return False
        actual_hash = compute_sha256(file_path)
        valid = saved_hash == actual_hash
        if logger:
            color = "GREEN" if valid else "RED"
            msg = f"{'✓' if valid else '✗'} Integrity check for {file_path.name} → {actual_hash}"
            logger.info(color_text(msg, color))
        return valid
    except Exception as e:
        if logger:
            logger.error(color_text(f"Integrity verification failed: {e}", "RED"))
        return False


def safe_save_json(obj: dict, file_path: Path, logger: logging.Logger | None = None) -> str:
    """
    Save a dictionary as JSON and embed an integrity hash.
    Returns the computed hash string.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    hash_value = embed_integrity_hash(file_path, logger)
    if logger:
        logger.debug(color_text(f"Saved {file_path.name} with hash {hash_value}", "GRAY"))
    return hash_value


# ----------------------------------------------------------------------
# CLI self-test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("IntegrityTest")

    temp = Path(tempfile.gettempdir()) / "integrity_test.json"
    sample = {"Test": "Integrity system"}
    print(color_text(f"Creating {temp}", "GRAY"))
    safe_save_json(sample, temp, logger)

    logger.info("Verifying saved file…")
    verify_integrity_hash(temp, logger)

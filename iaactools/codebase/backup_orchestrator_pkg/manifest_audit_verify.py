# -*- coding: utf-8 -*-
"""
===============================================================================
 manifest_audit_verify.py — v0.9.0-alpha
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestrator
 Purpose............: Verify integrity and authenticity of architecture manifests
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Reads a unified architecture manifest (and its referenced section files),
 re-computes SHA256 hashes, compares them against recorded digests, and
 verifies the optional AWS KMS signature.
===============================================================================
"""

import json
import hashlib
import boto3
from pathlib import Path
from typing import Dict, Any


# -----------------------------------------------------------------------------
# Core verification helpers
# -----------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    """Compute SHA-256 digest for a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sections(manifest: Dict[str, Any], base_dir: Path) -> bool:
    """Validate all section file hashes against recorded metadata."""
    ok = True
    print("\n────────── SECTION VERIFICATION ──────────")
    for key, meta in manifest["meta"]["sections"].items():
        section_path = base_dir / meta["path"]
        digest = sha256_file(section_path)
        if digest == meta["sha256"]:
            print(f"[OK]  {key}  ({meta['count']} items)")
        else:
            print(f"[FAIL] {key}  Expected={meta['sha256']} Got={digest}")
            ok = False
    return ok


def verify_overall_checksum(manifest: Dict[str, Any]) -> bool:
    """Re-hash all section digests and compare with top-level checksum."""
    hasher = hashlib.sha256()
    for meta in manifest["meta"]["sections"].values():
        hasher.update(meta["sha256"].encode())
    expected = manifest["meta"]["overall_checksum"].split("sha256:")[-1]
    result = hasher.hexdigest()
    print("\n────────── MANIFEST CHECKSUM ──────────")
    if expected == result:
        print(f"[OK]  sha256:{result}")
        return True
    print(f"[FAIL] Expected={expected}  Got={result}")
    return False


def verify_kms_signature(manifest_path: Path, manifest: Dict[str, Any], profile: str) -> bool:
    """Verify AWS KMS signature if present."""
    if "signature" not in manifest["meta"]:
        print("\n[SKIP] No KMS signature recorded.")
        return True

    alias_uri = manifest["meta"]["signature"]
    kms_alias = alias_uri.split("alias/")[-1]
    sig_path = manifest_path.with_suffix(".sig")
    if not sig_path.exists():
        print(f"[FAIL] Missing signature file: {sig_path}")
        return False

    kms = boto3.client("kms", profile_name=profile)
    signature = sig_path.read_bytes()
    with manifest_path.open("rb") as f:
        message = f.read()

    print("\n────────── SIGNATURE VERIFICATION ──────────")
    resp = kms.verify(
        KeyId=f"alias/{kms_alias}",
        Message=message,
        Signature=signature,
        MessageType="RAW",
        SigningAlgorithm="RSASSA_PSS_SHA_256",
    )
    if resp.get("SignatureValid"):
        print(f"[OK]  Signature verified with {kms_alias}")
        return True
    print(f"[FAIL] Signature invalid for {kms_alias}")
    return False


# -----------------------------------------------------------------------------
# Unified entry point
# -----------------------------------------------------------------------------
def verify_manifest(manifest_path: Path, profile: str) -> bool:
    """Perform all verification steps for the given manifest."""
    base_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    all_ok = True
    if not verify_sections(manifest, base_dir):
        all_ok = False
    if not verify_overall_checksum(manifest):
        all_ok = False
    if not verify_kms_signature(manifest_path, manifest, profile):
        all_ok = False

    print("\n══════════════════════════════════════════════════")
    print(f"Manifest verification result: {'PASS' if all_ok else 'FAIL'}")
    print("══════════════════════════════════════════════════")
    return all_ok


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verify architecture manifest integrity")
    parser.add_argument("--manifest", required=True, help="Path to architecture_manifest.json")
    parser.add_argument("--profile", required=True, help="AWS profile for KMS verification")
    args = parser.parse_args()

    verify_manifest(Path(args.manifest), args.profile)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 s3_recovery_audit.py — v1.8.1 (2025-11-02)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Recovery Audit Package
 Purpose............: Unified entrypoint for AWS recovery readiness audit
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 v1.8.1 introduces:
   • Integration with audit_core_logic v1.8.0 (multi-phase structure scanning)
   • Schema version awareness from audit_config_validator v1.8.1
   • Enhanced startup banner with schema + completeness notice
   • Consistent region-only configuration (no --region flag)
   • Hardened exception trapping and colored terminal feedback

 Provides a complete execution flow for:
   • Config validation (--validate-config)
   • IAM and credential verification
   • S3/EC2 audit execution and structure reporting
   • JSON/PDF generation and optional S3 upload
   • Simulation-safe operation (--simulate)
   • Synthetic PDF generation (--test-pdf)
===============================================================================
"""

from __future__ import annotations
import sys
import traceback
from old_code.recovery_audit_v1_pkg import audit_core_logic, audit_config_validator

__version__ = "1.8.1"


# -----------------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------------
def print_banner(cfg: dict | None = None) -> None:
    """Print a version banner including region, bucket, and schema version."""
    print("=" * 79)
    print(f"S3 Recovery Audit Tool — v{__version__}")
    print("© 2025 Teotoniio Fontana — IaaC Tools / Recovery Audit Package")
    if cfg and "audit" in cfg:
        region = cfg["audit"].get("region", "?")
        bucket = cfg["audit"].get("bucket", "?")
        schema_ver = cfg.get("version", "unknown")
        print(f"Configured Region: {region}   Bucket: {bucket}")
        print(f"Schema Version:    {schema_ver}")
        print("-" * 79)
        print("Includes multi-phase S3 structure verification "
              "(discover → latest).")
    else:
        print("Configuration not yet loaded.")
    print("=" * 79)
    print()


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
def main():
    """Parse CLI, validate configuration, and execute the recovery audit."""
    # Phase 0 — print banner before config load
    print_banner()

    try:
        # Phase 1 — strict configuration load + validation
        args, cfg = audit_config_validator.parse_args()
    except SystemExit:
        # argparse already handled normal exits (e.g. --help or --validate-config)
        return
    except Exception as e:
        print(f"[FATAL] Failed to parse or validate configuration: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(3)

    # Phase 2 — now print banner with region/schema details
    print_banner(cfg)

    # Defensive: ensure required audit fields are set
    audit_section = cfg.get("audit", {})
    region = audit_section.get("region")
    bucket = audit_section.get("bucket")
    if not region or not bucket:
        print("[FATAL] Missing 'audit.region' or 'audit.bucket' in configuration.", file=sys.stderr)
        sys.exit(3)

    # Phase 3 — main recovery audit run
    try:
        audit_core_logic.run_audit_from_cli(args, cfg)
    except KeyboardInterrupt:
        print("\n[ABORTED] User interrupted the audit.", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[FATAL] Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


# -----------------------------------------------------------------------------
# Safe Runner
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    main()

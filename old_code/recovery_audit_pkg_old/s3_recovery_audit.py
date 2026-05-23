# -*- coding: utf-8 -*-
"""
===============================================================================
 s3_recovery_audit.py — v2.0.0 (2025-11-02)
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

import sys
import traceback

from . import audit_config_validator
from . import audit_core_logic

__version__ = "2.0.0"

def print_banner(cfg: dict | None = None) -> None:
    print("=" * 79)
    print(f"S3 Recovery Audit Tool — v{__version__}")
    print("© 2025 Teotoniio Fontana — IaaC Tools / Recovery Audit Package")
    if cfg and "audit" in cfg:
        region = cfg["audit"].get("region", "?")
        bucket = cfg["audit"].get("bucket", "?")
        print(f"Configured Region: {region}   Bucket: {bucket}")
    else:
        print("Configuration not yet loaded.")
    print("=" * 79)
    print()

def main():
    print_banner()
    try:
        args, cfg = audit_config_validator.parse_args()
    except SystemExit:
        return
    except Exception as e:
        print(f"[FATAL] Failed to parse/validate configuration: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(3)

    print_banner(cfg)

    try:
        audit_core_logic.run_audit_from_cli(args, cfg)
    except KeyboardInterrupt:
        print("\n[ABORTED] User interrupted the audit.", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[FATAL] Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

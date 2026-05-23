#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ebs_backup_pkg/main.py — Orchestration entrypoint
=================================================

Drives the multi-phase EBS backup workflow:
  1. Discover
  2. Plan
  3. Prep
  4. Backup
  5. Manifest

Handles CLI parsing, logging, AWS session setup, and high-level exception control.

Now includes graceful UnauthorizedSSOTokenError handling:
prints a clear fatal message and exits cleanly (no traceback).
"""

import sys
import logging
import boto3
from botocore.exceptions import UnauthorizedSSOTokenError

from .cli import parse_args
from .utils import build_logger
from .phase_1_discover import run_discover
from .phase_2_plan import run_plan
from .phase_3_prep import run_prep
from .phase_4_backup import run_backup
from .phase_5_manifest import run_manifest


# ---------------------------------------------------------------------------
# Helper: validate SSO token freshness before AWS calls
# ---------------------------------------------------------------------------
def validate_sso_token(profile: str, logger=None):
    """Validate AWS SSO session for the given profile before orchestration."""
    if not profile:
        return
    try:
        boto3.Session(profile_name=profile).client("sts").get_caller_identity()
    except UnauthorizedSSOTokenError:
        msg = (
            f"[FATAL] AWS SSO token expired or invalid for profile '{profile}'.\n"
            f"        Run: aws sso login --profile {profile}"
        )
        if logger:
            logger.error(msg)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helper: validate each phase result
# ---------------------------------------------------------------------------
def _check_phase_result(name: str, result, logger):
    """Ensure the phase returned a dictionary; abort cleanly if not."""
    if not isinstance(result, dict):
        logger.error(f"[FATAL] Phase '{name}' returned invalid type: {type(result).__name__}")
        sys.exit(1)
    return result


# ---------------------------------------------------------------------------
# Main Orchestration
# ---------------------------------------------------------------------------
def main():
    try:
        # ---------------------------------------------------------------
        # Parse args and initialize logger
        # ---------------------------------------------------------------
        args = parse_args()
        logger = build_logger(
            "ebs-backup",
            args.log_file,
            args.log_json,
            args.log_json_array,
            getattr(logging, args.log_level.upper(), logging.INFO),
        )

        logger.info("Starting IaacTools EBS Backup Orchestrator")
        logger.info(
            "Profile: %s | Source region: %s | Destination: %s",
            args.profile,
            args.src_region,
            args.dst_region,
        )

        # ---------------------------------------------------------------
        # Validate AWS SSO token before any API call
        # ---------------------------------------------------------------
        validate_sso_token(args.profile, logger)

        # ---------------------------------------------------------------
        # Execute phases sequentially
        # ---------------------------------------------------------------
        discovered = _check_phase_result("discover", run_discover(args, logger), logger)
        planned = _check_phase_result("plan", run_plan(args, discovered, logger), logger)
        prepped = _check_phase_result("prep", run_prep(args, planned, logger), logger)
        backed = _check_phase_result("backup", run_backup(args, prepped, logger), logger)
        _check_phase_result("manifest", run_manifest(args, backed, logger), logger)

        logger.info("All phases completed successfully.")
        sys.exit(0)

    # -------------------------------------------------------------------
    # Handle expired / invalid SSO token
    # -------------------------------------------------------------------
    except UnauthorizedSSOTokenError:
        profile = getattr(args, "profile", "(unknown)")
        msg = (
            f"[FATAL] AWS SSO token expired or invalid for profile '{profile}'.\n"
            f"        Please run:\n"
            f"            aws sso login --profile {profile}\n"
        )
        print(msg, file=sys.stderr)
        sys.exit(1)

    # -------------------------------------------------------------------
    # Handle user interruption
    # -------------------------------------------------------------------
    except KeyboardInterrupt:
        print("\n[ABORTED] Operation cancelled by user.", file=sys.stderr)
        sys.exit(130)

    # -------------------------------------------------------------------
    # Handle unexpected exceptions gracefully
    # -------------------------------------------------------------------
    except Exception as exc:
        exc_type, _, exc_tb = sys.exc_info()
        lineno = exc_tb.tb_lineno if exc_tb else "(unknown)"
        filename = exc_tb.tb_frame.f_code.co_filename if exc_tb else "(unknown)"
        print(
            f"[FATAL] Unexpected error: {exc} "
            f"(line {lineno} in {filename})",
            file=sys.stderr,
        )
        sys.exit(2)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phase_3_prep.py — Phase 3: Prep
================================

Acquires helper locks and pre-clears the helper instance before
starting the backup phase.

Derived from the monolithic ebs_backup_pkg/main.py (PREP section),
refactored for modular orchestration and logging consistency.

FATAL error handling:
- Clean message with line number and file name.
- No traceback spam.
- Always exits with SystemExit(1).
"""

import sys
import boto3
from botocore.exceptions import ClientError
from .locks import acquire_helper_lock, release_helper_lock
from .fullvol import preclear_helper_instance
from .utils import log_step
from .logging_utils import log_phase_header, log_exception


def run_prep(args, plan_state, logger):
    """
    Phase 3 — Acquire locks and prepare helper instance.

    Args:
        args: argparse.Namespace with runtime options
        plan_state: dict with volumes, totals, and other plan info
        logger: active logger

    Returns:
        dict: extended plan state with S3 client, lock key, etc.
    """
    try:
        # -------------------------------------------------------------------
        # Phase header
        # -------------------------------------------------------------------
        log_phase_header(logger, 3, 5, "PREP", "phase_3_prep")
        log_step(logger, "PREP", "START")

        s3_client = None
        lock_key = None

        # -------------------------------------------------------------------
        # S3 client (for helper lock and artifacts)
        # -------------------------------------------------------------------
        if args.s3_bucket:
            try:
                s3_region = args.s3_region or args.dst_region
                s3_client = boto3.Session(
                    region_name=s3_region,
                    **({"profile_name": args.profile} if args.profile else {}),
                ).client("s3")
                logger.debug(
                    "Initialized S3 client for bucket %s in region %s",
                    args.s3_bucket,
                    s3_region,
                )
            except Exception as exc:
                log_exception(logger, "PREP:S3_INIT", exc)
                raise SystemExit("[FATAL] Unable to initialize S3 client.")

        # -------------------------------------------------------------------
        # Acquire helper lock if full-volume backup is enabled
        # -------------------------------------------------------------------
        if args.backup_type in ("full-volume", "both"):
            if not s3_client or not args.s3_bucket:
                raise SystemExit(
                    "[FATAL] Full-volume backup requires --s3-bucket to create the helper lock."
                )
            try:
                lock_key = acquire_helper_lock(
                    s3_client,
                    args.s3_bucket,
                    args.s3_prefix,
                    args.helper_instance_id,
                    plan_state.get("run_id", "none"),
                    args.profile,
                    logger,
                    simulate=args.simulate,
                )
                logger.info("Helper lock acquired: %s", lock_key or "(simulated)")
            except ClientError as exc:
                log_exception(logger, "PREP:LOCK", exc)
                raise SystemExit("[FATAL] Failed to acquire helper lock.")
            except Exception as exc:
                log_exception(logger, "PREP:LOCK", exc)
                raise SystemExit("[FATAL] Unexpected error acquiring helper lock.")

            # -------------------------------------------------------------------
            # Preclear helper instance
            # -------------------------------------------------------------------
            try:
                ec2_dst = boto3.Session(
                    region_name=args.dst_region,
                    **({"profile_name": args.profile} if args.profile else {}),
                ).client("ec2")
                preclear_helper_instance(
                    ec2_dst,
                    args.helper_instance_id,
                    logger,
                    simulate=args.simulate,
                )
                logger.info(
                    "Helper instance %s pre-cleared successfully.",
                    args.helper_instance_id,
                )
            except Exception as exc:
                log_exception(logger, "PREP:PRECLEAR", exc)
                raise SystemExit("[FATAL] Helper instance preclear failed.")

        else:
            logger.info(
                "Full-volume operations not requested — skipping lock acquisition."
            )

        log_step(logger, "PREP", "END")
        logger.info("Phase 3 complete: Preparation successful.")

        return {
            **plan_state,
            "s3_client": s3_client,
            "lock_key": lock_key,
        }

    # -----------------------------------------------------------------------
    # Canonical FATAL handler
    # -----------------------------------------------------------------------
    except Exception as e:
        exc_type, _, exc_tb = sys.exc_info()
        lineno = exc_tb.tb_lineno if exc_tb else "(unknown)"
        filename = exc_tb.tb_frame.f_code.co_filename if exc_tb else "(unknown)"
        logger.error(
            f"[FATAL] Unexpected error: {e} (line {lineno} in {filename})",
            exc_info=False,
        )
        raise SystemExit(1)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phase_5_manifest.py — Phase 5: Manifest & Upload
================================================

Generates and uploads the backup manifest, updates indexes,
uploads logs, and releases the helper lock.

Derived from the monolithic ebs_backup_pkg/main.py (MANIFEST section),
refactored for modular orchestration and logging consistency.

FATAL error handling:
- Clean message with line number and file name.
- No traceback spam.
"""

import json
import sys
import time
from pathlib import Path
from typing import Dict, List

from .utils import log_step, secs_since, utc_iso, confirm_phase
from .s3_utils import (
    upload_manifest_to_s3,
    upload_log_to_s3_if_present,
    append_volume_index_entry,
    write_latest_pointer,
)
from .locks import release_helper_lock
from .logging_utils import log_phase_header, log_exception


def run_manifest(args, backup_state, logger):
    """
    Phase 5 — Write manifest, upload artifacts, release locks.

    Args:
        args: argparse.Namespace with all configuration options.
        backup_state: dict returned from phase_4_backup.
        logger: active logger instance.

    Returns:
        dict: final run summary.
    """
    try:
        # -------------------------------------------------------------------
        # Phase header
        # -------------------------------------------------------------------
        log_phase_header(logger, 5, 5, "MANIFEST", "phase_5_manifest")

        run_id = backup_state.get("run_id")
        records: List = backup_state.get("records", [])
        s3_client = backup_state.get("s3_client")
        index_entries_by_volume = backup_state.get("index_entries_by_volume", {})
        lock_key = backup_state.get("lock_key")

        total = len(records)
        ok = sum(1 for r in records if not r.Error)
        ko = total - ok
        logger.info("Preparing manifest for %d backups (%d OK, %d failed).", total, ok, ko)

        # -------------------------------------------------------------------
        # Write MANIFEST file locally
        # -------------------------------------------------------------------
        confirm_phase(
            args,
            logger,
            question=f"Write manifest to {Path(args.manifest_file).resolve()}?",
            abort_reason="Cancelled by user at MANIFEST phase.",
        )

        t0 = time.time()
        log_step(logger, "MANIFEST", "START", Path=str(Path(args.manifest_file).resolve()))

        manifest_path = Path(args.manifest_file)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {}

        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}

        payload = existing or {"Backups": []}
        if "Backups" not in payload or not isinstance(payload["Backups"], list):
            payload["Backups"] = []

        payload.setdefault("RunId", run_id)
        payload["Simulated"] = bool(args.simulate)
        payload["GeneratedAtUTC"] = utc_iso()
        payload["Backups"].extend(r.__dict__ for r in records)

        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        elapsed = secs_since(t0)
        log_step(logger, "MANIFEST", "END", Path=str(manifest_path), ElapsedSec=elapsed)
        logger.info("Manifest written to %s (%.1fs)", manifest_path, elapsed)

        # -------------------------------------------------------------------
        # Upload artifacts to S3
        # -------------------------------------------------------------------
        if args.s3_bucket and s3_client:
            logger.info("Uploading manifest and logs to S3 bucket: %s", args.s3_bucket)
            try:
                s3_run_prefix = f"{args.s3_prefix.rstrip('/')}/runs/{run_id}"
                man_key = f"{s3_run_prefix}/manifest.json".lstrip("/")
                upload_manifest_to_s3(
                    s3_client,
                    args.s3_bucket,
                    man_key,
                    manifest_path,
                    args.s3_storage_class,
                    logger,
                    simulate=args.simulate,
                )

                if args.log_file:
                    log_key = f"{s3_run_prefix}/logs/backup-log.json".lstrip("/")
                    upload_log_to_s3_if_present(
                        s3_client,
                        args.s3_bucket,
                        log_key,
                        args.log_file,
                        args.s3_storage_class,
                        logger,
                        simulate=args.simulate,
                    )

                for vol_id, entries in index_entries_by_volume.items():
                    append_volume_index_entry(
                        s3_client,
                        args.s3_bucket,
                        args.s3_prefix,
                        vol_id,
                        entries[-1],
                        storage_class="STANDARD",
                        simulate=args.simulate,
                    )

                write_latest_pointer(
                    s3_client,
                    args.s3_bucket,
                    args.s3_prefix,
                    run_id,
                    storage_class="STANDARD",
                    simulate=args.simulate,
                )

            except Exception as exc:
                log_exception(logger, "MANIFEST:S3_UPLOAD", exc)
                logger.warning("[WARN] Upload to S3 failed. Manifest remains local.")
            else:
                logger.info("Manifest and logs uploaded to S3 successfully.")

        else:
            logger.info("No S3 bucket specified — skipping upload.")

        # -------------------------------------------------------------------
        # Final cleanup: release lock
        # -------------------------------------------------------------------
        if lock_key and s3_client and args.s3_bucket:
            try:
                release_helper_lock(
                    s3_client,
                    args.s3_bucket,
                    lock_key,
                    logger,
                    simulate=args.simulate,
                )
                logger.info("Helper lock released successfully.")
            except Exception as exc:
                log_exception(logger, "MANIFEST:LOCK_RELEASE", exc)
                logger.warning("[WARN] Failed to release helper lock.")

        # -------------------------------------------------------------------
        # Summary output
        # -------------------------------------------------------------------
        print(
            f"[RESULT] succeeded={ok} failed={ko} volumes={total} mode={'SIMULATE' if args.simulate else 'EXECUTE'}",
            file=sys.stderr,
        )
        logger.info("Backup process complete: %d succeeded, %d failed.", ok, ko)

        return {
            **backup_state,
            "manifest_path": str(manifest_path),
            "result": {"ok": ok, "failed": ko, "total": total},
        }

    # -----------------------------------------------------------------------
    # Canonical FATAL error handler
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phase_4_backup.py — Phase 4: Backup
===================================

Performs the actual EBS backup operation:
 - Creates snapshots for each discovered volume
 - Optionally copies snapshots cross-region
 - Optionally performs full-volume exports to S3 via helper instance
 - Records results and prepares for manifest generation

INFO-level policy (human readable):
 - One line per volume:
       vol-0b480b74c18cfd338 → tf-ws2-xvdg attached to tf-webserver-1 (i-0630cf3424a3f3b1a) at /dev/xvdg
       vol-0b480b74c18cfd339 → tf-ws2-xvdh (unattached)
 - All JSON, structured steps, and AWS responses are DEBUG-only.

FATAL error handling:
 - Clean message with line number and file name.
 - No traceback spam.
"""

import sys
import time
import json
import logging
from collections import defaultdict
from typing import Dict, List
from botocore.exceptions import ClientError, WaiterError, BotoCoreError

from .models import BackupRecord
from .snapshots import create_snapshot_for_volume, wait_snapshot_complete, copy_snapshot
from .fullvol import perform_full_volume_backup
from .s3_utils import write_snapshot_artifacts
from .utils import utc_iso, secs_since, flatten_tags, log_step
from .logging_utils import log_phase_header, log_exception


def run_backup(args, prep_state, logger):
    """
    Phase 4 — Perform EBS snapshot and full-volume backup operations.
    """
    try:
        # -------------------------------------------------------------------
        # Phase header
        # -------------------------------------------------------------------
        log_phase_header(logger, 4, 5, "BACKUP", "phase_4_backup")

        volumes: List[Dict] = prep_state.get("volumes", [])
        s3_client = prep_state.get("s3_client")
        lock_key = prep_state.get("lock_key")
        run_id = prep_state.get("run_id", utc_iso().replace(":", "").replace("-", ""))
        fullvol_bucket = getattr(args, "fullvol_s3_bucket", None) or args.s3_bucket
        s3_run_prefix = getattr(args, "s3_prefix", "runs").rstrip("/") + f"/runs/{run_id}"

        if not volumes:
            logger.warning("No volumes available for backup.")
            return {"records": [], **prep_state}

        t0 = time.time()
        records: List[BackupRecord] = []
        index_entries_by_volume: Dict[str, List[dict]] = defaultdict(list)

        log_step(
            logger,
            "BACKUP",
            "START",
            SrcRegion=args.src_region,
            DstRegion=args.dst_region,
            Count=len(volumes),
            BackupType=args.backup_type,
            EncryptDst=bool(args.encrypt_dst),
            KmsKeyId=args.kms_key_id or "(default-key)",
            RunId=run_id,
            Simulate=bool(args.simulate),
        )

        logger.info("Phase 4 started: %d volume(s) to back up.", len(volumes))

        # -------------------------------------------------------------------
        # Per-volume operations
        # -------------------------------------------------------------------
        for vol in volumes:
            vid = vol["VolumeId"]
            size = vol.get("Size", "?")
            az = vol.get("AvailabilityZone", "?")
            vtags = flatten_tags(vol.get("Tags"))
            vname = vtags.get("Name", "").strip() or vid
            attachments = vol.get("Attachments") or []

            # Simplified human-readable INFO line
            if attachments:
                att = attachments[0]
                inst_id = att.get("InstanceId", "(unknown)")
                inst_name = att.get("InstanceName", inst_id)
                dev = att.get("DeviceName", "(none)")
                logger.info(
                    "%s → %s attached to %s (%s) at %s",
                    vid, vname, inst_name, inst_id, dev
                )
            else:
                logger.info("%s → %s (unattached)", vid, vname)

            # Debug-only details
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("VOLUME_DETAIL: %s", json.dumps(vol, indent=2))

            rec = BackupRecord(
                VolumeId=vid,
                VolumeType=vol.get("VolumeType", "unknown"),
                SizeGiB=size,
                AvailabilityZone=az,
                SrcRegion=args.src_region,
                DstRegion=args.dst_region,
                StartTime=utc_iso(),
                Tags=vtags,
            )

            try:
                # -----------------------------------------------------------
                # SNAPSHOT creation
                # -----------------------------------------------------------
                if args.backup_type in ("snapshot", "both", "full-volume"):
                    snap_id = create_snapshot_for_volume(
                        src_client=prep_state.get("ec2_src"),
                        vol=vol,
                        tags=args.tag or {},
                        logger=logger,
                        snapshot_name=vname,
                        simulate=args.simulate,
                    )
                    rec.SrcSnapshotId = snap_id
                    wait_snapshot_complete(
                        ec2_client=prep_state.get("ec2_src"),
                        snapshot_id=snap_id,
                        logger=logger,
                        simulate=args.simulate,
                    )
                else:
                    snap_id = None

                # -----------------------------------------------------------
                # COPY snapshot (cross-region)
                # -----------------------------------------------------------
                dst_snapshot_id = None
                if args.dst_region and args.dst_region != args.src_region and snap_id:
                    dst_snapshot_id = copy_snapshot(
                        dst_client=prep_state.get("ec2_dst"),
                        src_region=args.src_region,
                        snapshot_id=snap_id,
                        tags=args.tag or {},
                        logger=logger,
                        snapshot_name=vname,
                        encrypt=args.encrypt_dst,
                        kms_key_id=args.kms_key_id,
                        simulate=args.simulate,
                    )
                    rec.DstSnapshotId = dst_snapshot_id
                    wait_snapshot_complete(
                        ec2_client=prep_state.get("ec2_dst"),
                        snapshot_id=dst_snapshot_id,
                        logger=logger,
                        simulate=args.simulate,
                    )
                else:
                    rec.DstSnapshotId = snap_id

                # -----------------------------------------------------------
                # FULL-VOLUME backup (optional)
                # -----------------------------------------------------------
                if args.backup_type in ("full-volume", "both"):
                    base_snap = rec.DstSnapshotId or dst_snapshot_id
                    if not base_snap:
                        raise RuntimeError("No snapshot available for full-volume export.")

                    try:
                        s3b, s3k = perform_full_volume_backup(
                            ec2_dst=prep_state.get("ec2_dst"),
                            ssm_dst=prep_state.get("ssm_dst"),
                            helper_instance_id=args.helper_instance_id,
                            dst_snapshot_id=base_snap,
                            base_name=vname or vid,
                            size_gib=size,
                            s3_bucket=fullvol_bucket,
                            s3_run_prefix=s3_run_prefix,
                            vol_id=vid,
                            fmt=args.fullvol_format,
                            delete_temp_volume=(not args.fullvol_keep_temp_volume),
                            logger=logger,
                            extra_tags={
                                "BackupTool": f"ebs_backup.py v{getattr(args, 'version', 'unknown')}",
                                "BackupTime": utc_iso(),
                            },
                            simulate=args.simulate,
                        )
                        rec.FullVolumeS3Bucket = s3b
                        rec.FullVolumeS3Key = s3k
                    except Exception as exc:
                        rec.Error = str(exc)
                        log_exception(logger, "BACKUP:FULLVOL", exc)

                rec.EndTime = utc_iso()
                records.append(rec)

                # Minimal per-volume summary
                status = "OK" if not rec.Error else "FAIL"
                logger.info(
                    "%s → snapshot %s [%s]",
                    vid,
                    rec.DstSnapshotId or rec.SrcSnapshotId or "(none)",
                    status,
                )

                # DEBUG-only structured logs
                if logger.isEnabledFor(logging.DEBUG) and s3_client and args.s3_bucket and rec.DstSnapshotId:
                    write_snapshot_artifacts(
                        s3_client,
                        args.s3_bucket,
                        args.s3_prefix,
                        s3_run_prefix,
                        run_id,
                        rec.DstSnapshotId,
                        rec.SrcSnapshotId,
                        vid,
                        args.dst_region,
                        args.encrypt_dst,
                        args.kms_key_id,
                    )
                    index_entries_by_volume[vid].append(
                        {
                            "RunId": run_id,
                            "DstSnapshotId": rec.DstSnapshotId,
                            "FullVolume": (
                                f"s3://{rec.FullVolumeS3Bucket}/{rec.FullVolumeS3Key.lstrip('/')}"
                                if rec.FullVolumeS3Bucket and rec.FullVolumeS3Key
                                else None
                            ),
                            "EndTime": rec.EndTime,
                            "Status": "ok" if not rec.Error else "error",
                        }
                    )

            except (ClientError, WaiterError, TimeoutError, RuntimeError, BotoCoreError) as exc:
                rec.Error = str(exc)
                log_exception(logger, "BACKUP", exc)
                log_step(
                    logger,
                    "BACKUP",
                    "ERROR",
                    VolumeId=vid,
                    SrcSnapshotId=rec.SrcSnapshotId,
                    DstSnapshotId=rec.DstSnapshotId,
                    Error=str(exc),
                )
                records.append(rec)
                logger.error("%s — ERROR: %s", vid, exc)
                continue

        # -------------------------------------------------------------------
        # Summary
        # -------------------------------------------------------------------
        ok = sum(1 for r in records if not getattr(r, "Error", None))
        ko = len(records) - ok
        elapsed = secs_since(t0)
        logger.info("Phase 4 complete: %d succeeded, %d failed (%.1fs)", ok, ko, elapsed)
        log_step(logger, "BACKUP", "END", Total=len(records), Succeeded=ok, Failed=ko, ElapsedSec=elapsed)

        return {
            **prep_state,
            "records": records,
            "index_entries_by_volume": index_entries_by_volume,
            "run_id": run_id,
            "lock_key": lock_key,
        }

    except Exception as e:
        exc_type, _, exc_tb = sys.exc_info()
        lineno = exc_tb.tb_lineno if exc_tb else "(unknown)"
        filename = exc_tb.tb_frame.f_code.co_filename if exc_tb else "(unknown)"
        logger.error(
            f"[FATAL] Unexpected error: {e} (line {lineno} in {filename})",
            exc_info=False,
        )
        sys.exit(1)

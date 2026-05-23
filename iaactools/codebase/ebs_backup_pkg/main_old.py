from __future__ import annotations
import json, logging, sys, time, os
from pathlib import Path
from typing import Dict, List
import boto3
from botocore.exceptions import ClientError, WaiterError

from . import SCRIPT_NAME, SCRIPT_VERSION, SCRIPT_OBJECTIVE
from .cli import parse_args
from .utils import utc_iso, run_id_iso, build_logger, log_step, flatten_tags
from .discovery import load_instance_name_map, describe_volumes, ssm_collect_lsblk, log_discovery_items
from .snapshots import create_snapshot_for_volume, wait_snapshot_complete, copy_snapshot
from .fullvol import preclear_helper_instance, perform_full_volume_backup
from .locks import acquire_helper_lock, release_helper_lock
from .s3_utils import (
    upload_manifest_to_s3, upload_log_to_s3_if_present,
    append_volume_index_entry, write_latest_pointer, write_snapshot_artifacts
)
from .models import BackupRecord


def intro_banner(mode: str):
    print(f"[START] {SCRIPT_NAME} — v{SCRIPT_VERSION}", file=sys.stderr)
    print(f"        Objective: {SCRIPT_OBJECTIVE}", file=sys.stderr)
    print(f"        Started (UTC): {utc_iso()}", file=sys.stderr)
    print(f"        Mode: {mode}", file=sys.stderr)


def prompt_yes_no(logger, question: str, assume_yes: bool, non_interactive_abort_msg: str) -> bool:
    if assume_yes:
        log_step(logger, "PROMPT", "AUTO-CONTINUE", Reason="--yes supplied", Question=question)
        return True
    if not sys.stdin.isatty():
        log_step(logger, "PROMPT", "ABORT", Reason="Non-interactive stdin; supply --yes", Question=question)
        if non_interactive_abort_msg:
            print(non_interactive_abort_msg)
        return False
    try:
        ans = input(f"{question} [y/N]: ").strip().lower()
    except EOFError:
        ans = ""
    if ans in ("y", "yes"):
        log_step(logger, "PROMPT", "CONFIRMED", Answer=ans, Question=question)
        return True
    log_step(logger, "PROMPT", "CANCELLED", Answer=ans or "(empty)", Question=question)
    return False


def confirm_phase(args, logger, question: str, abort_reason: str):
    if not args.verbose or args.preview:  # never prompt in preview
        return
    ok = prompt_yes_no(
        logger,
        question,
        assume_yes=args.yes,
        non_interactive_abort_msg="Refusing to continue without --yes in non-interactive mode.",
    )
    if not ok:
        raise SystemExit(abort_reason)


def intro_and_confirm(args, session_src, logger, run_id: str):
    account = None
    try:
        sts = session_src.client("sts")
        ident = sts.get_caller_identity()
        account = ident.get("Account")
    except Exception:
        account = None
    cfg = {
        "ScriptName": SCRIPT_NAME,
        "Version": SCRIPT_VERSION,
        "Objective": SCRIPT_OBJECTIVE,
        "RunId": run_id,
        "SrcRegion": args.src_region,
        "DstRegion": args.dst_region,
        "Profile": args.profile or "(default)",
        "Account": account or "(unknown)",
        "States": args.states,
        "FilterTags": args.filter_tag or [],
        "SnapshotTags": args.tag or [],
        "BackupType": args.backup_type,
        "EncryptDst": bool(args.encrypt_dst),
        "KmsKeyId": args.kms_key_id or "(default-key)",
        "DeleteSrcAfterCopy": bool(args.delete_src_after_copy),
        "ManifestPath": args.manifest_file,
        "LogFile": args.log_file or "(stdout only)",
        "JSONLogs": bool(args.log_json),
        "JSONArray": bool(args.log_json_array),
        "Verbose": bool(args.verbose),
        "SSMInspect": bool(args.ssm_inspect),
        "S3Bucket": args.s3_bucket or "(none)",
        "S3Prefix": args.s3_prefix or "(n/a)",
        "S3StorageClass": args.s3_storage_class if args.s3_bucket else "(n/a)",
        "FullVolBucket": args.fullvol_s3_bucket or args.s3_bucket or "(none)",
        "FullVolPrefix": "(run-scoped)/fullvol/",
        "FullVolFormat": args.fullvol_format,
        "HelperInstance": args.helper_instance_id or "(none)",
        "KeepTempVolume": bool(args.fullvol_keep_temp_volume),
        "Preview": bool(args.preview),
        "Simulate": bool(args.simulate),
    }
    log_step(logger, "INTRO", "IDENTIFY", **cfg)
    if args.verbose and not args.preview:
        log_step(
            logger,
            "INTRO",
            "DETAILS",
            Notes=(
                "Operation creates EBS snapshots and/or full-volume images via a helper instance. "
                "Requires EC2, S3, SSM, and (optional) KMS permissions."
            ),
        )

    if not args.ssm_inspect and not args.preview:
        log_step(
            logger,
            "ALERT",
            "SSM_NOT_USED",
            Message="--ssm-inspect not supplied; OS mount points will NOT be collected.",
        )
        if args.verbose and not args.simulate:
            ok = prompt_yes_no(
                logger,
                "Proceed WITHOUT SSM mount inspection (mount points will not be logged)?",
                assume_yes=args.yes,
                non_interactive_abort_msg="Refusing to continue without --yes in non-interactive mode (SSM not used).",
            )
            if not ok:
                raise SystemExit("Cancelled by user (SSM not used).")

    if args.backup_type in ("full-volume", "both") and not args.preview:
        if not (args.fullvol_s3_bucket or args.s3_bucket):
            raise SystemExit("Full-volume backup requires an S3 bucket (--fullvol-s3-bucket or --s3-bucket).")
        if not args.helper_instance_id:
            raise SystemExit("Full-volume backup requires --helper-instance-id (in destination region).")

    if args.preview:
        return

    if args.yes or args.simulate:
        log_step(logger, "PROMPT", "AUTO-CONTINUE", Reason="--yes or --simulate supplied")
        return
    if not sys.stdin.isatty():
        log_step(
            logger,
            "PROMPT",
            "ABORT",
            Reason="Non-interactive stdin; supply --yes to skip confirmation",
        )
        raise SystemExit("Refusing to prompt without TTY. Re-run with --yes.")
    if not prompt_yes_no(
        logger, f"{SCRIPT_NAME} v{SCRIPT_VERSION} — proceed?", assume_yes=False, non_interactive_abort_msg=""
    ):
        raise SystemExit("Cancelled by user.")


def main():
    args = parse_args()
    mode = "PREVIEW" if args.preview else "SIMULATE" if args.simulate else "EXECUTE"
    intro_banner(mode)

    # Logger
    logger = build_logger(
        "ebs-backup",
        args.log_file,
        args.log_json,
        args.log_json_array,
        getattr(logging, args.log_level.upper(), logging.INFO),
    )

    # Config debug
    if getattr(args, "_config_path", None):
        log_step(
            logger,
            "CONFIG",
            "LOADED",
            Path=str(Path(args._config_path).resolve()),
            Keys = sorted([str(k) for k in (args._config.keys() if isinstance(args._config, dict) else [])])

        )

    # Sessions / clients
    session_kwargs = {}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    src_sess = boto3.Session(region_name=args.src_region, **session_kwargs)
    dst_sess = boto3.Session(region_name=args.dst_region, **session_kwargs)
    ec2_src = src_sess.client("ec2")
    ec2_dst = dst_sess.client("ec2")
    ssm_dst = dst_sess.client("ssm")

    s3_client = None
    if args.s3_bucket:
        s3_region = args.s3_region or args.dst_region
        s3_client = boto3.Session(
            region_name=s3_region, **({"profile_name": args.profile} if args.profile else {})
        ).client("s3")

    run_id = run_id_iso()
    s3_run_prefix = None
    if args.s3_bucket:
        norm_prefix = args.s3_prefix.strip("/")
        if norm_prefix.endswith("/manifests"):
            print(
                f"[WARN] s3_prefix '{args.s3_prefix}' ends with '/manifests/'. Normalizing to '{norm_prefix.rsplit('/manifests',1)[0]}/'",
                file=sys.stderr,
            )
            args.s3_prefix = norm_prefix.rsplit("/manifests", 1)[0] + "/"
        s3_run_prefix = f"{args.s3_prefix.rstrip('/')}/runs/{run_id}"

    intro_and_confirm(args, src_sess, logger, run_id)

    # ===== DISCOVER =====
    confirm_phase(
        args,
        logger,
        question=f"Proceed to DISCOVER volumes in {args.src_region} (states: {args.states})?",
        abort_reason="Cancelled by user at DISCOVER phase.",
    )

    include_states = [s.strip() for s in args.states.split(",") if s.strip()]
    vol_tag_filters: Dict[str, str] = {}
    for kv in args.filter_tag:
        if "=" not in kv:
            raise SystemExit(f"--filter-tag expects key=value, got: {kv}")
        k, v = kv.split("=", 1)
        vol_tag_filters[k] = v

    snap_tags: Dict[str, str] = {}
    for kv in args.tag:
        if "=" not in kv:
            raise SystemExit(f"--tag expects key=value, got: {kv}")
        k, v = kv.split("=", 1)
        snap_tags[k] = v
    from . import SCRIPT_VERSION as _VER

    snap_tags.setdefault("BackupOrigin", args.src_region)
    snap_tags.setdefault("BackupTime", utc_iso())
    snap_tags.setdefault("BackupTool", f"ebs_backup.py v{_VER}")

    inst_name_map = load_instance_name_map(ec2_src)
    t0 = time.time()
    log_step(logger, "DISCOVER", "START", States=list(include_states))
    volumes = describe_volumes(ec2_src, include_states)
    from .utils import secs_since

    log_step(logger, "DISCOVER", "FOUND", Count=len(volumes), ElapsedSec=secs_since(t0))

    if vol_tag_filters:
        def _match(vol: dict) -> bool:
            tags = flatten_tags(vol.get("Tags"))
            return all(tags.get(k) == v for k, v in vol_tag_filters.items())

        pre_len = len(volumes)
        volumes = [v for v in volumes if _match(v)]
        log_step(logger, "DISCOVER", "FILTER", FilterTags=vol_tag_filters, Before=pre_len, After=len(volumes))

    # Canonical discovery line for orchestrator parsing (always print, even if 0)
    attached = sum(1 for v in volumes if str(v.get("State")) == "in-use")
    available = sum(1 for v in volumes if str(v.get("State")) == "available")
    print(f"[DISCOVERY] volumes={len(volumes)} attached={attached} available={available}")

    if not volumes:
        log_step(logger, "DISCOVER", "EMPTY", Message="No volumes matched filters/states")
        print("No volumes to back up.", file=sys.stderr)
        return

    # [CHANGED] — INFO compacto; detalhado só no DEBUG
    if logger.isEnabledFor(logging.DEBUG):
        log_discovery_items(
            logger, volumes, inst_name_map, None  # SSM map será adicionado mais abaixo se aplicável
        )
    else:
        log_step(
            logger,
            "DISCOVER",
            "SUMMARY",
            Count=len(volumes),
            Attached=attached,
            Available=available,
        )

    log_step(logger, "DISCOVER", "END", Count=len(volumes))

    # ===== SSM INSPECT (opcional) =====
    ssm_map: Dict[str, dict] = {}
    if args.ssm_inspect and not args.preview:
        attached_instance_ids = sorted(
            {
                att.get("InstanceId")
                for v in volumes
                for att in v.get("Attachments", []) or []
                if att.get("InstanceId")
            }
        )
        if attached_instance_ids:
            confirm_phase(
                args,
                logger,
                question=f"Run SSM mount inspection on {len(attached_instance_ids)} attached instances?",
                abort_reason="Cancelled by user at SSM INSPECT phase.",
            )
            ssm_map, _ = ssm_collect_lsblk(src_sess.client("ssm"), attached_instance_ids, logger)
            # [CHANGED] — Detalhes de SSM só no DEBUG
            if logger.isEnabledFor(logging.DEBUG):
                log_discovery_items(logger, volumes, inst_name_map, ssm_map)
            else:
                log_step(
                    logger,
                    "SSM",
                    "SUMMARY",
                    Instances=len(attached_instance_ids),
                    WithData=len(ssm_map),
                )
        else:
            log_step(
                logger,
                "ALERT",
                "SSM_SKIPPED",
                Message="No attached instances found; --ssm-inspect has nothing to inspect.",
            )

    # ===== PLAN =====
    total_gib = sum(int(v.get("Size", 0)) for v in volumes)
    total_tib = round(total_gib / 1024.0, 3)
    log_step(
        logger,
        "PLAN",
        "SIZE",
        TotalVolumes=len(volumes),
        TotalSizeGiB=total_gib,
        TotalSizeTiB=total_tib,
        Note="EBS snapshot storage is incremental; shown value is raw attached capacity.",
    )

    if args.preview:
        print(
            f"[PREVIEW] Would back up {len(volumes)} volume(s) totaling ~{total_gib} GiB ({total_tib:.3f} TiB). No actions performed.",
            file=sys.stderr,
        )
        return

    confirm_phase(
        args,
        logger,
        question=f"Backup plan: {len(volumes)} volumes totaling ~{total_gib} GiB ({total_tib:.3f} TiB). Proceed?",
        abort_reason="Cancelled by user at BACKUP (size confirmation) phase.",
    )

    # ===== PREP (locks & pre-clear) =====
    lock_key = None
    try:
        if args.backup_type in ("full-volume", "both"):
            if not s3_client or not args.s3_bucket:
                raise SystemExit("Full-volume runs require --s3-bucket to create the helper lock (safety).")
            lock_key = acquire_helper_lock(
                s3_client,
                args.s3_bucket,
                args.s3_prefix,
                args.helper_instance_id,
                run_id,
                args.profile,
                logger,
                simulate=args.simulate,
            )
            preclear_helper_instance(ec2_dst, args.helper_instance_id, logger, simulate=args.simulate)

        # ===== BACKUP =====
        manifest_path = Path(args.manifest_file)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        records: List[BackupRecord] = []
        from collections import defaultdict

        index_entries_by_volume: Dict[str, List[dict]] = defaultdict(list)
        overall_t0 = time.time()
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

        fullvol_bucket = args.fullvol_s3_bucket or args.s3_bucket

        for vol in volumes:
            vid = vol["VolumeId"]
            size = vol["Size"]
            vtype = vol.get("VolumeType", "unknown")
            az = vol["AvailabilityZone"]
            vtags = flatten_tags(vol.get("Tags"))
            vname = vtags.get("Name", "").strip()
            snapshot_name = vname if vname else vid
            from .utils import utc_iso as _utc

            rec = BackupRecord(
                VolumeId=vid,
                VolumeType=vtype,
                SizeGiB=size,
                AvailabilityZone=az,
                SrcRegion=args.src_region,
                DstRegion=args.dst_region,
                StartTime=_utc(),
                Tags=vtags,
            )

            try:
                # SNAPSHOT path (or minimal for full-volume)
                if args.backup_type in ("snapshot", "both"):
                    snap_id = create_snapshot_for_volume(
                        ec2_src, vol, snap_tags, logger, snapshot_name, simulate=args.simulate
                    )
                    rec.SrcSnapshotId = snap_id
                    wait_snapshot_complete(ec2_src, snap_id, logger, simulate=args.simulate)

                    dst_snapshot_id = copy_snapshot(
                        ec2_dst,
                        args.src_region,
                        snap_id,
                        snap_tags,
                        logger,
                        snapshot_name=snapshot_name,
                        encrypt=args.encrypt_dst,
                        kms_key_id=args.kms_key_id,
                        simulate=args.simulate,
                    )
                    rec.DstSnapshotId = dst_snapshot_id
                    wait_snapshot_complete(ec2_dst, dst_snapshot_id, logger, simulate=args.simulate)

                    if args.s3_bucket and s3_client and s3_run_prefix:
                        if not args.simulate:
                            write_snapshot_artifacts(
                                s3_client,
                                args.s3_bucket,
                                args.s3_prefix,
                                s3_run_prefix,
                                run_id,
                                dst_snapshot_id,
                                rec.SrcSnapshotId,
                                vid,
                                args.dst_region,
                                args.encrypt_dst,
                                args.kms_key_id,
                            )
                        else:
                            print(
                                f"[SIMULATE] Would write snapshot artifact/index entries for {dst_snapshot_id}",
                                file=sys.stderr,
                            )

                else:
                    # full-volume only: still need a base snapshot (simulate or real)
                    snap_id = create_snapshot_for_volume(
                        ec2_src, vol, snap_tags, logger, snapshot_name, simulate=args.simulate
                    )
                    rec.SrcSnapshotId = snap_id
                    wait_snapshot_complete(ec2_src, snap_id, logger, simulate=args.simulate)
                    dst_snapshot_id = snap_id
                    if args.dst_region != args.src_region:
                        dst_snapshot_id = copy_snapshot(
                            ec2_dst,
                            args.src_region,
                            snap_id,
                            snap_tags,
                            logger,
                            snapshot_name=snapshot_name,
                            encrypt=args.encrypt_dst,
                            kms_key_id=args.kms_key_id,
                            simulate=args.simulate,
                        )
                        wait_snapshot_complete(ec2_dst, dst_snapshot_id, logger, simulate=args.simulate)
                    if args.s3_bucket and s3_client and s3_run_prefix:
                        if not args.simulate:
                            write_snapshot_artifacts(
                                s3_client,
                                args.s3_bucket,
                                args.s3_prefix,
                                s3_run_prefix,
                                run_id,
                                dst_snapshot_id,
                                rec.SrcSnapshotId,
                                vid,
                                args.dst_region,
                                args.encrypt_dst,
                                args.kms_key_id,
                            )
                        else:
                            print(
                                f"[SIMULATE] Would write snapshot artifact/index entries for {dst_snapshot_id}",
                                file=sys.stderr,
                            )
                    rec.DstSnapshotId = dst_snapshot_id if args.dst_region == args.src_region else (dst_snapshot_id or None)

                # FULL-VOLUME path
                if args.backup_type in ("full-volume", "both"):
                    base_snap = rec.DstSnapshotId or dst_snapshot_id
                    if not base_snap:
                        raise RuntimeError("No snapshot available to produce a full-volume image.")
                    s3b, s3k = perform_full_volume_backup(
                        ec2_dst=ec2_dst,
                        ssm_dst=ssm_dst,
                        helper_instance_id=args.helper_instance_id,
                        dst_snapshot_id=base_snap,
                        base_name=(vname or vid),
                        size_gib=size,
                        s3_bucket=(fullvol_bucket),
                        s3_run_prefix=(s3_run_prefix or args.s3_prefix),
                        vol_id=vid,
                        fmt=args.fullvol_format,
                        delete_temp_volume=(not args.fullvol_keep_temp_volume),
                        logger=logger,
                        extra_tags={"BackupTool": f"ebs_backup.py v{SCRIPT_VERSION}", "BackupTime": utc_iso()},
                        simulate=args.simulate,
                    )
                    rec.FullVolumeS3Bucket = s3b
                    rec.FullVolumeS3Key = s3k

            except (ClientError, WaiterError, TimeoutError, RuntimeError, SystemExit) as e:
                rec.Error = str(e)
                log_step(
                    logger,
                    "BACKUP",
                    "ERROR",
                    VolumeId=vid,
                    SrcSnapshotId=rec.SrcSnapshotId,
                    DstSnapshotId=rec.DstSnapshotId,
                    Error=str(e),
                    SnapshotName=snapshot_name,
                )
                if isinstance(e, SystemExit):
                    from .utils import utc_iso as _utc

                    rec.EndTime = _utc()
                    records.append(rec)
                    raise

            from .utils import utc_iso as _utc

            rec.EndTime = _utc()
            records.append(rec)
            from .utils import secs_since

            # [CHANGED] — resumo por volume só no DEBUG (INFO fica limpo)
            if logger.isEnabledFor(logging.DEBUG):
                log_step(
                    logger,
                    "BACKUP",
                    "SUMMARY",
                    VolumeId=vid,
                    SizeGiB=size,
                    VolumeType=vtype,
                    SrcSnapshotId=rec.SrcSnapshotId,
                    DstSnapshotId=rec.DstSnapshotId,
                    FullVolumeS3Bucket=rec.FullVolumeS3Bucket,
                    FullVolumeS3Key=rec.FullVolumeS3Key,
                    Error=rec.Error,
                    TotalSoFar=len(records),
                    ElapsedSec=secs_since(overall_t0),
                )

            status = "ok" if (not rec.Error) else "error"
            fullvol_uri = None
            if rec.FullVolumeS3Bucket and rec.FullVolumeS3Key:
                fullvol_uri = f"s3://{rec.FullVolumeS3Bucket}/{rec.FullVolumeS3Key.lstrip('/')}"
            index_entries_by_volume[vid].append(
                {
                    "RunId": run_id,
                    "DstSnapshotId": rec.DstSnapshotId,
                    "FullVolume": fullvol_uri,
                    "EndTime": rec.EndTime,
                    "Status": status,
                }
            )

        log_step(
            logger,
            "BACKUP",
            "END",
            Total=len(records),
            Succeeded=sum(1 for r in records if not r.Error),
            Failed=sum(1 for r in records if r.Error),
        )

        # ===== MANIFEST =====
        confirm_phase(
            args,
            logger,
            question=f"Write MANIFEST to {Path(args.manifest_file).resolve()}?",
            abort_reason="Cancelled by user at MANIFEST phase.",
        )
        t1 = time.time()
        manifest_path = Path(args.manifest_file)
        log_step(logger, "MANIFEST", "START", Path=str(manifest_path))
        existing = {}
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}
        # Robust payload initialization
        payload = existing or {"Backups": []}
        if "Backups" not in payload or not isinstance(payload["Backups"], list):
            payload["Backups"] = []
        payload.setdefault("RunId", run_id)
        payload["Simulated"] = bool(args.simulate)
        payload["Backups"].extend(r.__dict__ for r in records)
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        from .utils import secs_since as _secs

        log_step(logger, "MANIFEST", "END", Path=str(manifest_path))

        # ===== S3 uploads =====
        if args.s3_bucket and s3_client:
            man_key = f"{(s3_run_prefix or args.s3_prefix).rstrip('/')}/manifest.json".lstrip("/")
            upload_manifest_to_s3(
                s3_client, args.s3_bucket, man_key, manifest_path, args.s3_storage_class, logger, simulate=args.simulate
            )

            if args.log_file:
                log_key = f"{(s3_run_prefix or args.s3_prefix).rstrip('/')}/logs/backup-log.json".lstrip("/")
                upload_log_to_s3_if_present(
                    s3_client, args.s3_bucket, log_key, args.log_file, args.s3_storage_class, logger, simulate=args.simulate
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
                s3_client, args.s3_bucket, args.s3_prefix, run_id, storage_class="STANDARD", simulate=args.simulate
            )

        ok = sum(1 for r in records if not r.Error)
        ko = len(records) - ok
        print(f"Done. {ok} succeeded, {ko} failed. Manifest: {manifest_path}", file=sys.stderr)
        # Canonical end-of-run line for orchestrator parsing
        mode_txt = "SIMULATE" if args.simulate else ("PREVIEW" if args.preview else "EXECUTE")
        print(f"[RESULT] succeeded={ok} failed={ko} volumes={len(records)} mode={mode_txt}")

    finally:
        if lock_key and s3_client and args.s3_bucket:
            release_helper_lock(s3_client, args.s3_bucket, lock_key, logger, simulate=args.simulate)

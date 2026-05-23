from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError
from .utils import log_step

def s3_put_json(s3_client, bucket: str, key: str, obj: dict, storage_class: Optional[str] = None, if_none_match: Optional[str] = None, simulate: bool=False):
    if simulate:
        print(f"[SIMULATE] Would PUT manifest/index to s3://{bucket}/{key}", file=sys.stderr)
        return
    body = json.dumps(obj, indent=2).encode("utf-8")
    extra: Dict[str, Any] = {}
    if storage_class:
        extra["StorageClass"] = storage_class
    if if_none_match is not None:
        extra["IfNoneMatch"] = if_none_match
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, **extra)

def s3_get_json(s3_client, bucket: str, key: str) -> Optional[dict]:
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()
        return json.loads(data.decode("utf-8"))
    except s3_client.exceptions.NoSuchKey:
        return None
    except ClientError as e:
        if e.response.get("Error",{}).get("Code") in ("NoSuchKey","404","NotFound"):
            return None
        raise

def upload_manifest_to_s3(s3_client, bucket: str, key: str, local_path: Path, storage_class: str, logger, simulate: bool=False):
    if simulate:
        log_step(logger, "MANIFEST", "SIMULATE_S3_UPLOAD", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=local_path.stat().st_size)
        print(f"[SIMULATE] Would upload manifest {local_path} to s3://{bucket}/{key}", file=sys.stderr)
        return
    log_step(logger, "MANIFEST", "S3_UPLOAD_START", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=local_path.stat().st_size)
    s3_client.upload_file(Filename=str(local_path), Bucket=bucket, Key=key, ExtraArgs={"StorageClass": storage_class})
    log_step(logger, "MANIFEST", "S3_UPLOAD_END", Bucket=bucket, Key=key, StorageClass=storage_class)

def upload_log_to_s3_if_present(s3_client, bucket: str, key: str, log_file: Optional[str], storage_class: str, logger, simulate: bool=False):
    if not log_file: return
    p = Path(log_file)
    if not p.exists(): return
    if simulate:
        log_step(logger, "LOGS", "SIMULATE_S3_UPLOAD", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=p.stat().st_size)
        print(f"[SIMULATE] Would upload log {p} to s3://{bucket}/{key}", file=sys.stderr)
        return
    log_step(logger, "LOGS", "S3_UPLOAD_START", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=p.stat().st_size)
    s3_client.upload_file(Filename=str(p), Bucket=bucket, Key=key, ExtraArgs={"StorageClass": storage_class})
    log_step(logger, "LOGS", "S3_UPLOAD_END", Bucket=bucket, Key=key, StorageClass=storage_class)

def index_latest_key(prefix: str) -> str:
    return f"{prefix.rstrip('/')}/index/latest.json"

def index_by_volume_key(prefix: str, vol_id: str) -> str:
    return f"{prefix.rstrip('/')}/index/by-volume/{vol_id}.json"

def index_by_snapshot_key(prefix: str, snapshot_id: str) -> str:
    return f"{prefix.rstrip('/')}/index/by-snapshot/{snapshot_id}.json"

def append_volume_index_entry(s3_client, bucket: str, prefix: str, vol_id: str, entry: dict, storage_class: Optional[str] = None, simulate: bool=False):
    current = s3_get_json(s3_client, bucket, index_by_volume_key(prefix, vol_id)) or {"VolumeId": vol_id, "Entries": []}
    current["Entries"] = [entry] + (current.get("Entries") or [])   # prepend newest
    s3_put_json(s3_client, bucket, index_by_volume_key(prefix, vol_id), current, storage_class=storage_class, simulate=simulate)

def write_latest_pointer(s3_client, bucket: str, prefix: str, run_id: str, storage_class: Optional[str] = None, simulate: bool=False):
    s3_put_json(s3_client, bucket, index_latest_key(prefix), {"run_id": run_id}, storage_class=storage_class, simulate=simulate)

# ---- Compatibility shim for older call sites ----
from pathlib import Path

def write_snapshot_artifacts(*args, **kwargs) -> str:
    """
    Backwards-compatible artifact writer.

    Accepts any of the following shapes (best-effort parsing):
      - write_snapshot_artifacts(manifest_path, records, s3_bucket=None, s3_prefix=None, s3_client=None, **extra)
      - write_snapshot_artifacts(out_dir, run_id, records, s3_bucket=None, s3_prefix=None, **extra)
      - write_snapshot_artifacts(records=<list>, manifest_path=<path>, s3_bucket=..., s3_prefix=..., s3_client=...)

    Writes a tiny JSON manifest locally; if bucket provided, uploads under {prefix}/manifests/.
    """
    import json
    from datetime import datetime, timezone

    def _utc_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _ensure_dir(p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True); return p

    manifest_path = kwargs.get("manifest_path")
    out_dir = kwargs.get("out_dir")
    if not manifest_path and out_dir:
        manifest_path = Path(out_dir) / "ebs_backup_manifest.json"
    if not manifest_path and args:
        a0 = args[0]
        if isinstance(a0, (str, Path)) and str(a0).lower().endswith(".json"):
            manifest_path = Path(a0)
    if not manifest_path:
        manifest_path = Path("results") / "ebs_backup_manifest.json"
    manifest_path = Path(manifest_path)

    records = (
        kwargs.get("records")
        or kwargs.get("snapshots")
        or (args[1] if len(args) >= 2 and isinstance(args[1], list) else None)
        or []
    )

    data = {"meta": {"generated_utc": _utc_iso(), "count": len(records)}, "items": records}
    _ensure_dir(manifest_path.parent)
    try:
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[ARTIFACTS] Manifest written: {manifest_path}")
    except Exception as e:
        print(f"[WARN] Could not write manifest to {manifest_path}: {e}", file=sys.stderr)
        return str(manifest_path)

    # FIX: bucket is args[1], prefix is args[2] in your call sites
    s3_bucket = kwargs.get("s3_bucket") or (args[1] if len(args) >= 2 and isinstance(args[1], str) else None)
    s3_prefix = (kwargs.get("s3_prefix") or (args[2] if len(args) >= 3 and isinstance(args[2], str) else "tf-backup/")).rstrip("/")
    if s3_bucket:
        key = f"{s3_prefix}/manifests/{manifest_path.name}".lstrip("/")
        try:
            s3 = kwargs.get("s3_client") or boto3.client("s3")
            s3.upload_file(str(manifest_path), s3_bucket, key)
            print(f"[ARTIFACTS] Manifest uploaded to s3://{s3_bucket}/{key}")
        except Exception as e:
            print(f"[WARN] Could not upload manifest to s3://{s3_bucket}/{key}: {e}", file=sys.stderr)
    return str(manifest_path)

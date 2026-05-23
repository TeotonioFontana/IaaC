from __future__ import annotations
import sys
from .utils import utc_iso, log_step
from .s3_utils import s3_put_json
from botocore.exceptions import ClientError

def acquire_helper_lock(s3_client, bucket: str, s3_prefix: str, helper_instance_id: str, run_id: str, profile: str, logger, simulate: bool) -> str:
    lock_key = f"{s3_prefix.rstrip('/')}/locks/helper-{helper_instance_id}.lock"
    payload = {"run_id": run_id, "helper_instance_id": helper_instance_id, "owner_profile": profile or "(default)", "acquired_utc": utc_iso()}
    if simulate:
        log_step(logger, "LOCK", "SIMULATE_ACQUIRE", Key=lock_key, Helper=helper_instance_id)
        print(f"[SIMULATE] Would acquire helper lock s3://{bucket}/{lock_key}", file=sys.stderr)
        return lock_key
    try:
        s3_put_json(s3_client, bucket, lock_key, payload, storage_class="STANDARD", if_none_match="*")
        log_step(logger, "LOCK", "ACQUIRED", Key=lock_key, Helper=helper_instance_id)
        print(f"[LOCK] Acquired {lock_key}", file=sys.stderr)
        return lock_key
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code == "PreconditionFailed" or status == 412:
            log_step(logger, "LOCK", "EXISTS", Key=lock_key, Helper=helper_instance_id)
            raise SystemExit(f"Helper lock already exists: s3://{bucket}/{lock_key} — another run may be in progress.")
        raise

def release_helper_lock(s3_client, bucket: str, lock_key: str, logger, simulate: bool):
    if simulate:
        log_step(logger, "LOCK", "SIMULATE_RELEASE", Key=lock_key)
        print(f"[SIMULATE] Would release helper lock s3://{bucket}/{lock_key}", file=sys.stderr)
        return
    try:
        s3_client.delete_object(Bucket=bucket, Key=lock_key)
        log_step(logger, "LOCK", "RELEASED", Key=lock_key)
        print(f"[LOCK] Released {lock_key}", file=sys.stderr)
    except Exception as e:
        log_step(logger, "LOCK", "RELEASE_ERROR", Key=lock_key, Error=str(e))
        print(f"[LOCK][WARN] Could not release {lock_key}: {e}", file=sys.stderr)

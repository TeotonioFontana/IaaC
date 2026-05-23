# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError, BotoCoreError  # type: ignore
except Exception:
    boto3 = None  # type: ignore

def verify_head_objects(uris: List[str], profile: Optional[str]) -> Tuple[List[str], List[str]]:
    """HEAD each s3://bucket/key; returns (ok_uris, error_msgs)."""
    if not uris: return [], []
    if boto3 is None:  # soft fail
        return [], [f"boto3 not available; cannot verify {len(uris)} objects"]

    session = boto3.Session(**({"profile_name": profile} if profile else {}))
    # simple client; most buckets resolve fine with us-east-1 head
    s3 = session.client("s3", region_name="us-east-1")

    ok, errs = [], []
    for u in uris:
        try:
            if not u.startswith("s3://"): raise ValueError("invalid S3 URI")
            bucket_key = u[5:].split("/", 1)
            bucket = bucket_key[0]; key = bucket_key[1]
            s3.head_object(Bucket=bucket, Key=key)
            ok.append(u)
        except Exception as e:
            errs.append(f"{u} — {e.__class__.__name__}: {e}")
    return ok, errs

def verify_idc_tree_local_vs_s3(out_dir: str, bucket: str, prefix: Optional[str],
                                s3_region: Optional[str], profile: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
    """Verify IDC identity-store/ tree exists on S3 (users.json, groups.json, etc.)."""
    from pathlib import Path
    if boto3 is None:
        return False, {"Error": "boto3 not installed; cannot verify S3 mirror"}
    sess_kwargs: Dict[str, Any] = {}
    if profile: sess_kwargs["profile_name"] = profile
    session = boto3.Session(region_name=s3_region, **sess_kwargs)
    s3 = session.client("s3")

    base = Path(out_dir)
    files = []
    for name in ("users.json","groups.json","group-memberships.json"):
        p = base / name
        if p.exists(): files.append(p)
    ps_dir = base / "permission-sets"
    if ps_dir.exists():
        files += list(ps_dir.glob("*.json"))

    px = (prefix or "").strip("/")
    checked, missing = 0, []
    for p in files:
        rel = p.relative_to(base).as_posix()
        key = f"{px}/{rel}" if px else rel
        try:
            s3.head_object(Bucket=bucket, Key=key); checked += 1
        except Exception:
            missing.append(key)
    ok = (len(missing) == 0 and checked == len(files))
    return ok, {"Bucket": bucket, "Prefix": px, "Checked": checked, "Expected": len(files), "Missing": missing}

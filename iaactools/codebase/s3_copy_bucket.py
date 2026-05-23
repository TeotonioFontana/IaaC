#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
s3_copy_bucket.py — Copy all objects from one S3 path to another (cross-account ready)

Examples
--------
# Simple: copy an entire bucket to another bucket/prefix (same account/creds)
python s3_copy_bucket.py \
  --src-bucket my-source-bucket \
  --dst-bucket 123456789012-target-bucket \
  --dst-prefix backups/2025-10-26/

# Cross-account: assume read role in source + write role in destination
python s3_copy_bucket.py \
  --src-bucket my-source-bucket --src-prefix exports/ \
  --dst-bucket 212533511020-tf-iaac --dst-prefix tf-idc/ \
  --assume-src-role arn:aws:iam::111111111111:role/S3ReadRole \
  --assume-dst-role arn:aws:iam::212533511020:role/S3WriteRole \
  --dst-kms-key-id arn:aws:kms:us-east-1:212533511020:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  --dst-region us-east-1 --max-workers 16

# With config file (YAML/JSON). CLI flags override the file.
python s3_copy_bucket.py --config conf/prod/s3_copy.yaml

Config keys (optional)
----------------------
src_bucket, src_prefix, src_region, src_profile, assume_src_role, assume_src_sts_region
dst_bucket, dst_prefix, dst_region, dst_profile, assume_dst_role, assume_dst_sts_region
storage_class, dst_kms_key_id, acl, copy_tags, skip_existing, start_after,
max_workers, dry_run
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import botocore
from botocore.config import Config

try:
    import boto3
except Exception:
    print("boto3 is required. Install with: pip install boto3", file=sys.stderr)
    sys.exit(2)

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # only needed for YAML config

# -----------------------
# CLI / Config
# -----------------------

def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Copy all objects from one S3 path to another (cross-account ready).")
    p.add_argument("--config", default=None, help="YAML/JSON file with defaults; CLI overrides these values.")

    # Source
    p.add_argument("--src-bucket", help="Source bucket name")
    p.add_argument("--src-prefix", default="", help="Source key prefix (optional)")
    p.add_argument("--src-region", default=None, help="Source S3 region (optional)")
    p.add_argument("--src-profile", default=None, help="AWS CLI profile for source (optional)")
    p.add_argument("--assume-src-role", default=None, help="Role ARN to assume for source reads")
    p.add_argument("--assume-src-sts-region", default=None, help="STS region for source role assumption")

    # Destination
    p.add_argument("--dst-bucket", help="Destination bucket name")
    p.add_argument("--dst-prefix", default="", help="Destination key prefix (optional)")
    p.add_argument("--dst-region", default=None, help="Destination S3 region")
    p.add_argument("--dst-profile", default=None, help="AWS CLI profile for destination (optional)")
    p.add_argument("--assume-dst-role", default=None, help="Role ARN to assume for destination writes")
    p.add_argument("--assume-dst-sts-region", default=None, help="STS region for destination role assumption")

    # Behavior
    p.add_argument("--storage-class", default=None,
                   choices=["STANDARD","STANDARD_IA","ONEZONE_IA","INTELLIGENT_TIERING","GLACIER_IR","GLACIER",
                            "DEEP_ARCHIVE","REDUCED_REDUNDANCY","EXPRESS_ONEZONE","OUTPOSTS","SNOW","FSX_OPENZFS"],
                   help="Set a storage class for destination objects (optional)")
    p.add_argument("--dst-kms-key-id", default=None, help="KMS key ARN/alias for SSE-KMS on destination")
    p.add_argument("--acl", default=None, help="CANNED ACL for destination objects (e.g., private, bucket-owner-full-control)")
    p.add_argument("--copy-tags", action="store_true", help="Copy object tags (requires GetObjectTagging on source)")
    p.add_argument("--skip-existing", action="store_true", help="Skip if destination object exists with same size")
    p.add_argument("--start-after", default=None, help="Resume listing after this key (uses ListObjectsV2 StartAfter)")
    p.add_argument("--max-workers", type=int, default=8, help="Max concurrent copies (default: 8)")
    p.add_argument("--dry-run", action="store_true", help="Plan only; do not copy")

    return p.parse_args(argv)


def _load_config(path: str) -> Dict[str, Any]:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        _fatal("Config file not found", {"path": str(cfg_path)})
    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in (".yaml", ".yml"):
        if yaml is None:
            _fatal("PyYAML not installed but a YAML config was provided.", {"pip": "pip install pyyaml"})
        try:
            data = yaml.safe_load(text) or {}
        except Exception as e:
            _fatal("Failed to parse YAML config", {"error": str(e)})
    else:
        try:
            data = json.loads(text or "{}")
        except Exception as e:
            _fatal("Failed to parse JSON config", {"error": str(e)})
    if not isinstance(data, dict):
        _fatal("Config top-level must be an object/mapping.", {"path": str(cfg_path)})
    return data


def _merge(args: argparse.Namespace, cfg: Dict[str, Any]) -> argparse.Namespace:
    # CLI overrides config; fill missing args from config
    for k, v in cfg.items():
        if not hasattr(args, k):
            continue
        cur = getattr(args, k)
        if cur in (None, "", False):
            setattr(args, k, v)
    # Normalize booleans if provided as strings
    for b in ("copy_tags", "skip_existing", "dry_run"):
        v = getattr(args, b, None)
        if isinstance(v, str):
            setattr(args, b, v.strip().lower() in ("1","true","yes","y","on"))
    # Uppercase storage class
    if args.storage_class:
        args.storage_class = str(args.storage_class).upper().strip()
    # Requireds after merge
    missing = []
    if not args.src_bucket:
        missing.append("src_bucket / --src-bucket")
    if not args.dst_bucket:
        missing.append("dst_bucket / --dst-bucket")
    if missing:
        _fatal("Missing required values", {"missing": missing})
    return args

# -----------------------
# AWS helpers
# -----------------------

def _fatal(msg: str, ctx: Optional[dict] = None) -> None:
    if ctx:
        print(f"[FATAL] {msg}\nContext: {json.dumps(ctx)}", file=sys.stderr)
    else:
        print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(2)


def _assumed_session(*, base_profile: Optional[str], region: Optional[str],
                     role_arn: Optional[str], sts_region: Optional[str]) -> boto3.Session:
    """
    Build a boto3 session, optionally assuming a role.
    """
    # Base session (could be None profile; environment creds are fine)
    base = boto3.Session(profile_name=base_profile, region_name=region)
    if not role_arn:
        return base

    sts = base.client("sts", region_name=sts_region or region)
    try:
        resp = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"S3Copy_{int(time.time())}"
        )
    except botocore.exceptions.ClientError as e:
        _fatal("AssumeRole failed", {"role": role_arn, "error": str(e)})

    creds = resp["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


def _s3_clients_for_copy(args) -> Tuple[boto3.client, boto3.client, boto3.resource, boto3.resource]:
    # Source
    src_sess = _assumed_session(
        base_profile=args.src_profile,
        region=args.src_region,
        role_arn=args.assume_src_role,
        sts_region=args.assume_src_sts_region,
    )
    # Destination
    dst_sess = _assumed_session(
        base_profile=args.dst_profile,
        region=args.dst_region,
        role_arn=args.assume_dst_role,
        sts_region=args.assume_dst_sts_region,
    )

    cfg = Config(retries={"max_attempts": 10, "mode": "standard"}, max_pool_connections=max(20, args.max_workers * 2))
    src_client = src_sess.client("s3", config=cfg, region_name=args.src_region)
    dst_client = dst_sess.client("s3", config=cfg, region_name=args.dst_region)
    src_res = src_sess.resource("s3", config=cfg, region_name=args.src_region)
    dst_res = dst_sess.resource("s3", config=cfg, region_name=args.dst_region)
    return src_client, dst_client, src_res, dst_res


def _kms_preflight(dst_sess: boto3.Session, dst_region: Optional[str], key_id: Optional[str]) -> None:
    if not key_id:
        return
    kms = dst_sess.client("kms", region_name=dst_region)
    try:
        kms.describe_key(KeyId=key_id)
    except botocore.exceptions.BotoCoreError as e:
        _fatal("KMS DescribeKey failed (destination).", {"region": dst_region, "key": key_id, "error": str(e)})
    except botocore.exceptions.ClientError as e:
        _fatal("KMS DescribeKey failed (destination).", {"region": dst_region, "key": key_id, "error": str(e)})

# -----------------------
# Core copy logic
# -----------------------

@dataclass
class CopyPlan:
    src_bucket: str
    src_key: str
    dst_bucket: str
    dst_key: str
    size: int

def _iter_source_objects(client, bucket: str, prefix: str, start_after: Optional[str]) -> Iterable[Dict[str, Any]]:
    paginator = client.get_paginator("list_objects_v2")
    kwargs = {"Bucket": bucket, "Prefix": prefix or ""}
    if start_after:
        kwargs["StartAfter"] = start_after
    for page in paginator.paginate(**kwargs):
        for obj in page.get("Contents", []):
            # Skip 'directory markers' (0-byte keys ending with '/'), but keep real 0-byte files
            key = obj.get("Key", "")
            if key.endswith("/") and obj.get("Size", 0) == 0:
                continue
            yield obj

def _rel_key(full_key: str, prefix: str) -> str:
    if not prefix:
        return full_key
    if full_key.startswith(prefix):
        return full_key[len(prefix):]
    return full_key  # graceful if listing is slightly broader

def _head_size(client, bucket: str, key: str) -> Optional[int]:
    try:
        resp = client.head_object(Bucket=bucket, Key=key)
        return int(resp.get("ContentLength", 0))
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey", "NotFound"):
            return None
        # any other head failure should be surfaced
        raise

def _make_extra_args(args) -> Dict[str, Any]:
    extra: Dict[str, Any] = {"MetadataDirective": "COPY"}
    if args.copy_tags:
        extra["TaggingDirective"] = "COPY"
    if args.storage_class:
        extra["StorageClass"] = args.storage_class
    if args.dst_kms_key_id:
        extra["ServerSideEncryption"] = "aws:kms"
        extra["SSEKMSKeyId"] = args.dst_kms_key_id
    if args.acl:
        extra["ACL"] = args.acl
    return extra

def _copy_one(plan: CopyPlan, *, src_client, dst_res, extra_args: Dict[str, Any], dry_run: bool) -> Tuple[str, bool, Optional[str]]:
    """Returns (key, success, error_message)"""
    if dry_run:
        print(f"[DRY-RUN] Would copy s3://{plan.src_bucket}/{plan.src_key} -> s3://{plan.dst_bucket}/{plan.dst_key}")
        return plan.src_key, True, None

    obj = dst_res.Object(plan.dst_bucket, plan.dst_key)
    try:
        # Use Object.copy_from with SourceClient so cross-account GET is signed by src creds
        obj.copy_from(
            CopySource={"Bucket": plan.src_bucket, "Key": plan.src_key},
            ExtraArgs=extra_args,
            SourceClient=src_client,
            # Optional: tuning multipart threshold/part size if needed
            # Config=TransferConfig(multipart_threshold=8*1024*1024, multipart_chunksize=8*1024*1024)
        )
        return plan.src_key, True, None
    except Exception as e:
        return plan.src_key, False, str(e)

# -----------------------
# Runner
# -----------------------

def main():
    args = parse_args()

    # Merge config (if provided)
    if args.config:
        cfg = _load_config(args.config)
        args = _merge(args, cfg)

    # Sanitize prefixes
    args.src_prefix = (args.src_prefix or "").lstrip("/")
    args.dst_prefix = (args.dst_prefix or "").lstrip("/")

    # Build clients/resources
    src_client, dst_client, src_res, dst_res = _s3_clients_for_copy(args)

    # KMS preflight (dest)
    _kms_preflight(dst_res.meta.client._request_signer._credentials and boto3.Session(), args.dst_region, args.dst_kms_key_id)
    # ^ The above session trick is noisy; simpler: use dst_client region directly:
    if args.dst_kms_key_id:
        try:
            kms = boto3.session.Session().client("kms", region_name=args.dst_region)
            kms.describe_key(KeyId=args.dst_kms_key_id)
        except Exception as e:
            _fatal("KMS preflight failed. Ensure the key exists in the destination account/region and you can use it.",
                   {"region": args.dst_region, "key": args.dst_kms_key_id, "error": str(e)})

    # Banner
    print(f"[START] S3 Copy — plan")
    print(f"  From: s3://{args.src_bucket}/{args.src_prefix}")
    print(f"    To: s3://{args.dst_bucket}/{args.dst_prefix}")
    print(f" Options: dry_run={args.dry_run} copy_tags={args.copy_tags} skip_existing={args.skip_existing} workers={args.max_workers}")
    if args.storage_class: print(f"          storage_class={args.storage_class}")
    if args.dst_kms_key_id: print(f"          dst_kms_key_id={args.dst_kms_key_id}")
    if args.acl: print(f"          acl={args.acl}")
    if args.start_after: print(f"          start_after={args.start_after}")

    # Plan
    plans: List[CopyPlan] = []
    total_bytes = 0
    for obj in _iter_source_objects(src_client, args.src_bucket, args.src_prefix, args.start_after):
        src_key = obj["Key"]
        rel = _rel_key(src_key, args.src_prefix)
        dst_key = f"{args.dst_prefix}{rel}" if args.dst_prefix else rel
        size = int(obj.get("Size") or 0)

        if args.skip_existing:
            try:
                dsize = _head_size(dst_client, args.dst_bucket, dst_key)
                if dsize is not None and dsize == size:
                    print(f"[SKIP] Exists (same size): s3://{args.dst_bucket}/{dst_key}")
                    continue
            except Exception as e:
                _fatal("HeadObject failed while checking destination", {"bucket": args.dst_bucket, "key": dst_key, "error": str(e)})

        plans.append(CopyPlan(args.src_bucket, src_key, args.dst_bucket, dst_key, size))
        total_bytes += size

    print(f"[INFO] Objects to copy: {len(plans)}  (~{total_bytes/1024/1024:.1f} MiB)")

    if args.dry_run:
        print("[DONE] Dry-run complete. Nothing copied.")
        return

    if not plans:
        print("[DONE] Nothing to do.")
        return

    extra_args = _make_extra_args(args)

    # Execute with a thread pool
    ok = 0
    fail = 0
    errors: List[Tuple[str, str]] = []

    with cf.ThreadPoolExecutor(max_workers=args.max_workers) as ex:
        futures = [ex.submit(_copy_one, plan, src_client=src_client, dst_res=dst_res, extra_args=extra_args, dry_run=False)
                   for plan in plans]
        for fut in cf.as_completed(futures):
            key, success, err = fut.result()
            if success:
                ok += 1
                print(f"[OK] {key}")
            else:
                fail += 1
                errors.append((key, err or "unknown error"))
                print(f"[ERR] {key} :: {err}", file=sys.stderr)

    print(f"[SUMMARY] copied={ok} failed={fail}")
    if fail:
        # Stop the pipeline on failure (per your phase behavior)
        _fatal("Some objects failed to copy", {"failed": fail, "errors": errors[:10]})

    print("[DONE] All objects copied successfully.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ABORTED] Interrupted by user.", file=sys.stderr)
        sys.exit(130)

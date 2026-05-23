#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sso_apply.py — Recreate IAM Identity Center (SSO) config from an export
=======================================================================

What it does
------------
Reads a run folder produced by `sso_exporter.py` (local or S3), then:
- Ensures the IdC instance exists in the selected region (you must enable it).
- Creates/updates **permission sets** (name, inline policy, managed policy ARNs).
- Rebuilds **account assignments**:
  • Resolves principals (USER/GROUP) in the current identity store by a few
    heuristics: UserName, DisplayName, PrimaryEmail (users) or DisplayName (groups).
  • Creates missing assignments and skips the ones that already exist.

Safety / Idempotency
--------------------
- Uses read-then-write; only creates when missing.
- `--dry-run` prints planned actions without changing anything.

Inputs
------
- Local folder: `--source-dir <path>`
- Or S3: `--s3-bucket <bucket> --s3-prefix <prefix> [--run-id <id>|--use-latest]`

Examples
--------
# From local folder (a single run path)
python sso_apply.py --region us-east-1 --source-dir ./results/idc-export/runs/2025-10-15T12-34-56Z

# From S3 latest
python sso_apply.py --region us-east-1 \
  --s3-bucket my-dr-bucket --s3-prefix idc-backup/ --use-latest

# Dry run first
python sso_apply.py --region us-east-1 --use-latest \
  --s3-bucket my-dr-bucket --s3-prefix idc-backup/ --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# ----------------- utils -----------------
def log(msg: str, **kv):
    print(msg if not kv else f"{msg} | {json.dumps(kv, ensure_ascii=False)}")

def safe_load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))

def download_run_from_s3(s3, bucket: str, prefix: str, run_id: str, dest: Path) -> Path:
    """Sync a run folder from S3 into dest and return the local path."""
    base = f"{prefix.rstrip('/')}/runs/{run_id}"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=base + "/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(base)+1:]
            if not rel:
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(out))
            log("S3:GET", key=key, file=str(out))
    return dest

def fetch_latest_run_id(s3, bucket: str, prefix: str) -> str:
    key = f"{prefix.rstrip('/')}/index/latest.json"
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    data = json.loads(body.decode("utf-8"))
    rid = data.get("run_id")
    if not rid:
        raise SystemExit("index/latest.json missing run_id.")
    return rid

# ----------------- Identity helpers -----------------
def discover_instance(sess) -> Tuple[str, str]:
    sso = sess.client("sso")
    resp = sso.list_instances()
    items = resp.get("Instances", [])
    if not items:
        raise SystemExit("No IAM Identity Center instance found. Enable it in this region first.")
    inst = items[0]
    return inst["InstanceArn"], inst["IdentityStoreId"]

def map_permission_sets(sso_admin, instance_arn: str) -> Dict[str, dict]:
    """Return {Name: {'Arn': arn, 'Desc': describe}} for existing ones."""
    name_map: Dict[str, dict] = {}
    token = None
    while True:
        resp = sso_admin.list_permission_sets(InstanceArn=instance_arn, NextToken=token) if token \
            else sso_admin.list_permission_sets(InstanceArn=instance_arn)
        for arn in resp.get("PermissionSets", []):
            d = sso_admin.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=arn)["PermissionSet"]
            name = d.get("Name") or arn.split("/")[-1]
            name_map[name] = {"Arn": arn, "Desc": d}
        token = resp.get("NextToken")
        if not token:
            break
    return name_map

def ensure_permission_set(sso_admin, instance_arn: str, spec: dict, dry_run: bool) -> str:
    """
    Ensure a permission set exists with given name and policy attachments.
    Returns its ARN.
    """
    name = spec["Name"]
    exist = map_permission_sets(sso_admin, instance_arn).get(name)
    if not exist:
        log("PS:CREATE", name=name)
        if dry_run:
            return f"arn:aws:sso:::permissionSet/dry-run/{name}"
        create = sso_admin.create_permission_set(
            InstanceArn=instance_arn,
            Name=name,
            SessionDuration=spec.get("SessionDuration"),
            RelayState=spec.get("RelayState"),
            Tags=spec.get("Tags", []),
        )
        ps_arn = create["PermissionSet"]["PermissionSetArn"]
    else:
        ps_arn = exist["Arn"]
        # Update mutable props if drifted (best-effort)
        # (sso-admin lacks direct update API for all fields; we skip unless needed)
        log("PS:EXISTS", name=name, arn=ps_arn)

    # Managed policies: reconcile (attach missing)
    want = set(spec.get("ManagedPolicies") or [])
    if want:
        # list current
        cur = set()
        token = None
        while True:
            resp = sso_admin.list_managed_policies_in_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=ps_arn, NextToken=token
            ) if token else sso_admin.list_managed_policies_in_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=ps_arn
            )
            for a in resp.get("AttachedManagedPolicies", []):
                arn = a.get("Arn")
                if arn:
                    cur.add(arn)
            token = resp.get("NextToken")
            if not token:
                break
        to_add = sorted(want - cur)
        for arn in to_add:
            log("PS:ATTACH_MANAGED", name=name, policy_arn=arn)
            if not dry_run:
                sso_admin.attach_managed_policy_to_permission_set(
                    InstanceArn=instance_arn, PermissionSetArn=ps_arn, ManagedPolicyArn=arn
                )

    # Inline policy: replace if differs (simple put)
    inline = spec.get("InlinePolicy")
    if inline:
        log("PS:PUT_INLINE", name=name)
        if not dry_run:
            sso_admin.put_inline_policy_to_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=ps_arn, InlinePolicy=json.dumps(inline)
            )
    else:
        # optional: remove if present — skipping to be conservative
        pass

    return ps_arn

def resolve_user(identity, identity_store_id: str, hint: dict) -> Optional[str]:
    """Try by UserName, then DisplayName, then PrimaryEmail."""
    # identitystore supports a single filter at a time; try a few
    try_order: List[Tuple[str, Optional[str]]] = [
        ("UserName", hint.get("UserName")),
        ("DisplayName", hint.get("DisplayName")),
        ("PrimaryEmail", hint.get("PrimaryEmail")),
    ]
    for attr, value in try_order:
        if not value:
            continue
        filt = [{"AttributePath": attr, "AttributeValue": value}]
        try:
            resp = identity.list_users(IdentityStoreId=identity_store_id, Filters=filt)
            users = resp.get("Users", [])
            if users:
                return users[0]["UserId"]
        except ClientError:
            continue
    return None

def resolve_group(identity, identity_store_id: str, hint: dict) -> Optional[str]:
    name = hint.get("DisplayName")
    if not name:
        return None
    try:
        resp = identity.list_groups(IdentityStoreId=identity_store_id, Filters=[{"AttributePath": "DisplayName", "AttributeValue": name}])
        groups = resp.get("Groups", [])
        if groups:
            return groups[0]["GroupId"]
    except ClientError:
        return None
    return None

def ensure_assignment(sso_admin, instance_arn: str, account_id: str, ps_arn: str, principal: dict, dry_run: bool):
    # check if already exists
    typ = principal.get("PrincipalType")
    desired_pid = principal.get("PrincipalId")  # original ID (may not match in new store)
    # First try with current store resolution if IDs differ
    identity = sso_admin.meta.client('identitystore')  # not valid; replaced below

def assignment_exists(sso_admin, instance_arn: str, account_id: str, ps_arn: str, principal_id: str, principal_type: str) -> bool:
    token = None
    while True:
        resp = sso_admin.list_account_assignments(
            InstanceArn=instance_arn, AccountId=account_id, PermissionSetArn=ps_arn, NextToken=token
        ) if token else sso_admin.list_account_assignments(
            InstanceArn=instance_arn, AccountId=account_id, PermissionSetArn=ps_arn
        )
        for a in resp.get("AccountAssignments", []):
            if a["PrincipalType"] == principal_type and a["PrincipalId"] == principal_id:
                return True
        token = resp.get("NextToken")
        if not token:
            break
    return False

# ----------------- main apply -----------------
def parse_args():
    ap = argparse.ArgumentParser(description="Apply IAM Identity Center export into a fresh IdC instance.")
    ap.add_argument("--profile", help="AWS profile.")
    ap.add_argument("--region", required=True, help="Region with IAM Identity Center enabled.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-dir", help="Local run folder path (the one with manifest.json inside).")
    src.add_argument("--s3-bucket", help="S3 bucket containing the export.")
    ap.add_argument("--s3-prefix", default="idc-backup/", help="S3 key prefix (with --s3-bucket).")
    ap.add_argument("--run-id", help="Specific run id (with --s3-bucket).")
    ap.add_argument("--use-latest", action="store_true", help="Use index/latest.json to select the run (with --s3-bucket).")
    ap.add_argument("--dry-run", action="store_true", help="Plan only; do not create/update anything.")
    return ap.parse_args()

def main():
    args = parse_args()
    sess_args = {}
    if args.profile:
        sess_args["profile_name"] = args.profile
    sess = boto3.Session(region_name=args.region, **sess_args)
    sso_admin = sess.client("sso-admin")
    identity = sess.client("identitystore")
    s3 = sess.client("s3") if args.s3_bucket else None

    # Locate source
    if args.source_dir:
        run_path = Path(args.source_dir).expanduser().resolve()
        if not (run_path / "manifest.json").exists():
            raise SystemExit(f"--source-dir must point at a run folder (missing manifest.json): {run_path}")
    else:
        if not s3:
            raise SystemExit("When not using --source-dir you must set --s3-bucket.")
        run_id = args.run_id or (fetch_latest_run_id(s3, args.s3_bucket, args.s3_prefix) if args.use_latest else None)
        if not run_id:
            raise SystemExit("Provide --run-id or --use-latest with S3 source.")
        cache = Path("./.idc-apply-cache").resolve()
        cache.mkdir(parents=True, exist_ok=True)
        run_path = download_run_from_s3(s3, args.s3_bucket, args.s3_prefix, run_id, cache)

    # Discover instance
    sso = sess.client("sso")
    insts = sso.list_instances().get("Instances", [])
    if not insts:
        raise SystemExit("No IdC instance found. Enable IAM Identity Center in this region and retry.")
    instance_arn = insts[0]["InstanceArn"]
    identity_store_id = insts[0]["IdentityStoreId"]
    log("INSTANCE", arn=instance_arn, identity_store_id=identity_store_id)

    # Ensure Permission Sets
    ps_dir = run_path / "permission-sets"
    if ps_dir.exists():
        for p in sorted(ps_dir.glob("*.json")):
            spec = safe_load_json(p)
            arn = ensure_permission_set(sso_admin, instance_arn, spec, args.dry_run)
            log("PS:READY", name=spec.get("Name"), arn=arn)
    else:
        log("WARN", msg="No permission-sets directory; skipping.")

    # Build map Name -> Arn after we (maybe) created them
    ps_map = map_permission_sets(sso_admin, instance_arn)

    # Assignments
    asn_dir = run_path / "assignments"
    if asn_dir.exists():
        for p in sorted(asn_dir.glob("*.json")):
            entries: List[dict] = safe_load_json(p)
            account_id = p.stem
            for e in entries:
                ps_name = e["PermissionSetName"]
                ps_arn = ps_map.get(ps_name, {}).get("Arn")
                if not ps_arn:
                    log("ASSIGN:SKIP", reason="permission set missing", name=ps_name, account=account_id)
                    continue
                principal = e["Principal"]
                ptype = principal.get("PrincipalType")
                # Try to reuse original principal id; if not valid, resolve by hints
                resolved_pid = principal.get("PrincipalId")
                valid = False
                if resolved_pid:
                    try:
                        valid = assignment_exists(sso_admin, instance_arn, account_id, ps_arn, resolved_pid, ptype)
                        # If it exists, no action; if not, keep the id to try Create anyway
                    except ClientError:
                        valid = False
                if not valid:
                    # Attempt to resolve to *current* principal id in this identity store
                    if ptype == "USER":
                        pid2 = resolve_user(identity, identity_store_id, principal)
                    else:
                        pid2 = resolve_group(identity, identity_store_id, principal)
                    if pid2:
                        resolved_pid = pid2

                # If already exists, skip; else create
                if assignment_exists(sso_admin, instance_arn, account_id, ps_arn, resolved_pid, ptype):
                    log("ASSIGN:EXISTS", account=account_id, ps=ps_name, principal_type=ptype)
                else:
                    log("ASSIGN:CREATE", account=account_id, ps=ps_name, principal_type=ptype)
                    if not args.dry_run:
                        sso_admin.create_account_assignment(
                            InstanceArn=instance_arn,
                            TargetId=account_id,
                            TargetType="AWS_ACCOUNT",
                            PermissionSetArn=ps_arn,
                            PrincipalType=ptype,
                            PrincipalId=resolved_pid,
                        )
    else:
        log("WARN", msg="No assignments directory; skipping.")

    log("DONE", source=str(run_path), dry_run=args.dry_run)

# -------------- missing helper impls --------------
def resolve_user(identity, identity_store_id: str, hint: dict) -> Optional[str]:
    # Re-implemented here due to scoping
    try_order: List[Tuple[str, Optional[str]]] = [
        ("UserName", hint.get("UserName")),
        ("DisplayName", hint.get("DisplayName")),
        ("PrimaryEmail", hint.get("PrimaryEmail")),
    ]
    for attr, value in try_order:
        if not value:
            continue
        try:
            resp = identity.list_users(IdentityStoreId=identity_store_id, Filters=[{"AttributePath": attr, "AttributeValue": value}])
            users = resp.get("Users", [])
            if users:
                return users[0]["UserId"]
        except ClientError:
            continue
    return None

def resolve_group(identity, identity_store_id: str, hint: dict) -> Optional[str]:
    name = hint.get("DisplayName")
    if not name:
        return None
    try:
        resp = identity.list_groups(IdentityStoreId=identity_store_id, Filters=[{"AttributePath": "DisplayName", "AttributeValue": name}])
        groups = resp.get("Groups", [])
        if groups:
            return groups[0]["GroupId"]
    except ClientError:
        return None
    return None

if __name__ == "__main__":
    main()

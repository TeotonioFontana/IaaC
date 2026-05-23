#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSO Exporter — IAM Identity Center snapshot (Identity Store + Permission Sets)
==============================================================================

Exports (locally):
  • Identity Store (users, groups, group-memberships)
  • Permission Sets (Describe + InlinePolicy + ManagedPolicy ARNs + CustomerManaged refs + Tags)

Optionally mirrors all exported files to an S3 bucket (e.g., in a backup region/account):
  --s3-bucket <name>
    [--s3-prefix tf-backup/idc/]
    [--s3-region us-east-1]
    [--s3-storage-class INTELLIGENT_TIERING|DEEP_ARCHIVE|...]
    [--s3-kms-key-id arn:aws:kms:...:key/... | alias/<name>]

Config file support:
  --config <path.{yaml|yml|json}>
    Load defaults from a config file. CLI flags override config keys.

Exit codes:
  0  success
  2  fatal configuration/AWS errors
"""

from __future__ import annotations
import argparse
import json
import sys
import time
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError, BotoCoreError, UnauthorizedSSOTokenError

try:
    import yaml  # optional; only needed for YAML configs
except Exception:
    yaml = None

SCRIPT_NAME = "SSO Exporter — IAM Identity Center snapshot"
SCRIPT_VERSION = "0.6.5"
SCRIPT_OBJECTIVE = (
    "Export Identity Store (users/groups/memberships) and full Permission Sets (policies & tags) "
    "and optionally mirror the artifacts to an S3 bucket (backup region/account)."
)

S3_STORAGE_CLASS_CHOICES = [
    "STANDARD", "STANDARD_IA", "ONEZONE_IA", "INTELLIGENT_TIERING", "GLACIER_IR", "GLACIER",
    "DEEP_ARCHIVE", "REDUCED_REDUNDANCY", "EXPRESS_ONEZONE", "OUTPOSTS", "SNOW", "FSX_OPENZFS"
]


# -------------------- small utils --------------------
def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def json_dump(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def short_id(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:8]


def safe_name(s: str) -> str:
    s = (s or "").strip()
    cleaned = "".join(ch if (ch.isalnum() or ch in "._- @()+/") else "_" for ch in s)
    return (cleaned or "noname")[:120]


def banner(args, account: Optional[str]) -> None:
    print(f"[START] {SCRIPT_NAME} — v{SCRIPT_VERSION}")
    print(f"        Objective: {SCRIPT_OBJECTIVE}")
    print(f"        Started (UTC): {utc_iso()}")
    mode = "PREVIEW" if args.preview else "SIMULATE" if args.simulate else "EXECUTE"
    print(f"        Mode: {mode}")
    print(f"        Home region: {args.region}   Profile: {args.profile or '(default)'}   Account: {account or '(unknown)'}")
    if args.assume:
        print(f"        AssumeRole: {args.assume}   STS Region: {args.assume_sts_region or '(default)'}")
    if args.s3_bucket:
        print(
            f"        S3 mirror: s3://{args.s3_bucket}/{(args.s3_prefix or '').lstrip('/')}"
            f"   Region={args.s3_region or args.region}   StorageClass={args.s3_storage_class}"
            f"   KMS={'(default SSE-S3)' if not args.s3_kms_key_id else args.s3_kms_key_id}"
        )


def fatal(msg: str, ctx: Optional[dict] = None) -> None:
    if ctx:
        print(f"[FATAL] {msg}\nContext: {json.dumps(ctx, ensure_ascii=False)}", file=sys.stderr)
    else:
        print(f"[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(2)


# -------------------- config helpers --------------------
def _load_config_file(path: str) -> dict:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        fatal("Config file not found", {"path": str(cfg_path)})
    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in (".yaml", ".yml"):
        if not yaml:
            fatal("YAML config provided but PyYAML not installed. Run: pip install pyyaml")
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text or "{}")
    if not isinstance(data, dict):
        fatal("Config file must contain a JSON/YAML object at top-level.", {"path": str(cfg_path)})
    return data


def _merge_args_with_config(args: argparse.Namespace, cfg: dict) -> argparse.Namespace:
    """
    Apply config defaults where CLI didn't specify a value.
    CLI always wins.
    """
    keymap = {
        # core
        "region": "region",
        "out_dir": "out_dir",
        "instance_arn": "instance_arn",
        "identity_store_id": "identity_store_id",
        "assume": "assume",
        "assume_sts_region": "assume_sts_region",
        "profile": "profile",
        "preview": "preview",
        "simulate": "simulate",
        # s3
        "s3_bucket": "s3_bucket",
        "s3_prefix": "s3_prefix",
        "s3_region": "s3_region",
        "s3_storage_class": "s3_storage_class",
        "s3_kms_key_id": "s3_kms_key_id",
    }
    for ck, attr in keymap.items():
        cur = getattr(args, attr, None)
        if (cur is None or (isinstance(cur, str) and cur == "") or (isinstance(cur, bool) and cur is False)):
            if ck in cfg and cfg[ck] is not None:
                setattr(args, attr, cfg[ck])

    # Normalize S3 storage class if provided
    if getattr(args, "s3_storage_class", None):
        sc = str(args.s3_storage_class).upper().strip()
        if sc not in S3_STORAGE_CLASS_CHOICES:
            fatal("Invalid s3_storage_class in config/CLI", {"value": sc, "allowed": S3_STORAGE_CLASS_CHOICES})
        args.s3_storage_class = sc

    return args


def _apply_final_defaults(args: argparse.Namespace) -> None:
    """
    Apply fallback defaults only AFTER merging config + CLI.
    Ensures config-set values aren't shadowed by argparse defaults.
    """
    if getattr(args, "s3_prefix", None) is None:
        args.s3_prefix = "tf-backup/idc/"
    if getattr(args, "s3_storage_class", None) is None:
        args.s3_storage_class = "DEEP_ARCHIVE"


def _require_after_merge(args: argparse.Namespace) -> None:
    missing = []
    if not getattr(args, "region", None):
        missing.append("--region (or config.region)")
    if not getattr(args, "out_dir", None):
        missing.append("--out-dir (or config.out_dir)")
    if missing:
        fatal("Missing required arguments after applying --config", {"missing": missing})


# -------------------- AWS sessions/assume --------------------
@dataclass
class Sessions:
    identitystore: Any
    sso_admin: Any
    account: Optional[str]


def build_sessions(args: argparse.Namespace) -> Sessions:
    # base session (profile only)
    base_kwargs = {}
    if args.profile:
        base_kwargs["profile_name"] = args.profile

    # optionally assume role for read-only export
    if args.assume:
        sts_region = args.assume_sts_region or "us-east-1"
        base = boto3.Session(**base_kwargs, region_name=sts_region)
        sts = base.client("sts")
        try:
            resp = sts.assume_role(RoleArn=args.assume, RoleSessionName=f"sso-export-{int(time.time())}")
        except UnauthorizedSSOTokenError:
            fatal(
                "Your AWS SSO session is expired or invalid.",
                {"action": f"Run: aws sso login --profile {args.profile or '(your-profile)'}", "role": args.assume},
            )
        except (ClientError, BotoCoreError) as e:
            fatal("AssumeRole failed", {"error": str(e), "role": args.assume})

        creds = resp["Credentials"]
        assumed_kwargs = {
            "aws_access_key_id": creds["AccessKeyId"],
            "aws_secret_access_key": creds["SecretAccessKey"],
            "aws_session_token": creds["SessionToken"],
            "region_name": args.region,
        }
        assumed = boto3.Session(**assumed_kwargs)
        sso_admin = assumed.client("sso-admin", region_name=args.region)
        identitystore = assumed.client("identitystore", region_name=args.region)
        try:
            acct = sts.get_caller_identity().get("Account")
        except Exception:
            acct = None
        return Sessions(identitystore=identitystore, sso_admin=sso_admin, account=acct)

    # no assume
    sess = boto3.Session(region_name=args.region, **base_kwargs)
    sso_admin = sess.client("sso-admin", region_name=args.region)
    identitystore = sess.client("identitystore", region_name=args.region)
    try:
        acct = sess.client("sts").get_caller_identity().get("Account")
    except UnauthorizedSSOTokenError:
        fatal(
            "Your AWS SSO session is expired or invalid.",
            {"action": f"Run: aws sso login --profile {args.profile or '(your-profile)'}"},
        )
    except Exception:
        acct = None
    return Sessions(identitystore=identitystore, sso_admin=sso_admin, account=acct)


# -------------------- discovery helpers --------------------
def discover_instance_and_store(
    sso_admin, identitystore_client, instance_arn: Optional[str], identity_store_id: Optional[str]
) -> Tuple[str, str]:
    inst_arn = instance_arn
    store_id = identity_store_id

    if not (inst_arn and store_id):
        arns: List[str] = []
        stores: List[str] = []
        paginator = sso_admin.get_paginator("list_instances")
        for page in paginator.paginate():
            for rec in page.get("Instances", []) or []:
                if rec.get("InstanceArn"):
                    arns.append(rec["InstanceArn"])
                if rec.get("IdentityStoreId"):
                    stores.append(rec["IdentityStoreId"])

        if not arns or not stores:
            fatal("Could not discover SSO instance; supply --instance-arn and --identity-store-id.")

        inst_arn = inst_arn or arns[0]
        store_id = store_id or stores[0]

    return inst_arn, store_id


# -------------------- identity store export --------------------
def export_users(identitystore_client, store_id: str, out_dir: Path) -> int:
    users: List[dict] = []
    paginator = identitystore_client.get_paginator("list_users")
    for page in paginator.paginate(IdentityStoreId=store_id):
        for u in page.get("Users", []) or []:
            users.append(u)
    json_dump(out_dir / "users.json", {"IdentityStoreId": store_id, "Count": len(users), "Users": users})
    return len(users)


def export_groups(identitystore_client, store_id: str, out_dir: Path) -> int:
    groups: List[dict] = []
    paginator = identitystore_client.get_paginator("list_groups")
    for page in paginator.paginate(IdentityStoreId=store_id):
        for g in page.get("Groups", []) or []:
            groups.append(g)
    json_dump(out_dir / "groups.json", {"IdentityStoreId": store_id, "Count": len(groups), "Groups": groups})
    return len(groups)


def export_group_memberships(identitystore_client, store_id: str, out_dir: Path) -> int:
    memberships: List[dict] = []
    grps = []
    gp = identitystore_client.get_paginator("list_groups")
    for page in gp.paginate(IdentityStoreId=store_id):
        grps.extend(page.get("Groups", []) or [])

    for g in grps:
        gid = g.get("GroupId")
        if not gid:
            continue
        mp = identitystore_client.get_paginator("list_group_memberships")
        for page in mp.paginate(IdentityStoreId=store_id, GroupId=gid):
            for m in page.get("GroupMemberships", []) or []:
                memberships.append(m)

    json_dump(out_dir / "group-memberships.json", {"IdentityStoreId": store_id, "Count": len(memberships), "Memberships": memberships})
    return len(memberships)


# -------------------- permission set export (FULL) --------------------
def export_permission_sets_full(sso_admin, instance_arn: str, out_dir: Path) -> int:
    """
    Export full permission set data:
      - DescribePermissionSet
      - GetInlinePolicyForPermissionSet
      - ListManagedPoliciesInPermissionSet
      - ListCustomerManagedPolicyReferencesInPermissionSet
      - ListTagsForResource
    Writes per-PS files + index.
    """
    ps_root = ensure_dir(out_dir / "permission-sets")
    ps_arns: List[str] = []
    pg = sso_admin.get_paginator("list_permission_sets")
    for page in pg.paginate(InstanceArn=instance_arn):
        ps_arns.extend(page.get("PermissionSets", []) or [])

    index_items: List[Dict[str, Any]] = []

    for arn in ps_arns:
        desc = sso_admin.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=arn)["PermissionSet"]

        inline_policy = None
        try:
            ip = sso_admin.get_inline_policy_for_permission_set(InstanceArn=instance_arn, PermissionSetArn=arn)
            inline_policy = ip.get("InlinePolicy")
        except ClientError:
            pass

        managed: List[str] = []
        try:
            mpg = sso_admin.get_paginator("list_managed_policies_in_permission_set")
            for page in mpg.paginate(InstanceArn=instance_arn, PermissionSetArn=arn):
                for mp in page.get("AttachedManagedPolicies", []) or []:
                    if mp.get("Arn"):
                        managed.append(mp["Arn"])
        except ClientError:
            pass

        cust_refs: List[Dict[str, str]] = []
        try:
            cmg = sso_admin.get_paginator("list_customer_managed_policy_references_in_permission_set")
            for page in cmg.paginate(InstanceArn=instance_arn, PermissionSetArn=arn):
                for ref in page.get("CustomerManagedPolicyReferences", []) or []:
                    cust_refs.append({"Name": ref.get("Name"), "Path": ref.get("Path")})
        except Exception:
            pass

        tags: Dict[str, str] = {}
        try:
            t = sso_admin.list_tags_for_resource(InstanceArn=instance_arn, ResourceArn=arn)
            for kv in t.get("Tags", []) or []:
                k = kv.get("Key")
                if k is not None:
                    tags[k] = kv.get("Value")
        except ClientError:
            pass

        name = desc.get("Name") or ""
        stub = f"{safe_name(name)}__{short_id(arn)}"
        record = {
            "Arn": arn,
            "Name": name,
            "Description": desc.get("Description"),
            "SessionDuration": desc.get("SessionDuration"),
            "RelayState": desc.get("RelayState"),
            "CreatedDate": desc.get("CreatedDate").isoformat() if desc.get("CreatedDate") else None,
            "InlinePolicy": inline_policy,
            "ManagedPolicyArns": managed,
            "CustomerManagedPolicyRefs": cust_refs,
            "Tags": tags,
        }

        json_dump(ps_root / f"{stub}.json", record)
        index_items.append({"Arn": arn, "Name": name, "File": f"{stub}.json"})

    json_dump(ps_root / "index.json", {"Count": len(index_items), "Items": index_items})
    return len(index_items)


# -------------------- S3 mirror helpers --------------------
def _kms_region_from_arn(kms_id: Optional[str]) -> Optional[str]:
    if not kms_id:
        return None
    if kms_id.startswith("arn:") and ":kms:" in kms_id:
        parts = kms_id.split(":")
        return parts[3] if len(parts) > 3 else None
    return None  # alias/<name> or raw key-id; region not encoded


def _preflight_validate_kms(args) -> None:
    """Validate KMS region alignment and key existence/permissions (best-effort)."""
    s3_region = args.s3_region or args.region
    kms_region = _kms_region_from_arn(args.s3_kms_key_id)
    if kms_region and kms_region != s3_region:
        fatal(
            "S3/KMS region mismatch for SSE-KMS.",
            {"s3_region": s3_region, "kms_key_region": kms_region, "hint": "Use a key/alias in the same region as the S3 bucket."},
        )
    if args.s3_kms_key_id:
        try:
            sess = boto3.Session(region_name=s3_region, profile_name=args.profile) if args.profile else boto3.Session(region_name=s3_region)
            kms = sess.client("kms")
            kms.describe_key(KeyId=args.s3_kms_key_id)  # raises if not found/authorized
        except (ClientError, BotoCoreError) as e:
            fatal(
                "KMS key not usable from this region/account (describe_key failed).",
                {"region": s3_region, "key": args.s3_kms_key_id, "error": str(e)},
            )


def _gather_export_paths(root: Path) -> List[Path]:
    """Collect all files to mirror: top-level *.json and permission-sets/*.json."""
    paths: List[Path] = []
    for name in ("users.json", "groups.json", "group-memberships.json"):
        p = root / name
        if p.exists():
            paths.append(p)
    ps_dir = root / "permission-sets"
    if ps_dir.exists():
        for p in sorted(ps_dir.glob("*.json")):
            paths.append(p)
    return paths


def _s3_client_for_args(args: argparse.Namespace):
    region = args.s3_region or args.region
    sess = boto3.Session(region_name=region, profile_name=args.profile) if args.profile else boto3.Session(region_name=region)
    return sess.client("s3")


def _s3_put_file(
    s3, bucket: str, key: str, local_path: Path, storage_class: Optional[str], kms_key_id: Optional[str], simulate: bool
) -> None:
    if simulate:
        print(f"[SIMULATE] Would upload {local_path} -> s3://{bucket}/{key}")
        return

    extra = {}
    if storage_class:
        extra["StorageClass"] = storage_class
    if kms_key_id:
        extra["ServerSideEncryption"] = "aws:kms"
        extra["SSEKMSKeyId"] = kms_key_id

    s3.upload_file(str(local_path), bucket, key, ExtraArgs=extra)


def mirror_to_s3(args: argparse.Namespace, out_dir: Path) -> None:
    if not args.s3_bucket:
        return

    files = _gather_export_paths(out_dir)
    if not files:
        print("[WARN] No files found to mirror to S3 (did the export run?)", file=sys.stderr)
        return

    # Validate KMS before opening the S3 client (clearer failures)
    _preflight_validate_kms(args)

    s3 = _s3_client_for_args(args)
    prefix = (args.s3_prefix or "").strip("/")
    if prefix:
        prefix += "/"

    ok = 0
    failed = 0
    for p in files:
        rel = p.relative_to(out_dir)
        key = f"{prefix}{rel.as_posix()}"
        try:
            _s3_put_file(
                s3,
                bucket=args.s3_bucket,
                key=key,
                local_path=p,
                storage_class=args.s3_storage_class,
                kms_key_id=args.s3_kms_key_id,
                simulate=(args.preview or args.simulate),
            )
            print(f"[S3] Mirrored {rel} -> s3://{args.s3_bucket}/{key}")
            ok += 1
        except UnauthorizedSSOTokenError:
            fatal(
                "Your AWS SSO session is expired or invalid while mirroring to S3.",
                {"action": f"Run: aws sso login --profile {args.profile or '(your-profile)'}"},
            )
        except (ClientError, BotoCoreError) as e:
            failed += 1
            print(f"[S3][ERROR] Failed to upload {rel}: {e}", file=sys.stderr)

    if failed:
        print(f"[S3] Mirror finished with errors (ok={ok}, failed={failed}).", file=sys.stderr)
    else:
        print(f"[S3] Mirror complete (ok={ok}).")


# -------------------- CLI --------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Export Identity Store and full Permission Sets from AWS IAM Identity Center.")

    # Config (NEW)
    ap.add_argument("--config", default=None, help="YAML/JSON file with defaults for this run (CLI overrides).")

    # Core export params (validated after merge)
    ap.add_argument("--region", help="IAM Identity Center HOME region (sso-admin/identitystore).")
    ap.add_argument("--out-dir", dest="out_dir", help="Output directory (will contain users/groups/memberships and permission-sets/).")
    ap.add_argument("--instance-arn", default=None, help="Identity Center InstanceArn (arn:aws:sso:::instance/ssoins-...).")
    ap.add_argument("--identity-store-id", default=None, help="IdentityStoreId (d-xxxxxxxxxx).")
    ap.add_argument("--assume", default=None, help="Role ARN to assume (read-only).")
    ap.add_argument("--assume-sts-region", default=None, help="Region to call STS AssumeRole (default: us-east-1).")
    ap.add_argument("--profile", default=None, help="AWS profile to use.")

    # Safety flags
    ap.add_argument("--preview", action="store_true", help="Print plan; still writes local files; S3 mirror logs 'Would upload'.")
    ap.add_argument("--simulate", action="store_true", help="Alias of normal run; local files written; S3 mirror logs 'Would upload'.")

    # S3 mirror options — defaults are None so config can supply values
    ap.add_argument("--s3-bucket", dest="s3_bucket", default=None, help="Destination S3 bucket to mirror the exported files.")
    ap.add_argument("--s3-prefix", dest="s3_prefix", default=None, help="Key prefix inside the destination bucket.")
    ap.add_argument("--s3-region", dest="s3_region", default=None, help="S3 client region (default: --region).")
    ap.add_argument(
        "--s3-storage-class",
        dest="s3_storage_class",
        default=None,
        choices=S3_STORAGE_CLASS_CHOICES,
        help="S3 storage class for mirrored objects (default: DEEP_ARCHIVE if unset).",
    )
    ap.add_argument("--s3-kms-key-id", dest="s3_kms_key_id", default=None, help="KMS key ARN/alias in the destination account for SSE-KMS.")

    return ap.parse_args()


# -------------------- main --------------------
def main() -> None:
    args = parse_args()

    # Load config and merge (CLI wins)
    if getattr(args, "config", None):
        cfg = _load_config_file(args.config)
        args = _merge_args_with_config(args, cfg)

    # Apply fallback defaults after merge, then validate
    _apply_final_defaults(args)
    _require_after_merge(args)

    sessions = build_sessions(args)

    # Discover InstanceArn + IdentityStoreId if omitted
    try:
        instance_arn, store_id = discover_instance_and_store(
            sessions.sso_admin, sessions.identitystore, args.instance_arn, args.identity_store_id
        )
    except (ClientError, BotoCoreError) as e:
        fatal("Discovery failed", {"error": str(e)})

    out_dir = ensure_dir(Path(args.out_dir))

    # Banner
    banner(args, sessions.account)
    print(f"[INFO] InstanceArn={instance_arn}")
    print(f"[INFO] IdentityStoreId={store_id}")

    # Identity Store exports
    try:
        u_count = export_users(sessions.identitystore, store_id, out_dir)
        g_count = export_groups(sessions.identitystore, store_id, out_dir)
        m_count = export_group_memberships(sessions.identitystore, store_id, out_dir)
        print(f"[INFO] Exported Identity Store: {u_count} users, {g_count} groups, {m_count} memberships")
    except (ClientError, BotoCoreError) as e:
        fatal("Identity Store export failed", {"error": str(e)})

    # Permission Sets (FULL details)
    try:
        ps_count = export_permission_sets_full(sessions.sso_admin, instance_arn, out_dir)
        print(f"[INFO] Exported {ps_count} permission set(s) with full policy details")
    except (ClientError, BotoCoreError) as e:
        fatal("Permission Set export failed", {"error": str(e)})

    # S3 mirror (optional)
    try:
        mirror_to_s3(args, out_dir)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[S3][ERROR] Unexpected error while mirroring: {e}", file=sys.stderr)
        # non-fatal: local export still succeeded

    print(f"[DONE] Export written to {out_dir}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except UnauthorizedSSOTokenError:
        print("[FATAL] Your AWS SSO session is expired or invalid.", file=sys.stderr)
        print("        Please run: aws sso login --profile <your-profile>", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred and the exporter stopped: {e}", file=sys.stderr)
        print("        Please check your AWS permissions, network, and parameters.", file=sys.stderr)
        sys.exit(2)

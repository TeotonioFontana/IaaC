#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sso_assignments_exporter.py — Export IAM Identity Center account assignments

Exports a snapshot of SSO Account Assignments across all accounts where each
Permission Set is provisioned.

Layout:
  <out-dir>/
    assignments/
      manifest.json
      by-account/
        <ACCOUNT_ID>/
          _index.json
          <SafePermissionSetName>__<shortid>.json    # per PS per account

Supports:
  --config <path.yaml|json>   # Load defaults; CLI overrides config keys

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
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError, UnauthorizedSSOTokenError

try:
    import yaml  # optional for YAML configs
except Exception:
    yaml = None

SCRIPT_NAME = "SSO Assignments Exporter"
SCRIPT_VERSION = "0.3.0"

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
    print(f"        Started (UTC): {utc_iso()}")
    mode = "PREVIEW" if args.preview else "SIMULATE" if args.simulate else "EXECUTE"
    print(f"        Mode: {mode}")
    print(f"        Home region: {args.region}   Profile: {args.profile or '(default)'}   Account: {account or '(unknown)'}")
    if args.assume:
        print(f"        AssumeRole: {args.assume}   STS Region: {args.assume_sts_region or '(default)'}")


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
    }
    for ck, attr in keymap.items():
        cur = getattr(args, attr, None)
        if (cur is None or (isinstance(cur, str) and cur == "") or (isinstance(cur, bool) and cur is False)):
            if ck in cfg and cfg[ck] is not None:
                setattr(args, attr, cfg[ck])
    return args


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
    sso_admin: Any
    identitystore: Any
    account: Optional[str]


def build_sessions(args: argparse.Namespace) -> Sessions:
    base_kwargs = {}
    if args.profile:
        base_kwargs["profile_name"] = args.profile

    if args.assume:
        sts_region = args.assume_sts_region or "us-east-1"
        base = boto3.Session(**base_kwargs, region_name=sts_region)
        sts = base.client("sts")
        try:
            resp = sts.assume_role(RoleArn=args.assume, RoleSessionName=f"sso-assign-export-{int(time.time())}")
        except UnauthorizedSSOTokenError:
            fatal(
                "Your AWS SSO session is expired or invalid.",
                {"action": f"Run: aws sso login --profile {args.profile or '(your-profile)'}", "role": args.assume},
            )
        except (ClientError, BotoCoreError) as e:
            fatal("AssumeRole failed", {"error": str(e), "role": args.assume})

        creds = resp["Credentials"]
        assumed = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=args.region,
        )
        sso_admin = assumed.client("sso-admin", region_name=args.region)
        identitystore = assumed.client("identitystore", region_name=args.region)
        try:
            acct = sts.get_caller_identity().get("Account")
        except Exception:
            acct = None
        return Sessions(sso_admin=sso_admin, identitystore=identitystore, account=acct)

    sess = boto3.Session(region_name=args.region, **base_kwargs)
    sso_admin = sess.client("sso-admin", region_name=args.region)
    identitystore = sess.client("identitystore", region_name=args.region)
    try:
        acct = sess.client("sts").get_caller_identity().get("Account")
    except UnauthorizedSSOTokenError:
        fatal("Your AWS SSO session is expired or invalid.",
              {"action": f"Run: aws sso login --profile {args.profile or '(your-profile)'}"})
    except Exception:
        acct = None
    return Sessions(sso_admin=sso_admin, identitystore=identitystore, account=acct)

# -------------------- discovery helpers --------------------
def discover_instance_and_store(sso_admin, identitystore_client, instance_arn: Optional[str], identity_store_id: Optional[str]) -> (str, str):
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

# -------------------- core export --------------------
def _list_all_permission_sets(sso_admin, instance_arn: str) -> List[str]:
    arns: List[str] = []
    pg = sso_admin.get_paginator("list_permission_sets")
    for page in pg.paginate(InstanceArn=instance_arn):
        arns.extend(page.get("PermissionSets", []) or [])
    return arns


def _describe_ps_name(sso_admin, instance_arn: str, ps_arn: str) -> str:
    try:
        d = sso_admin.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=ps_arn)["PermissionSet"]
        return d.get("Name") or ps_arn.rsplit("/", 1)[-1]
    except Exception:
        return ps_arn.rsplit("/", 1)[-1]


def _list_accounts_for_ps(sso_admin, instance_arn: str, ps_arn: str) -> List[str]:
    acct_ids: List[str] = []
    pg = sso_admin.get_paginator("list_accounts_for_provisioned_permission_set")
    for page in pg.paginate(InstanceArn=instance_arn, PermissionSetArn=ps_arn, ProvisioningStatus="LATEST_PERMISSION_SET_PROVISIONED"):
        acct_ids.extend(page.get("AccountIds", []) or [])
    return acct_ids


def _list_assignments(sso_admin, instance_arn: str, account_id: str, ps_arn: str) -> List[dict]:
    out: List[dict] = []
    pg = sso_admin.get_paginator("list_account_assignments")
    for page in pg.paginate(InstanceArn=instance_arn, AccountId=account_id, PermissionSetArn=ps_arn):
        out.extend(page.get("AccountAssignments", []) or [])
    return out


def export_assignments(sso_admin, instance_arn: str, out_base: Path) -> Dict[str, Any]:
    """
    For each Permission Set:
      - find accounts where it's provisioned
      - list assignments in each of those accounts
      - write per-account+PS JSON files and per-account _index.json
    Returns a manifest dict for summary.
    """
    by_acct_counts: Dict[str, int] = {}
    total_files = 0
    total_assignments = 0

    ps_arns = _list_all_permission_sets(sso_admin, instance_arn)
    ps_name_cache: Dict[str, str] = {}

    root = ensure_dir(out_base / "assignments")
    by_acct_root = ensure_dir(root / "by-account")

    for ps_arn in ps_arns:
        name = ps_name_cache.get(ps_arn)
        if not name:
            name = _describe_ps_name(sso_admin, instance_arn, ps_arn)
            ps_name_cache[ps_arn] = name
        stub = f"{safe_name(name)}__{short_id(ps_arn)}"

        acct_ids = _list_accounts_for_ps(sso_admin, instance_arn, ps_arn)
        for acct in acct_ids:
            acct_dir = ensure_dir(by_acct_root / acct)
            assignments = _list_assignments(sso_admin, instance_arn, acct, ps_arn)

            rec = {
                "AccountId": acct,
                "PermissionSetArn": ps_arn,
                "PermissionSetName": name,
                "Count": len(assignments),
                "Items": assignments,
                "ExportedAt": utc_iso(),
            }
            json_dump(acct_dir / f"{stub}.json", rec)
            total_files += 1
            total_assignments += len(assignments)
            by_acct_counts[acct] = by_acct_counts.get(acct, 0) + 1

    # Per-account _index.json
    for acct_dir in (by_acct_root.iterdir() if by_acct_root.exists() else []):
        if not acct_dir.is_dir():
            continue
        files = sorted(p for p in acct_dir.glob("*.json") if p.name != "_index.json")
        idx = {
            "AccountId": acct_dir.name,
            "Files": [p.name for p in files],
            "Count": len(files),
            "ExportedAt": utc_iso(),
        }
        json_dump(acct_dir / "_index.json", idx)

    manifest = {
        "CountPermissionSets": len(ps_arns),
        "FilesWritten": total_files,
        "AssignmentsTotal": total_assignments,
        "ByAccountPermissionSetFiles": by_acct_counts,
        "ExportedAt": utc_iso(),
    }
    json_dump(root / "manifest.json", manifest)
    return manifest

# -------------------- CLI --------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Export AWS IAM Identity Center (SSO) Account Assignments.")
    # NEW: config
    ap.add_argument("--config", default=None, help="YAML/JSON config with defaults; CLI overrides.")
    # Core (validate after merge)
    ap.add_argument("--region", help="IAM Identity Center HOME region.")
    ap.add_argument("--out-dir", dest="out_dir", help="Output base directory (will create assignments/ subdir).")
    ap.add_argument("--instance-arn", default=None, help="Identity Center InstanceArn (arn:aws:sso:::instance/ssoins-...).")
    ap.add_argument("--identity-store-id", default=None, help="IdentityStoreId (d-xxxxxxxxxx) [optional]")
    ap.add_argument("--profile", default=None, help="AWS profile.")
    ap.add_argument("--assume", default=None, help="Role ARN to assume (read-only).")
    ap.add_argument("--assume-sts-region", default=None, help="STS region for AssumeRole (default: us-east-1).")
    # Safety (read-only exporter; flags mainly for consistent banners/workflows)
    ap.add_argument("--preview", action="store_true", help="Plan-style banner; still writes local files (export is read-only).")
    ap.add_argument("--simulate", action="store_true", help="Alias for normal run; files still written.")
    return ap.parse_args()

# -------------------- main --------------------
def main() -> None:
    args = parse_args()

    # Merge config if provided (CLI wins)
    if getattr(args, "config", None):
        cfg = _load_config_file(args.config)
        args = _merge_args_with_config(args, cfg)

    # Validate after merge
    _require_after_merge(args)

    # Sessions
    sessions = build_sessions(args)

    # Discover (re-uses same helper as sso_exporter style)
    try:
        instance_arn, store_id = discover_instance_and_store(
            sessions.sso_admin, sessions.identitystore, args.instance_arn, args.identity_store_id
        )
    except (ClientError, BotoCoreError) as e:
        fatal("Discovery failed", {"error": str(e)})

    out_dir = ensure_dir(Path(args.out_dir))
    banner(args, sessions.account)
    print(f"[INFO] InstanceArn={instance_arn}")
    if store_id:
        print(f"[INFO] IdentityStoreId={store_id}")

    # Export
    try:
        manifest = export_assignments(sessions.sso_admin, instance_arn, out_dir)
        print(f"[INFO] Exported assignments: PS={manifest['CountPermissionSets']} files={manifest['FilesWritten']} total-assignments={manifest['AssignmentsTotal']}")
    except (ClientError, BotoCoreError) as e:
        fatal("Assignments export failed", {"error": str(e)})

    print(f"[DONE] Assignments written under {out_dir / 'assignments'}")

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
        print(f"[ERROR] Unexpected error: {e}", file=sys.stderr)
        sys.exit(2)

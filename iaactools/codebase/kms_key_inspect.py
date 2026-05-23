#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kms_key_inspect.py — Display properties of an AWS KMS key by ARN.

Outputs a compact JSON summary by default; can also print the full (or truncated) default key policy.

Exit codes:
  0 OK
  2 Usage/AWS error
"""

from __future__ import annotations
import argparse, json, sys
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError


def jprint(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Display properties of a KMS key by ARN.")
    ap.add_argument("--key-arn", required=True, help="KMS Key ARN (e.g., arn:aws:kms:us-east-1:123456789012:key/uuid)")
    ap.add_argument("--region", default=None, help="AWS region (optional; inferred from ARN if omitted).")
    ap.add_argument("--profile", default=None, help="AWS profile to use.")
    ap.add_argument("--show-policy", action="store_true", help="Also print the default key policy.")
    ap.add_argument("--policy-truncate", type=int, default=0, help="If >0, truncate policy JSON to this many characters.")
    ap.add_argument("--show-tags", action="store_true", help="Include key tags.")
    ap.add_argument("--show-grants", action="store_true", help="List up to N grants (use --grants-limit).")
    ap.add_argument("--grants-limit", type=int, default=20, help="Max grants to fetch when --show-grants is set.")
    return ap.parse_args()


def region_from_arn(arn: str) -> Optional[str]:
    # arn:partition:service:region:account-id:resource
    parts = arn.split(":")
    return parts[3] if len(parts) > 4 else None


def make_kms_client(region: Optional[str], profile: Optional[str]):
    sess_kwargs = {}
    if profile:
        sess_kwargs["profile_name"] = profile
    sess = boto3.Session(region_name=region, **sess_kwargs)
    return sess.client("kms")


def safe_get_policy(kms, key_arn: str) -> Optional[str]:
    try:
        pol = kms.get_key_policy(KeyId=key_arn, PolicyName="default")["Policy"]
        return pol
    except ClientError as e:
        return f"[unavailable: {e.response.get('Error', {}).get('Code', 'ClientError')}]"
    except Exception as e:
        return f"[unavailable: {e}]"


def list_aliases_for_key(kms, key_arn: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    paginator = kms.get_paginator("list_aliases")
    for page in paginator.paginate(KeyId=key_arn):
        out.extend(page.get("Aliases", []))
    return out


def list_tags(kms, key_arn: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    paginator = kms.get_paginator("list_resource_tags")
    for page in paginator.paginate(KeyId=key_arn):
        out.extend(page.get("Tags", []))
    return out


def list_some_grants(kms, key_arn: str, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        paginator = kms.get_paginator("list_grants")
        for page in paginator.paginate(KeyId=key_arn, Limit=min(max(limit, 1), 100)):
            out.extend(page.get("Grants", []))
            if len(out) >= limit:
                return out[:limit]
    except ClientError as e:
        out.append({"Error": f"list_grants failed: {e.response.get('Error', {}).get('Message', str(e))}"})
    return out


def main() -> None:
    args = parse_args()

    # Region: prefer explicit, else extract from ARN
    region = args.region or region_from_arn(args.key_arn)
    if not region:
        print("[ERROR] Could not infer region from ARN. Provide --region.", file=sys.stderr)
        sys.exit(2)

    try:
        kms = make_kms_client(region, args.profile)
        md = kms.describe_key(KeyId=args.key_arn)["KeyMetadata"]
    except ClientError as e:
        print(f"[ERROR] describe_key failed: {e}", file=sys.stderr); sys.exit(2)
    except Exception as e:
        print(f"[ERROR] AWS client error: {e}", file=sys.stderr); sys.exit(2)

    # Base summary
    summary: Dict[str, Any] = {
        "KeyArn": md.get("Arn"),
        "KeyId": md.get("KeyId"),
        "Region": region,
        "AccountId": md.get("AWSAccountId"),
        "Enabled": md.get("Enabled"),
        "KeyState": md.get("KeyState"),
        "KeyManager": md.get("KeyManager"),  # AWS or CUSTOMER
        "KeySpec": md.get("KeySpec"),
        "KeyUsage": md.get("KeyUsage"),
        "Description": md.get("Description"),
        "Origin": md.get("Origin"),
        "MultiRegion": md.get("MultiRegion"),
        "CustomerMasterKeySpec": md.get("CustomerMasterKeySpec"),  # older field, sometimes present
        "CreationDate": md.get("CreationDate").strftime("%Y-%m-%dT%H:%M:%SZ") if md.get("CreationDate") else None,
        "DeletionDate": md.get("DeletionDate").strftime("%Y-%m-%dT%H:%M:%SZ") if md.get("DeletionDate") else None,
        "ValidTo": md.get("ValidTo").strftime("%Y-%m-%dT%H:%M:%SZ") if md.get("ValidTo") else None,
        "ArnAliases": [],  # populated below
        "RotationEnabled": None,
    }

    # Rotation status
    try:
        rot = kms.get_key_rotation_status(KeyId=args.key_arn)
        summary["RotationEnabled"] = rot.get("KeyRotationEnabled")
    except ClientError as e:
        summary["RotationEnabled"] = f"[unavailable: {e.response.get('Error', {}).get('Code', 'ClientError')}]"

    # Aliases
    try:
        aliases = list_aliases_for_key(kms, args.key_arn)
        summary["ArnAliases"] = [a["AliasName"] for a in aliases if a.get("AliasName")]
    except Exception as e:
        summary["ArnAliases"] = [f"[unavailable: {e}]"]

    # Tags (optional)
    if args.show_tags:
        try:
            summary["Tags"] = list_tags(kms, args.key_arn)
        except ClientError as e:
            summary["Tags"] = [{"Error": f"list_resource_tags failed: {e.response.get('Error', {}).get('Message', str(e))}"}]

    # Grants (count; list optional)
    try:
        # list_grants can be heavy; fetch a page to count if available
        grants_page = kms.list_grants(KeyId=args.key_arn, Limit=1)
        summary["GrantsCount"] = grants_page.get("Total", len(grants_page.get("Grants", [])))
    except ClientError as e:
        summary["GrantsCount"] = f"[unavailable: {e.response.get('Error', {}).get('Code', 'ClientError')}]"

    if args.show_grants:
        summary["Grants"] = list_some_grants(kms, args.key_arn, args.grants_limit)

    # Policy (optional)
    if args.show_policy:
        pol = safe_get_policy(kms, args.key_arn)
        if isinstance(pol, str) and args.policy_truncate and len(pol) > args.policy_truncate:
            summary["DefaultPolicy"] = pol[:args.policy_truncate] + f"... [truncated {len(pol)-args.policy_truncate} chars]"
        else:
            summary["DefaultPolicy"] = pol

    jprint(summary)
    sys.exit(0)


if __name__ == "__main__":
    main()

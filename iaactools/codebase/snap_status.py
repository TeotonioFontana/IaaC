#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snap_status.py — Check EBS snapshot status in a region

- Lists snapshots (owner=self by default) with pagination
- Filters: state, date range, tags
- Health rule: completed AND VolumeSize > 0
- Output: table (default), JSON, or CSV
- Extras:
    --errors-only           show only unhealthy snapshots
    --show-error-details    pretty-print detailed JSON for unhealthy snaps to stderr
    --errors-json PATH      write those detailed records as JSON to PATH
- Exit code: 0 all healthy, 1 unhealthy found (with --fail-on-unhealthy), 2 API/usage error
"""

from __future__ import annotations
import argparse
import csv
import json
import sys
import datetime as dt
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

ISO = "%Y-%m-%d"


def parse_kv(items: List[str]) -> Dict[str, str]:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--tag expects key=value, got: {item}")
        k, v = item.split("=", 1)
        out[k] = v
    return out


def parse_date(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    return dt.datetime.strptime(s, ISO).replace(tzinfo=dt.timezone.utc)


def tags_to_dict(snap: dict) -> Dict[str, str]:
    return {t["Key"]: t["Value"] for t in snap.get("Tags", [])}


def row_from_snapshot(snap: dict) -> dict:
    t = tags_to_dict(snap)
    return {
        "SnapshotId": snap.get("SnapshotId"),
        "State": snap.get("State"),
        "Progress": snap.get("Progress"),
        "StartTime": snap.get("StartTime").astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if snap.get("StartTime")
        else "",
        "VolumeSizeGiB": snap.get("VolumeSize"),
        "VolumeId": snap.get("VolumeId"),
        "Encrypted": snap.get("Encrypted"),
        "KmsKeyId": snap.get("KmsKeyId"),
        "Name": t.get("Name", ""),
        "Description": (snap.get("Description") or "")[:200],
    }


def detailed_from_snapshot(snap: dict) -> dict:
    """A richer view to help debug failures. Avoids claiming non-existent fields."""
    t = tags_to_dict(snap)
    d = {
        "SnapshotId": snap.get("SnapshotId"),
        "State": snap.get("State"),
        "Progress": snap.get("Progress"),
        "StartTime": snap.get("StartTime").astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if snap.get("StartTime")
        else None,
        "VolumeId": snap.get("VolumeId"),
        "VolumeSizeGiB": snap.get("VolumeSize"),
        "Encrypted": snap.get("Encrypted"),
        "KmsKeyId": snap.get("KmsKeyId"),
        "OwnerId": snap.get("OwnerId"),
        "StorageTier": snap.get("StorageTier"),  # present when archive/standard tiers are involved
        "RestoreExpiryTime": snap.get("RestoreExpiryTime").astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if snap.get("RestoreExpiryTime")
        else None,
        "OutpostArn": snap.get("OutpostArn"),
        "Description": snap.get("Description"),
        "Tags": t,
    }
    # Include raw subset for completeness, without datetime objects
    safe_raw = {}
    for k, v in snap.items():
        if isinstance(v, dt.datetime):
            safe_raw[k] = v.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            safe_raw[k] = v
    d["Raw"] = safe_raw
    return d


def is_healthy(snap: dict) -> bool:
    try:
        size_ok = int(snap.get("VolumeSize") or 0) > 0
    except Exception:
        size_ok = False
    return (snap.get("State") == "completed") and size_ok


def fetch_snapshots(
    ec2,
    owners: List[str],
    state: Optional[str],
    started_after: Optional[dt.datetime],
    started_before: Optional[dt.datetime],
    tag_eq: Dict[str, str],
) -> List[dict]:
    snaps: List[dict] = []
    paginator = ec2.get_paginator("describe_snapshots")

    req: Dict = {}
    if owners:
        req["OwnerIds"] = owners

    filters = []
    if state:
        filters.append({"Name": "status", "Values": [state]})
    for k, v in (tag_eq or {}).items():
        filters.append({"Name": f"tag:{k}", "Values": [v]})
    if filters:
        req["Filters"] = filters

    for page in paginator.paginate(**req):
        for s in page.get("Snapshots", []):
            st = s.get("StartTime")
            if started_after and st and st < started_after:
                continue
            if started_before and st and st >= started_before:
                continue
            snaps.append(s)
    return snaps


def print_table(rows: List[dict]):
    if not rows:
        print("No snapshots matched.")
        return
    cols = [
        "SnapshotId",
        "State",
        "Progress",
        "StartTime",
        "VolumeSizeGiB",
        "VolumeId",
        "Encrypted",
        "KmsKeyId",
        "Name",
        "Description",
    ]
    widths = {c: max(len(c), *(len(str(r.get(c, "") or "")) for r in rows)) for c in cols}
    hdr = "  ".join(c.ljust(widths[c]) for c in cols)
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print("  ".join(str(r.get(c, "") or "").ljust(widths[c]) for c in cols))


def write_csv(rows: List[dict], path: str):
    cols = [
        "SnapshotId",
        "State",
        "Progress",
        "StartTime",
        "VolumeSizeGiB",
        "VolumeId",
        "Encrypted",
        "KmsKeyId",
        "Name",
        "Description",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"Wrote CSV: {path}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Check EBS snapshot status in a region.")
    ap.add_argument("--region", default=None, help="AWS region (default: from env/profile).")
    ap.add_argument("--profile", default=None, help="AWS profile name.")
    ap.add_argument(
        "--owner",
        action="append",
        default=["self"],
        help="Owner IDs to include. Default: self. Repeatable.",
    )
    ap.add_argument(
        "--state",
        choices=["pending", "completed", "error"],
        default=None,
        help="Filter by snapshot state.",
    )
    ap.add_argument("--started-after", default=None, help="StartTime >= this date (UTC), YYYY-MM-DD.")
    ap.add_argument("--started-before", default=None, help="StartTime < this date (UTC), YYYY-MM-DD.")
    ap.add_argument("--tag", action="append", default=[], help="Filter tag key=value (repeatable).")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of table.")
    ap.add_argument("--csv", default=None, help="Also write CSV to this path.")
    ap.add_argument("--fail-on-unhealthy", action="store_true", help="Exit 1 if any snapshot is unhealthy.")
    # New flags:
    ap.add_argument("--errors-only", action="store_true", help="Show only unhealthy snapshots.")
    ap.add_argument(
        "--show-error-details",
        action="store_true",
        help="Pretty-print detailed JSON for unhealthy snapshots to stderr.",
    )
    ap.add_argument("--errors-json", default=None, help="Write detailed JSON for unhealthy snapshots to this file.")
    args = ap.parse_args()

    # Session
    sess_kwargs = {}
    if args.profile:
        sess_kwargs["profile_name"] = args.profile
    try:
        sess = boto3.Session(region_name=args.region, **sess_kwargs)
        ec2 = sess.client("ec2")
    except Exception as e:
        print(f"[ERROR] Could not create AWS session/client: {e}", file=sys.stderr)
        sys.exit(2)

    started_after = parse_date(args.started_after)
    started_before = parse_date(args.started_before)
    tags = parse_kv(args.tag)

    try:
        snaps = fetch_snapshots(
            ec2=ec2,
            owners=args.owner,
            state=args.state,
            started_after=started_after,
            started_before=started_before,
            tag_eq=tags,
        )
    except ClientError as e:
        print(f"[ERROR] DescribeSnapshots failed: {e}", file=sys.stderr)
        sys.exit(2)

    # Partition by health
    unhealthy_raw = [s for s in snaps if not is_healthy(s)]
    healthy_raw = [s for s in snaps if is_healthy(s)]

    # Select which to show (FIXED: argparse uses underscore)
    show_raw = unhealthy_raw if args.errors_only else snaps
    rows = [row_from_snapshot(s) for s in show_raw]
    rows.sort(key=lambda r: r.get("StartTime", ""), reverse=True)  # newest first

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_table(rows)

    if args.csv:
        try:
            write_csv(rows, args.csv)
        except Exception as e:
            print(f"[WARN] Could not write CSV: {e}", file=sys.stderr)

    # Fancy details for errors
    if args.show_error_details or args.errors_json:
        detail = [detailed_from_snapshot(s) for s in unhealthy_raw]
        if args.show_error_details:
            print("\n=== Unhealthy Snapshot Details (JSON) ===", file=sys.stderr)
            print(json.dumps(detail, indent=2), file=sys.stderr)
        if args.errors_json:
            try:
                with open(args.errors_json, "w", encoding="utf-8") as f:
                    json.dump(detail, f, indent=2)
                print(f"Wrote error details to: {args.errors_json}", file=sys.stderr)
            except Exception as e:
                print(f"[WARN] Could not write errors JSON: {e}", file=sys.stderr)

    # Summary + exit code
    total = len(snaps)
    unhealthy = len(unhealthy_raw)
    by_state: Dict[str, int] = {}
    for s in snaps:
        st = s.get("State", "unknown")
        by_state[st] = by_state.get(st, 0) + 1

    print(f"\nSummary: total={total}  states={by_state}  unhealthy={unhealthy}", file=sys.stderr)

    if args.fail_on_unhealthy and unhealthy > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

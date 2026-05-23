#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
idc_check.py — Validate completeness of IDC (Identity Center) export
===================================================================

This helper verifies that a given IDC export directory contains all
artifacts required to rebuild AWS Identity Center from a total loss.

Expected layout:
  idc/<region>/
    identity-store/
      users.json
      groups.json
      group-memberships.json
    permission-sets/*.json
    assignments/*.json
    instance.json (optional)

It prints a concise summary and returns a dict that can be embedded
into orchestrator manifests.

Usage (stand-alone):
    python idc_check.py /path/to/idc/us-east-2
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Any


def _count_json(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(1 for p in folder.glob("*.json") if p.is_file())


def check_idc_completeness(region_root: Path, quiet: bool = False) -> Dict[str, Any]:
    identity_dir = region_root / "identity-store"
    users = identity_dir / "users.json"
    groups = identity_dir / "groups.json"
    memberships = identity_dir / "group-memberships.json"
    psets_dir = region_root / "permission-sets"
    assigns_dir = region_root / "assignments"
    instance_meta = region_root / "instance.json"

    present = {
        "users.json": users.exists(),
        "groups.json": groups.exists(),
        "group-memberships.json": memberships.exists(),
        "permission-sets/*.json": (psets_dir.exists() and _count_json(psets_dir) > 0),
        "assignments/*.json": (assigns_dir.exists() and _count_json(assigns_dir) > 0),
        "instance.json": instance_meta.exists(),
    }

    missing = [k for k, ok in present.items() if not ok and k != "instance.json"]
    ok = not missing

    # Load counts for human context
    try:
        u_count = len(json.loads(users.read_text()) if users.exists() else [])
    except Exception:
        u_count = 0
    try:
        g_count = len(json.loads(groups.read_text()) if groups.exists() else [])
    except Exception:
        g_count = 0
    summary = {
        "ok": ok,
        "present": present,
        "missing": missing,
        "counts": {
            "users": u_count,
            "groups": g_count,
            "permission_sets": _count_json(psets_dir),
            "assignments": _count_json(assigns_dir),
        },
    }

    if not quiet:
        print("-" * 78)
        print("IDC Completeness Check — required artifacts for full IDC recovery")
        print("-" * 78)
        for key, val in present.items():
            status = "OK " if val else "MISS"
            print(f"  {status:4} {key}")
        if missing:
            print("\n[WARN] Missing critical IDC artifacts:")
            for m in missing:
                print(f"   - {m}")
        print(f"\nCounts: users={u_count} groups={g_count} "
              f"permission-sets={summary['counts']['permission_sets']} "
              f"assignments={summary['counts']['assignments']}")
        print("-" * 78)

    return summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python idc_check.py /path/to/idc/<region>")
        sys.exit(2)
    root = Path(sys.argv[1]).expanduser().resolve()
    result = check_idc_completeness(root)
    print(json.dumps(result, indent=2))

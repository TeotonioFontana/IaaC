# -*- coding: utf-8 -*-
from __future__ import annotations
import sys, json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from ..utils import ensure_dir, load_config_file, run_cmd, file_exists
from ..utils import now_utc_iso, json_dump
from ..s3verify import verify_idc_tree_local_vs_s3

def _idc_completeness_check(idc_region_root: Path) -> Tuple[bool, Dict[str, Any]]:
    def _read_json(p: Path) -> dict:
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: return {}

    ident_dir = idc_region_root / "identity-store"
    ps_dir = ident_dir / "permission-sets"
    asg_dir = idc_region_root / "assignments"

    users_count = _read_json(ident_dir / "users.json").get("Count", 0)
    groups_count = _read_json(ident_dir / "groups.json").get("Count", 0)
    memberships_count = _read_json(ident_dir / "group-memberships.json").get("Count", 0)

    ps_index = _read_json(ps_dir / "index.json")
    ps_count = int(ps_index.get("Count", 0)) if ps_index else \
               sum(1 for p in ps_dir.glob("*.json") if p.name != "index.json")

    assignment_files = 0
    by_acct = asg_dir / "by-account"
    if by_acct.exists():
        for acct_dir in by_acct.iterdir():
            if acct_dir.is_dir():
                assignment_files += sum(1 for f in acct_dir.glob("*.json") if f.name != "_index.json")

    missing: List[str] = []
    if users_count == 0: missing.append("identity-store/users.json")
    if groups_count == 0: missing.append("identity-store/groups.json")
    if memberships_count == 0: missing.append("identity-store/group-memberships.json")
    if ps_count == 0: missing.append("identity-store/permission-sets/*.json")
    if assignment_files == 0: missing.append("assignments/*.json")

    summary = {
        "Result": "COMPLETE" if not missing else "INCOMPLETE",
        "Counts": {
            "users": users_count, "groups": groups_count,
            "group_memberships": memberships_count, "permission_sets": ps_count,
            "assignment_files": assignment_files,
        },
        "Missing": missing,
    }
    return (len(missing) == 0), summary

def run_phase_1_idc(args, scripts, tools_dir: Path, base_env: Dict[str,str]) -> bool:
    # paths
    idc_root = ensure_dir(Path(args.out_root).expanduser().resolve() / "idc" / args.source_region)
    idc_identity_dir = ensure_dir(idc_root / "identity-store")

    # sso_exporter
    sso_cmd = [sys.executable, str(scripts["sso_exporter"]),
               "--region", args.home_region, "--out-dir", str(idc_identity_dir)]
    sso_cfg_path = None
    if isinstance(getattr(args, "module_configs", {}), dict):
        sso_cfg_path = args.module_configs.get("sso_exporter")
        if sso_cfg_path: sso_cmd += ["--config", sso_cfg_path]
    if args.instance_arn: sso_cmd += ["--instance-arn", args.instance_arn]
    if args.identity_store_id: sso_cmd += ["--identity-store-id", args.identity_store_id]
    if args.assume:
        sso_cmd += ["--assume", args.assume]
        if args.assume_sts_region:
            sso_cmd += ["--assume-sts-region", args.assume_sts_region]

    for flag, attr in (("--s3-bucket","s3_bucket"),("--s3-prefix","s3_prefix"),
                       ("--s3-region","s3_region"),("--s3-storage-class","s3_storage_class"),
                       ("--s3-kms-key-id","s3_kms_key_id")):
        v = getattr(args, attr, None)
        if v: sso_cmd += [flag, str(v)]

    res = run_cmd("IDC Export (sso_exporter)", sso_cmd, tools_dir, base_env, args.preview, args.simulate)
    if not res.ok and not args.keep_going:
        return False

    # optional assignments exporter
    if "sso_assignments_exporter" in args.enabled_modules and file_exists(scripts["sso_assignments_exporter"]):
        ssoa_cmd = [sys.executable, str(scripts["sso_assignments_exporter"]),
                    "--region", args.home_region, "--out-dir", str(idc_root)]
        if isinstance(getattr(args, "module_configs", {}), dict):
            ssoa_cfg = args.module_configs.get("sso_assignments_exporter")
            if ssoa_cfg: ssoa_cmd += ["--config", ssoa_cfg]
        if args.instance_arn: ssoa_cmd += ["--instance-arn", args.instance_arn]
        if args.assume:
            ssoa_cmd += ["--assume", args.assume]
            if args.assume_sts_region:
                ssoa_cmd += ["--assume-sts-region", args.assume_sts_region]
        if args.preview: ssoa_cmd += ["--preview"]
        if args.simulate: ssoa_cmd += ["--simulate"]
        res2 = run_cmd("IDC Assignments Export (sso_assignments_exporter)", ssoa_cmd, tools_dir, base_env, args.preview, args.simulate)
        if not res2.ok and not args.keep_going:
            return False

    # completeness (local)
    ok_local, s_local = _idc_completeness_check(idc_root)
    print("-"*78); print("IDC Completeness Check — required artifacts for full IDC recovery"); print("-"*78)
    print(f"  Result ............. {s_local.get('Result')}")
    c = s_local.get("Counts", {})
    print(f"  Counts ............. users={c.get('users',0)} groups={c.get('groups',0)} "
          f"group-memberships={c.get('group_memberships',0)} permission-sets={c.get('permission_sets',0)} "
          f"assignment-files={c.get('assignment_files',0)}")
    miss = s_local.get("Missing", [])
    print(f"  Missing ............ {', '.join(miss) if miss else '(none)'}")
    print("-"*78)

    # S3 mirror verification if s3 config present
    s3_verified = True
    if sso_cfg_path:
        try: sso_cfg = load_config_file(sso_cfg_path)
        except Exception as e:
            sso_cfg = {}
            print(f"[WARN] Could not read sso_exporter config for S3 verification: {e}", file=sys.stderr)
        s3_bucket = (sso_cfg or {}).get("s3_bucket") or getattr(args, "s3_bucket", None)
        s3_prefix = (sso_cfg or {}).get("s3_prefix") or getattr(args, "s3_prefix", None)
        s3_region = (sso_cfg or {}).get("s3_region") or getattr(args, "s3_region", None) or args.home_region
        if s3_bucket:
            if args.preview or args.simulate:
                print("S3 Mirror Check ..... skipped (preview/simulate)")
            else:
                ok_s3, s3_summary = verify_idc_tree_local_vs_s3(str(idc_identity_dir), s3_bucket, s3_prefix, s3_region, args.profile)
                s3_verified = ok_s3
                status = "OK" if ok_s3 else "MISSING"
                miss = s3_summary.get("Missing", [])
                print(f"S3 Mirror Check ..... {status} (checked={s3_summary.get('Checked',0)}/{s3_summary.get('Expected',0)} in s3://{s3_summary.get('Bucket')}/{s3_summary.get('Prefix','')})")
                if miss:
                    sample = '; '.join(miss[:5]); more = ' ...' if len(miss)>5 else ''
                    print(f"  Missing keys ...... {len(miss)} (e.g., {sample}{more})")
                print("-"*78)

    return (ok_local and s3_verified) or args.keep_going

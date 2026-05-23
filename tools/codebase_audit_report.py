#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 codebase_audit_report.py — v1.0.4
===============================================================================
 Purpose............: Scan the iaactools/codebase folder to detect misplaced,
                      orphaned, and redundant files for manual cleanup.
 Author.............: Duke (GPT-5, OpenAI)
-------------------------------------------------------------------------------
 Output.............: /Users/teotonio/Projetos/IaaC/iaactools/codebase/codebase_audit_report.txt
===============================================================================
"""

import os
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical structure
# ---------------------------------------------------------------------------
VALID_PACKAGES = {
    "backup_orchestrator_pkg",
    "ebs_backup_pkg",
    "recovery_audit_pkg",
    "json_schemas",
    "utils",
    "recovery_orchestrator",
    "results",
    "archive",
    "docs",
}

# Valid operational entry points (root commands)
ROOT_COMMANDS = {
    "backup_orchestrator.py",
    "ebs_backup.py",
    "recover_volume.py",
    "sso_exporter.py",
    "sso_apply.py",
    "snap_status.py",
    "kms_key_inspect.py",
    "cfn_exporter.py",
    "cfn_splitter.py",
    "ami_build.py",
    "idc_check.py",
    "iaac_cf.transform.py",
}

CODE_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".md"}
JUNK_EXTENSIONS = {".zip", ".bak"}
JUNK_FILENAMES = {".DS_Store", "__pycache__"}

# Fixed report output path
REPORT_FILE = Path("/Users/teotonio/Projetos/IaaC/iaactools/codebase/codebase_audit_report.txt")


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------
def scan_codebase(root: Path):
    misplaced, orphan, redundant = [], [], []

    for dirpath, _, filenames in os.walk(root):
        dirpath = Path(dirpath)
        if "__pycache__" in dirpath.parts:
            continue

        for file in filenames:
            fpath = dirpath / file
            ext = fpath.suffix.lower()

            # Redundant / garbage
            if ext in JUNK_EXTENSIONS or file in JUNK_FILENAMES:
                redundant.append(fpath)
                continue

            # Inside valid package?
            if any(pkg in dirpath.parts for pkg in VALID_PACKAGES):
                continue

            # Root-level command?
            elif file in ROOT_COMMANDS:
                continue

            # Otherwise classify
            if ext in CODE_EXTENSIONS:
                orphan.append(fpath)
            else:
                misplaced.append(fpath)

    return misplaced, orphan, redundant


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Audit codebase structure for misplaced or orphaned files.")
    parser.add_argument("--show-summary", action="store_true", help="Print summary of findings to stdout.")
    args = parser.parse_args()

    root = Path("/Users/teotonio/Projetos/IaaC/iaactools/codebase")
    if not root.exists():
        raise SystemExit(f"[FATAL] Cannot locate codebase directory: {root}")

    misplaced, orphan, redundant = scan_codebase(root)

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_FILE.open("w", encoding="utf-8") as f:
        f.write("============================================================\n")
        f.write(" CODEBASE AUDIT REPORT — v1.0.4\n")
        f.write("============================================================\n\n")

        f.write("[1] MISPLACED FILES (outside expected package hierarchy)\n")
        f.write("------------------------------------------------------------\n")
        if misplaced:
            for path in misplaced:
                f.write(f"{path}\n")
        else:
            f.write("✅ None detected.\n")
        f.write("\n")

        f.write("[2] ORPHAN FILES (code/scripts not under a package)\n")
        f.write("------------------------------------------------------------\n")
        if orphan:
            for path in orphan:
                f.write(f"{path}\n")
        else:
            f.write("✅ None detected.\n")
        f.write("\n")

        f.write("[3] REDUNDANT FILES (archives, backups, DS_Store)\n")
        f.write("------------------------------------------------------------\n")
        if redundant:
            for path in redundant:
                f.write(f"{path}\n")
        else:
            f.write("✅ None detected.\n")

    if args.show_summary:
        print("============================================================")
        print(" CODEBASE AUDIT SUMMARY — v1.0.4")
        print("============================================================")
        print(f"Misplaced files: {len(misplaced)}")
        print(f"Orphan files   : {len(orphan)}")
        print(f"Redundant files: {len(redundant)}")
        print("------------------------------------------------------------")
        print(f"Full report written to: {REPORT_FILE}\n")

    else:
        print(f"\n[OK] Codebase audit completed.\nReport written to:\n{REPORT_FILE}\n")


if __name__ == "__main__":
    main()

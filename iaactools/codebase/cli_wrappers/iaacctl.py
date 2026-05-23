# -*- coding: utf-8 -*-
"""
===============================================================================
 iaacctl.py — Unified CLI Wrapper for IaaC Tools
===============================================================================
 Version.............: v0.3.0
 Author..............: Teotoniio Fontana — Architect
 Programmed by.......: Duke (GPT-5, OpenAI)
 Project.............: IaaC Tools / Unified Command Interface
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 A unified Python CLI wrapper replacing multiple shell scripts used to launch
 backup, audit, and CloudFormation utilities. Provides consistent parameter
 handling, colorized logging, and optional dry-run execution.
===============================================================================
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

# -----------------------------------------------------------------------------
# ANSI Colors
# -----------------------------------------------------------------------------
ANSI = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "RED": "\033[31m",
    "CYAN": "\033[36m",
    "GRAY": "\033[90m",
}


def color(text, col):
    """Return colorized text."""
    return f"{ANSI.get(col, '')}{text}{ANSI['RESET']}"


# -----------------------------------------------------------------------------
# Command Mapping
# -----------------------------------------------------------------------------
COMMANDS = {
    "backup": "iaactools.codebase.backup_orchestrator_pkg.orchestrator",
    "audit": "iaactools.codebase.recovery_audit_pkg.orchestrator",
    "cfn-export": "iaactools.codebase.cfn_exporter",
    "cfn-split": "iaactools.codebase.cfn_splitter",
    "sso-export": "iaactools.codebase.sso_exporter",
}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def run_python_module(module: str, args: list, dry_run: bool = False) -> int:
    """Execute a Python module with provided arguments."""
    cmd = [sys.executable, "-m", module] + args
    if dry_run:
        print(color("[DRY-RUN]", "YELLOW"), " ".join(cmd))
        return 0
    print(color("→ Executing:", "CYAN"), " ".join(cmd))
    return subprocess.call(cmd)


def ensure_env(profile: str, region: str):
    """Ensure AWS environment variables are exported."""
    os.environ["AWS_PROFILE"] = profile
    os.environ["AWS_REGION"] = region


def ensure_results_dir():
    """Ensure results/logs folder exists."""
    results_dir = Path.cwd() / "results" / "logs"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir


def log_summary(results_dir: Path, command: str, code: int):
    """Write minimal log summary."""
    log_path = results_dir / f"{command}.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"Command={command} ExitCode={code}\n")
    print(color(f"Log written to {log_path}", "GRAY"))


# -----------------------------------------------------------------------------
# CLI Entry
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        prog="iaacctl",
        description=(
            "Unified command-line interface for all IaacTools components.\n"
            "Each subcommand wraps a dedicated orchestrator or utility module,\n"
            "ensuring consistent execution and logging.\n\n"
            "Available subcommands:\n"
            "  backup       → Run the full backup orchestrator (EBS, snapshots, manifests)\n"
            "  audit        → Verify backup integrity and generate PDF/JSON reports\n"
            "  cfn-export   → Export CloudFormation stacks as YAML templates\n"
            "  cfn-split    → Split monolithic CloudFormation into layered files\n"
            "  sso-export   → Export AWS SSO / Identity Center users and assignments\n\n"
            "Examples:\n"
            "  iaacctl backup --config conf/orchestrator/orchestrator-execute.yaml\n"
            "  iaacctl audit  --config conf/audit/audit-default.yaml --run-id 2025-11-05T21:00Z\n"
            "  iaacctl cfn-export --config conf/cloudformation/export-default.yaml\n"
            "  iaacctl cfn-split  --config conf/cloudformation/split-default.yaml\n"
            "  iaacctl sso-export --config conf/sso/export-default.yaml --dry-run"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "command",
        choices=COMMANDS.keys(),
        help="Subcommand to run (type one of: backup, audit, cfn-export, cfn-split, sso-export)",
    )
    parser.add_argument("--config", required=True, help="Path to YAML/JSON configuration file")
    parser.add_argument("--run-id", help="Execution run identifier (ISO UTC format recommended)")
    parser.add_argument("--profile", default="default", help="AWS CLI profile name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--dry-run", action="store_true", help="Preview commands without executing")

    args, extras = parser.parse_known_args()

    ensure_env(args.profile, args.region)
    results_dir = ensure_results_dir()

    print(color(f"\nIaacTools Control CLI — {args.command.upper()} Mode", "BOLD"))
    print(color(f"Profile: {args.profile} | Region: {args.region}", "CYAN"))
    print(color(f"Config: {args.config}", "CYAN"))
    if args.run_id:
        print(color(f"Run ID: {args.run_id}", "CYAN"))

    module = COMMANDS.get(args.command)
    if not module:
        print(color("[FATAL] Invalid command.", "RED"))
        sys.exit(1)

    cmd_args = ["--config", args.config]
    if args.run_id:
        cmd_args += ["--run-id", args.run_id]

    if args.dry_run:
        print(color("[DRY-RUN MODE ENABLED]", "YELLOW"))

    code = run_python_module(module, cmd_args + extras, dry_run=args.dry_run)

    log_summary(results_dir, args.command, code)
    print(
        color(
            f"\n{args.command.upper()} completed with code {code}",
            "GREEN" if code == 0 else "RED",
        )
    )
    sys.exit(code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(color("\n[ABORTED] Interrupted by user.", "RED"))
        sys.exit(130)

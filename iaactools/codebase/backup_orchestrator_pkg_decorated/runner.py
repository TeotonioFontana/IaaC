#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 runner.py — v4.0.0-alpha1
===============================================================================
 Purpose............: CLI wrapper to execute the Backup Orchestrator.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 This script serves as a top-level entrypoint for debugging and testing the
 backup orchestration pipeline. It wraps orchestrator.main() and exposes
 command-line arguments that override config values when provided.
===============================================================================
"""
from backup_orchestrator_pkg.result_envelope import enveloped

import sys
import traceback
import argparse
from pathlib import Path
from . import orchestrator


def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="IaacTools Backup Orchestrator Runner"
    )
    parser.add_argument(
        "--config", required=True, help="Path to backup configuration YAML/JSON file."
    )
    parser.add_argument(
        "--run-id", required=True, help="Unique run identifier (e.g., 20251105T180000Z)."
    )
    parser.add_argument(
        "--simulate", action="store_true", help="Run in simulation mode (no AWS writes)."
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug-level logging."
    )
    parser.add_argument(
        "--stop-on-error", action="store_true", help="Abort pipeline if any phase fails."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.config)

    # Defensive existence check
    if not config_path.exists():
        sys.exit(f"[FATAL] Config file not found: {config_path}")

    # Dynamically patch arguments into orchestrator’s config system
    try:
        print("=" * 79)
        print("IaacTools — Backup Orchestrator (v4.0.0-alpha1)")
        print(f"Config: {config_path}")
        print(f"Run ID: {args.run_id}")
        print(f"Mode: {'SIMULATION' if args.simulate else 'LIVE'}")
        print("=" * 79)

        # Pass overrides through to orchestrator
        result = orchestrator.main(
            config_path=config_path,
            run_id=args.run_id,
            simulate=args.simulate,
            verbose=args.verbose,
            stop_on_error=args.stop_on_error,
        )

        print("\n[OK] Orchestration completed successfully.")
        print(f"Results saved under: {result.get('ResultsDir', '(unknown)')}")
        return 0

    except KeyboardInterrupt:
        print("\n[ABORTED] User interrupted execution.")
        return 2
    except Exception as e:
        print(f"\n[FATAL] Orchestrator execution failed: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

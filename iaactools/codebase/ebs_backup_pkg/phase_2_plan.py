#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phase_2_plan.py — Phase 2: Plan
===============================

Computes aggregate volume metrics (total GiB/TiB) and confirms backup scope.

FATAL error handling:
- Clean message with line number and file name.
- No traceback spam.

Logging policy:
- Phase header and summary at INFO level.
- Detailed volume breakdown at DEBUG level.
"""

import sys
import time
import re
from typing import List, Dict, Any

from .utils import secs_since, log_step
from .logging_utils import log_phase_header

# ---------------------------------------------------------------------------
# Helper: recursive numeric sanitization
# ---------------------------------------------------------------------------
_NUMERIC_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")

def _sanitize_numeric(obj):
    """Recursively coerce numeric-like strings into int or float."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str) and _NUMERIC_PATTERN.match(v.strip()):
                try:
                    obj[k] = float(v) if "." in v else int(v)
                except ValueError:
                    pass
            elif isinstance(v, (dict, list)):
                _sanitize_numeric(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and _NUMERIC_PATTERN.match(v.strip()):
                try:
                    obj[i] = float(v) if "." in v else int(v)
                except ValueError:
                    pass
            elif isinstance(v, (dict, list)):
                _sanitize_numeric(v)
    return obj


# ---------------------------------------------------------------------------
# Main function: PLAN phase
# ---------------------------------------------------------------------------
def run_plan(args, discovered: Dict[str, Any], logger):
    """
    Phase 2 — Plan backup workload.
    Returns a dictionary with total size and volume count.
    """
    try:
        log_phase_header(logger, 2, 5, "PLAN", "phase_2_plan")
        t0 = time.time()

        # -------------------------------------------------------------------
        # Extract volumes list from previous phase result
        # -------------------------------------------------------------------
        volumes = discovered.get("volumes") or discovered.get("Volumes") or discovered
        if not isinstance(volumes, list):
            raise TypeError("Expected list of volumes from discovery phase")

        # -------------------------------------------------------------------
        # Sanitize all volumes
        # -------------------------------------------------------------------
        for v in volumes:
            _sanitize_numeric(v)
            for k in ("Size", "Iops", "Throughput"):
                if k in v and isinstance(v[k], str):
                    try:
                        v[k] = int(v[k])
                    except ValueError:
                        v[k] = 0

        # -------------------------------------------------------------------
        # Compute totals
        # -------------------------------------------------------------------
        total_gib = 0
        for v in volumes:
            size = v.get("Size", 0)
            try:
                size = int(size)
            except (TypeError, ValueError):
                size = 0
            total_gib += size

        total_tib = round(total_gib / 1024.0, 3)

        log_step(
            logger,
            "PLAN",
            "SIZE",
            TotalVolumes=len(volumes),
            TotalSizeGiB=total_gib,
            TotalSizeTiB=total_tib,
            Note="EBS snapshot storage is incremental; shown value is raw attached capacity.",
        )

        logger.info(
            "Planned backup size: %d volumes, ~%.3f TiB total.",
            len(volumes),
            total_tib,
        )

        log_step(logger, "PLAN", "END", ElapsedSec=secs_since(t0))
        logger.info("Phase 2 complete: backup plan ready.")

        return {
            "volumes": volumes,
            "TotalVolumes": len(volumes),
            "TotalSizeGiB": total_gib,
            "TotalSizeTiB": total_tib,
        }

    except Exception as e:
        exc_type, _, exc_tb = sys.exc_info()
        lineno = exc_tb.tb_lineno if exc_tb else "(unknown)"
        filename = exc_tb.tb_frame.f_code.co_filename if exc_tb else "(unknown)"
        logger.error(
            f"[FATAL] Unexpected error: {e} (line {lineno} in {filename})",
            exc_info=False,
        )
        raise SystemExit(1)

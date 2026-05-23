#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
phase_1_discover.py — Phase 1: Discover
=======================================

Enumerates all EBS volumes in the source region, applies state and tag filters,
and optionally inspects attached instances via AWS SSM.

FATAL error handling:
- Clean message with line number and file name.
- No traceback spam.

Logging policy:
- Phase header and progress at INFO level.
- Detailed per-volume/instance data only under DEBUG.
"""

import sys
import time
import re
import logging
from typing import Dict, List, Any
import boto3
from botocore.exceptions import ClientError

from .utils import utc_iso, secs_since, flatten_tags, log_step
from .discovery import (
    load_instance_name_map,
    describe_volumes,
    ssm_collect_lsblk,
    log_discovery_items,
)
from .logging_utils import log_phase_header, summarize_list


# ---------------------------------------------------------------------------
# Helper: recursive numeric sanitization
# ---------------------------------------------------------------------------
_NUMERIC_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")


def _sanitize_numeric(obj):
    """
    Recursively coerce numeric-like strings into int or float.
    Skips non-numeric values like 'gp3', 'standard', etc.
    """
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
# Main function: DISCOVER phase
# ---------------------------------------------------------------------------
def run_discover(args, logger):
    """
    Phase 1 — Discover EBS volumes.
    Returns a dictionary with keys:
        - volumes
        - ssm_map
        - inst_name_map
    """
    try:
        # -------------------------------------------------------------------
        # Phase header
        # -------------------------------------------------------------------
        log_phase_header(logger, 1, 5, "DISCOVER", "phase_1_discover")
        t0 = time.time()

        # -------------------------------------------------------------------
        # AWS EC2 client
        # -------------------------------------------------------------------
        session_kwargs = {}
        if args.profile:
            session_kwargs["profile_name"] = args.profile
        ec2 = boto3.Session(region_name=args.src_region, **session_kwargs).client("ec2")

        # -------------------------------------------------------------------
        # Build state and tag filters
        # -------------------------------------------------------------------
        include_states = [s.strip() for s in args.states.split(",") if s.strip()]
        vol_tag_filters: Dict[str, str] = {}
        for kv in args.filter_tag:
            if "=" not in kv:
                raise SystemExit(f"--filter-tag expects key=value, got: {kv}")
            k, v = kv.split("=", 1)
            vol_tag_filters[k] = v

        # -------------------------------------------------------------------
        # Discover volumes
        # -------------------------------------------------------------------
        log_step(logger, "DISCOVER", "START", States=include_states)
        try:
            volumes = describe_volumes(ec2, include_states, logger=logger)
        except ClientError as e:
            logger.error("[FATAL] EC2 DescribeVolumes failed: %s", e)
            raise

        # -------------------------------------------------------------------
        # Sanitize AWS data (ensure numeric and list types, deep)
        # -------------------------------------------------------------------
        for v in volumes:
            _sanitize_numeric(v)
            for k in ("Size", "Iops", "Throughput"):
                if k in v and isinstance(v[k], str):
                    try:
                        v[k] = int(v[k])
                    except ValueError:
                        v[k] = 0
            if not isinstance(v.get("Tags"), list):
                v["Tags"] = []
            if not isinstance(v.get("Attachments"), list):
                v["Attachments"] = []

        log_step(logger, "DISCOVER", "FOUND", Count=len(volumes), ElapsedSec=secs_since(t0))

        # -------------------------------------------------------------------
        # Apply tag filtering
        # -------------------------------------------------------------------
        if vol_tag_filters:
            def _match(vol: dict) -> bool:
                tags = flatten_tags(vol.get("Tags"))
                return all(tags.get(k) == v for k, v in vol_tag_filters.items())

            pre_len = len(volumes)
            volumes = [v for v in volumes if _match(v)]
            log_step(
                logger,
                "DISCOVER",
                "FILTER",
                FilterTags=vol_tag_filters,
                Before=pre_len,
                After=len(volumes),
            )

        # -------------------------------------------------------------------
        # Canonical discovery line (for orchestrator parsing)
        # -------------------------------------------------------------------
        attached = sum(1 for v in volumes if str(v.get("State")) == "in-use")
        available = sum(1 for v in volumes if str(v.get("State")) == "available")
        logger.info(
            "[DISCOVERY] volumes=%d attached=%d available=%d",
            len(volumes),
            attached,
            available,
        )

        if not volumes:
            log_step(logger, "DISCOVER", "EMPTY", Message="No volumes matched filters/states")
            logger.warning("No volumes to back up.")
            return {"volumes": [], "ssm_map": {}, "inst_name_map": {}}

        # -------------------------------------------------------------------
        # Instance map
        # -------------------------------------------------------------------
        inst_name_map = load_instance_name_map(ec2)
        logger.debug("Loaded instance name map for %d entries", len(inst_name_map))

        # -------------------------------------------------------------------
        # Optional SSM inspection
        # -------------------------------------------------------------------
        ssm_map: Dict[str, dict] = {}
        if args.ssm_inspect and not args.preview:
            attached_instance_ids = sorted(
                {
                    att.get("InstanceId")
                    for v in volumes
                    for att in v.get("Attachments", []) or []
                    if att.get("InstanceId")
                }
            )
            if attached_instance_ids:
                from .utils import confirm_phase
                confirm_phase(
                    args,
                    logger,
                    question=f"Run SSM mount inspection on {len(attached_instance_ids)} attached instances?",
                    abort_reason="Cancelled by user at SSM INSPECT phase.",
                )
                ssm_map, _ = ssm_collect_lsblk(
                    boto3.Session(region_name=args.src_region, **session_kwargs).client("ssm"),
                    attached_instance_ids,
                    logger,
                )
            else:
                log_step(
                    logger,
                    "ALERT",
                    "SSM_SKIPPED",
                    Message="No attached instances found; --ssm-inspect has nothing to inspect.",
                )

        # -------------------------------------------------------------------
        # Discovery log
        # -------------------------------------------------------------------
        log_discovery_items(
            logger,
            volumes,
            inst_name_map,
            ssm_map if (args.ssm_inspect and not args.preview) else None,
            compact=not logger.isEnabledFor(logging.DEBUG),
        )

        # Compact summary at INFO level
        summarize_list(logger, volumes, "Discovered volumes")
        if ssm_map:
            summarize_list(logger, ssm_map.keys(), "Instances inspected via SSM")

        log_step(logger, "DISCOVER", "END", Count=len(volumes), ElapsedSec=secs_since(t0))
        logger.info("Phase 1 complete: %d volume(s) discovered.", len(volumes))

        # -------------------------------------------------------------------
        # Canonical return structure
        # -------------------------------------------------------------------
        return {
            "volumes": volumes,
            "ssm_map": ssm_map,
            "inst_name_map": inst_name_map,
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

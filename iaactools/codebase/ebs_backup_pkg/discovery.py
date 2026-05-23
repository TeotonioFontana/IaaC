#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
discovery.py — EBS discovery utilities
=====================================

Provides safe and consistent functions to query AWS EC2 for EBS volumes,
attached instances, and optional SSM inspection data.

Patched version:
- Sanitizes filter values before paginator call.
- Converts numeric-like strings (e.g. "3000") to numbers.
- Catches and reports paginator errors without raw stack traces.
"""

import re
import sys
import boto3
from botocore.exceptions import ClientError

from .utils import log_step

# ---------------------------------------------------------------------------
# Internal numeric sanitizer
# ---------------------------------------------------------------------------
_NUMERIC_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")


def _sanitize_numeric(obj):
    """
    Recursively coerce numeric-like strings into int or float.
    Skips non-numeric strings such as 'gp3', 'standard', etc.
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
# EC2 volume discovery
# ---------------------------------------------------------------------------
def describe_volumes(ec2, include_states=None, logger=None):
    """
    Describe EBS volumes in the target region.
    Ensures all filters are properly stringified and numeric fields are sanitized.
    """
    filters = []
    if include_states:
        filters.append({
            "Name": "status",
            "Values": [str(s).strip() for s in include_states if s]
        })

    try:
        paginator = ec2.get_paginator("describe_volumes")
        volumes = []
        for page in paginator.paginate(Filters=filters):
            for vol in page.get("Volumes", []):
                _sanitize_numeric(vol)
                volumes.append(vol)
        return volumes

    except ClientError as e:
        msg = f"[FATAL] EC2 DescribeVolumes failed: {e}"
        if logger:
            logger.error(msg)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    except TypeError as e:
        msg = f"[FATAL] EC2 describe_volumes() type error: {e}"
        if logger:
            logger.error(msg)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        msg = f"[FATAL] Unexpected describe_volumes() error: {e}"
        if logger:
            logger.error(msg)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Instance name mapping
# ---------------------------------------------------------------------------
def load_instance_name_map(ec2):
    """Return a dict mapping InstanceId → Name tag."""
    paginator = ec2.get_paginator("describe_instances")
    result = {}
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                name = None
                for tag in instance.get("Tags", []):
                    if tag.get("Key") == "Name":
                        name = tag.get("Value")
                        break
                result[instance["InstanceId"]] = name or "(unnamed)"
    return result


# ---------------------------------------------------------------------------
# Optional SSM inspection
# ---------------------------------------------------------------------------
def ssm_collect_lsblk(ssm_client, instance_ids, logger=None):
    """
    Collects 'lsblk' output from attached instances via AWS SSM.
    Returns (ssm_map, failed_instances)
    """
    ssm_map = {}
    failed = []
    command = "lsblk -J -o NAME,MOUNTPOINT,SIZE,TYPE"
    try:
        resp = ssm_client.send_command(
            InstanceIds=instance_ids,
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command]},
            TimeoutSeconds=30,
        )
        command_id = resp["Command"]["CommandId"]
        for iid in instance_ids:
            try:
                out = ssm_client.get_command_invocation(
                    CommandId=command_id, InstanceId=iid
                )
                if out["Status"] == "Success":
                    ssm_map[iid] = out["StandardOutputContent"]
                else:
                    failed.append(iid)
            except Exception:
                failed.append(iid)
    except ClientError as e:
        msg = f"[FATAL] SSM command failed: {e}"
        if logger:
            logger.error(msg)
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)
    return ssm_map, failed


# ---------------------------------------------------------------------------
# Discovery item logger (optional detailed log)
# ---------------------------------------------------------------------------
def log_discovery_items(logger, volumes, inst_name_map, ssm_map=None, compact=True):
    """
    Logs discovered volume info.
    - compact=True → summarize volume name, instance, device.
    - compact=False → full JSON-like detail.
    """
    for v in volumes:
        vol_id = v.get("VolumeId")
        state = v.get("State")
        name = "(unnamed)"
        for t in v.get("Tags", []):
            if t.get("Key") == "Name":
                name = t.get("Value")
                break

        attachments = v.get("Attachments", []) or []
        if compact:
            if attachments:
                for att in attachments:
                    inst_id = att.get("InstanceId")
                    inst_name = inst_name_map.get(inst_id, "(unknown)")
                    device = att.get("Device")
                    logger.info(
                        "[DISCOVER] %s attached to %s (%s) at %s",
                        name, inst_name, inst_id, device
                    )
            else:
                logger.info("[DISCOVER] %s — available (no attachments)", name)
        else:
            logger.debug("DISCOVER:ITEM | %s", v)

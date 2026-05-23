# -*- coding: utf-8 -*-
"""
===============================================================================
 discovery.py — AWS EC2 Discovery Helpers for IaacTools Backup Orchestrator
===============================================================================
 Version.............: v0.6.0
 Author..............: Teotoniio Fontana — Architect
 Programmed by.......: Duke (GPT-5, OpenAI)
 Project.............: IaaC Tools / Backup Orchestration
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides EC2 volume and instance discovery utilities used during backup
 orchestration. These helpers collect metadata, volume details, and instance
 name tags for audit logging and manifest generation.
===============================================================================
"""

import boto3
from botocore.exceptions import ClientError
from typing import Dict, List
from iaactools.codebase.utils.logger_utils import log_phase_status


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def load_instance_name_map(ec2_client) -> Dict[str, str]:
    """
    Return a dictionary mapping InstanceId -> Name tag.
    """
    mapping = {}
    try:
        response = ec2_client.describe_instances()
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                instance_id = instance["InstanceId"]
                name_tag = next(
                    (tag["Value"] for tag in instance.get("Tags", []) if tag["Key"] == "Name"),
                    "Unnamed"
                )
                mapping[instance_id] = name_tag
    except ClientError as e:
        raise RuntimeError(f"Error describing instances: {e}")
    return mapping


def describe_volumes(ec2_client) -> List[Dict]:
    """
    Return a list of EBS volumes with their key metadata.
    """
    try:
        response = ec2_client.describe_volumes()
        return response["Volumes"]
    except ClientError as e:
        raise RuntimeError(f"Error describing volumes: {e}")


def ssm_collect_lsblk(ssm_client, instance_id: str) -> Dict:
    """
    Placeholder for SSM lsblk collector.
    Currently returns an empty dict — to be implemented later.
    """
    return {"InstanceId": instance_id, "Devices": []}


def log_discovery_items(logger, instances: Dict[str, str], volumes: List[Dict]) -> None:
    """
    Log basic discovery summary for debugging and audits.
    """
    log_phase_status(logger, "Discovery", "SUCCESS", f"Instances={len(instances)} Volumes={len(volumes)}")
    for iid, name in instances.items():
        logger.info(f"Instance {iid} — Name: {name}")
    for v in volumes:
        logger.info(f"Volume {v.get('VolumeId')} — Size={v.get('Size')}GiB State={v.get('State')}")

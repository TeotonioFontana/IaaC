#!/usr/bin/env python3
"""Reconcile the AWS-managed portion of the SPServices FastAPI host.

Host mounts and systemd units remain deployment concerns and are documented in
the adjacent runbook. This program deliberately manages only idempotent AWS API
resources. Run without ``--apply`` to print the intended operations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3
import yaml


ROOT = Path(__file__).resolve().parent


def load_state() -> dict:
    return yaml.safe_load((ROOT / "desired_state.yaml").read_text())


def alarm_name(slug: str, threshold: dict) -> str:
    return f"SPServices-{slug}-disk-{threshold['name']}-{threshold['percent']}"


def desired_alarms(state: dict) -> list[dict]:
    monitoring = state["monitoring"]
    instance_id = state["instance_id"]
    alarms = []
    for filesystem in state["storage"]["filesystems"]:
        for threshold in monitoring["thresholds"]:
            alarms.append({
                "AlarmName": alarm_name(filesystem["slug"], threshold),
                "AlarmDescription": (
                    f"{filesystem['path']} disk usage is at least "
                    f"{threshold['percent']}% on {instance_id}."
                ),
                "ActionsEnabled": True,
                "AlarmActions": [monitoring["topic_arn"]],
                "OKActions": [monitoring["topic_arn"]],
                "MetricName": "disk_used_percent",
                "Namespace": monitoring["namespace"],
                "Statistic": "Average",
                "Dimensions": [
                    {"Name": "InstanceId", "Value": instance_id},
                    {"Name": "path", "Value": filesystem["path"]},
                    {"Name": "fstype", "Value": "ext4"},
                ],
                "Period": threshold["period"],
                "EvaluationPeriods": threshold["evaluation_periods"],
                "DatapointsToAlarm": threshold["datapoints_to_alarm"],
                "Threshold": threshold["percent"],
                "ComparisonOperator": "GreaterThanOrEqualToThreshold",
                "TreatMissingData": "missing",
            })
    return alarms


def reconcile(state: dict, apply: bool) -> None:
    region = state["region"]
    ec2 = boto3.client("ec2", region_name=region)
    cloudwatch = boto3.client("cloudwatch", region_name=region)
    iam = boto3.client("iam")
    sns = boto3.client("sns", region_name=region)

    operations = []
    if state["storage"]["encryption_by_default"]:
        current = ec2.get_ebs_encryption_by_default()["EbsEncryptionByDefault"]
        if not current:
            operations.append("enable EBS encryption by default")
            if apply:
                ec2.enable_ebs_encryption_by_default()

    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublishSPServicesHostMetrics",
            "Effect": "Allow",
            "Action": "cloudwatch:PutMetricData",
            "Resource": "*",
            "Condition": {
                "StringEquals": {
                    "cloudwatch:namespace": state["monitoring"]["namespace"]
                }
            },
        }],
    }
    operations.append("reconcile instance-role metric publishing policy")
    if apply:
        iam.put_role_policy(
            RoleName=state["instance_role"],
            PolicyName="SPServicesDiskMetrics",
            PolicyDocument=json.dumps(policy),
        )

    subscriptions = sns.list_subscriptions_by_topic(
        TopicArn=state["monitoring"]["topic_arn"]
    )["Subscriptions"]
    endpoint = state["monitoring"]["notification_email"]
    if not any(item.get("Endpoint") == endpoint for item in subscriptions):
        operations.append(f"request SNS email subscription for {endpoint}")
        if apply:
            sns.subscribe(
                TopicArn=state["monitoring"]["topic_arn"],
                Protocol="email",
                Endpoint=endpoint,
            )

    for alarm in desired_alarms(state):
        operations.append(f"reconcile alarm {alarm['AlarmName']}")
        if apply:
            cloudwatch.put_metric_alarm(**alarm)

    snapshot_state = state["temporary_snapshots"]
    tags = [
        {"Key": "ManagedBy", "Value": "IaaC"},
        {"Key": "RetentionClass", "Value": snapshot_state["retention_class"]},
        {"Key": "DeleteAfter", "Value": snapshot_state["delete_after"]},
    ]
    operations.append(f"tag {len(snapshot_state['ids'])} temporary snapshots")
    if apply:
        ec2.create_tags(Resources=snapshot_state["ids"], Tags=tags)

    print("\n".join(operations) or "AWS state is already reconciled.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    reconcile(load_state(), args.apply)


if __name__ == "__main__":
    main()


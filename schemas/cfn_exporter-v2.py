#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfn_exporter.py — Human‑friendly, results‑aware CloudFormation exporter (v0.2)
==============================================================================

WHAT’S NEW (v0.2)
-----------------
• Safer NAT route export: correctly references exported NAT Gateways (no more ad‑hoc sanitize mismatch).
• Optional region prefixing of logical IDs to avoid cross‑region collisions.
• Export metadata (AccountId, Regions, Timestamp) in `Metadata` for traceability.
• CLI enhancements:
  - --profile to pin an AWS named profile
  - --assume-role-arn (and --external-id) to export from another account
  - --regions behaves like before but is required for multi‑region; defaults to current session region
  - --no-network / --no-security / --no-compute to skip categories
  - --vpc-ids and --instance-ids to scope the export
  - --prefix-region to add a region prefix to all logical IDs (useful for multi‑region export into *one* file)
• Robust retries via botocore Config; consistent results folder usage.

Goal
----
Snapshot a subset of your AWS infrastructure and emit a **single** CloudFormation
template (YAML) you can later **split** into layered stacks and re‑deploy in a
fresh account (e.g., before enabling **SCPs**).

What it captures (v0.2)
-----------------------
Network:
  • VPCs, Subnets, Route Tables + Associations
  • Internet Gateways, NAT Gateways (+ single EIP reference), Elastic IPs
Security:
  • Security Groups (ingress/egress), tags preserved
Compute:
  • EC2 Instances (ImageId, InstanceType, KeyName, Subnet/SGs, basic EBS, tags)

Out of scope (add later or by hand)
-----------------------------------
  • IAM (Roles/Policies/InstanceProfiles), S3, RDS, ALB/NLB, Route53, ACM,
    Lambda, ASGs/LaunchTemplates, EKS/ECS, etc.
  • AMI portability: we **copy AMI IDs**; consider swapping to **SSM Parameter**
    lookups (`/aws/service/ami-amazon-linux-latest/...`) when redeploying.

Safety
------
  • Read‑only: recommend the AWS managed policy **ReadOnlyAccess** or the minimal
    policy in `cfn_exporter_readonly.json`.
  • No deletes, no changes to your infra.

Results directory
-----------------
All artifacts are written under **./results** so PyCharm/CI stays clean.

Quick start
-----------
```bash
python -m venv .venv && source .venv/bin/activate
pip install boto3 pyyaml
aws configure  # or set AWS_PROFILE/AWS_DEFAULT_REGION

python cfn_exporter.py \
  --stack-name ProdExport \
  --output exported_stack.yaml \
  --regions us-east-1 sa-east-1 \
  --prefix-region
# => ./results/exported_stack.yaml
```

License: MIT
Author: Duke (IaaC)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.credentials import RefreshableCredentials
from botocore.session import get_session

try:
    import yaml  # type: ignore
except Exception:
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

RESULTS_DIR = Path("./results")  # project-local results dir (PyCharm-friendly)


def ensure_results_dir() -> None:
    """Create the ./results folder if it doesn't exist."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def boto_session(region: Optional[str] = None, profile: Optional[str] = None) -> boto3.session.Session:
    """Return a boto3 session pinned to an optional region/profile."""
    if profile:
        return boto3.Session(region_name=region, profile_name=profile)
    return boto3.Session(region_name=region) if region else boto3.Session()


def assume_role_session(base_sess: boto3.session.Session, role_arn: str, external_id: Optional[str] = None) -> boto3.session.Session:
    """Assume a role and return a boto3 Session using temporary creds."""
    sts = base_sess.client("sts")
    assume_args = {"RoleArn": role_arn, "RoleSessionName": f"cfn-exporter-{int(time.time())}"}
    if external_id:
        assume_args["ExternalId"] = external_id
    resp = sts.assume_role(**assume_args)["Credentials"]

    def _refresh():
        return {
            "access_key": resp["AccessKeyId"],
            "secret_key": resp["SecretAccessKey"],
            "token": resp["SessionToken"],
            "expiry_time": resp["Expiration"].isoformat() if hasattr(resp["Expiration"], "isoformat") else resp["Expiration"],
        }

    creds = RefreshableCredentials.create_from_metadata(
        metadata=_refresh(), refresh_using=lambda: _refresh(), method="assume-role"
    )
    bcs = get_session()
    bcs._credentials = creds  # type: ignore
    authed_sess = boto3.Session(botocore_session=bcs, region_name=base_sess.region_name)
    return authed_sess


def tag_list_to_dict(tags: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    """Convert AWS tag list [{'Key':..., 'Value':...}] to a plain dict."""
    d: Dict[str, str] = {}
    if tags:
        for t in tags:
            k = t.get("Key")
            v = t.get("Value")
            if k is not None and v is not None:
                d[k] = v
    return d


def sanitize_logical_id(name: str) -> str:
    """
    Convert noisy names/ids to a CloudFormation-safe Logical ID.
    Rules:
      • keep alphanumerics, split others to spaces
      • TitleCase and concatenate
      • ensure it doesn't start with a digit
    """
    import re

    s = re.sub(r"[^A-Za-z0-9]", " ", name or "")
    parts = [p.capitalize() for p in s.split() if p]
    out = "".join(parts) or f"Res{int(time.time())}"
    if out[0].isdigit():
        out = "R" + out
    return out[:255]


class CFNTemplate:
    """Minimal CFN template builder with de-duplication of logical IDs."""

    def __init__(self, stack_name: str):
        self.template: Dict[str, Any] = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": f"Exported stack {stack_name} (best-effort)",
            "Metadata": {},
            "Parameters": {},
            "Mappings": {},
            "Resources": {},
            "Outputs": {},
        }
        self.logical_ids: set[str] = set()

    def add_resource(self, logical_id: str, res_type: str, properties: Dict[str, Any]) -> str:
        """Add a resource, suffixing with an integer if the logical id already exists."""
        if logical_id in self.logical_ids:
            i = 2
            base = logical_id
            while logical_id in self.logical_ids:
                logical_id = f"{base}{i}"
                i += 1
        self.logical_ids.add(logical_id)
        self.template["Resources"][logical_id] = {"Type": res_type, "Properties": properties}
        return logical_id

    def yaml(self) -> str:
        """Dump the full template as YAML (sorted keys disabled for readability)."""
        return yaml.safe_dump(self.template, sort_keys=False)


def export_vpcs(ec2, tmpl: CFNTemplate, region: str, prefix_region: bool, vpc_ids: Optional[List[str]]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Export all (or selected) VPCs in the region."""
    params = {}
    if vpc_ids:
        params["VpcIds"] = vpc_ids
    vpcs = ec2.describe_vpcs(**params).get("Vpcs", [])
    vpc_id_to_logical: Dict[str, str] = {}
    vpc_meta: Dict[str, Any] = {}

    for v in vpcs:
        vpc_id = v["VpcId"]
        cidr = v.get("CidrBlock")
        tags = tag_list_to_dict(v.get("Tags"))
        base = tags.get("Name", vpc_id) + "Vpc"
        lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)
        props: Dict[str, Any] = {"CidrBlock": cidr}
        if tags:
            props["Tags"] = [{"Key": k, "Value": val} for k, val in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::VPC", props)
        vpc_id_to_logical[vpc_id] = lid
        vpc_meta[vpc_id] = v
    return vpc_id_to_logical, vpc_meta


def export_igws(ec2, tmpl: CFNTemplate, vpc_id_to_logical: Dict[str, str], region: str, prefix_region: bool) -> Dict[str, str]:
    """Export Internet Gateways and VPC attachments."""
    igws = ec2.describe_internet_gateways().get("InternetGateways", [])
    igw_id_to_logical: Dict[str, str] = {}

    for igw in igws:
        tags = tag_list_to_dict(igw.get("Tags"))
        igw_id = igw["InternetGatewayId"]
        base = tags.get("Name", igw_id) + "Igw"
        lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)
        props: Dict[str, Any] = {}
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::InternetGateway", props)
        igw_id_to_logical[igw_id] = lid

        # Attachments
        for att in igw.get("Attachments", []):
            if att.get("State") == "available":
                vpc_id = att.get("VpcId")
                if vpc_id in vpc_id_to_logical:
                    attach_id = sanitize_logical_id(lid + "Attach" + vpc_id_to_logical[vpc_id])
                    tmpl.add_resource(
                        attach_id,
                        "AWS::EC2::VPCGatewayAttachment",
                        {"VpcId": {"Ref": vpc_id_to_logical[vpc_id]}, "InternetGatewayId": {"Ref": lid}},
                    )
    return igw_id_to_logical


def export_subnets(ec2, tmpl: CFNTemplate, vpc_id_to_logical: Dict[str, str], region: str, prefix_region: bool) -> Dict[str, str]:
    """Export all subnets; map them to their VPC logical IDs."""
    subnets = ec2.describe_subnets().get("Subnets", [])
    subnet_id_to_logical: Dict[str, str] = {}

    for s in subnets:
        sid = s["SubnetId"]
        cidr = s.get("CidrBlock")
        az = s.get("AvailabilityZone")
        vpc_id = s.get("VpcId")
        tags = tag_list_to_dict(s.get("Tags"))
        base = tags.get("Name", sid) + "Subnet"
        lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)
        props: Dict[str, Any] = {"CidrBlock": cidr, "VpcId": {"Ref": vpc_id_to_logical[vpc_id]}}
        if az:
            props["AvailabilityZone"] = az
        if s.get("MapPublicIpOnLaunch") is not None:
            props["MapPublicIpOnLaunch"] = s["MapPublicIpOnLaunch"]
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::Subnet", props)
        subnet_id_to_logical[sid] = lid
    return subnet_id_to_logical


def export_route_tables(
    ec2,
    tmpl: CFNTemplate,
    vpc_id_to_logical: Dict[str, str],
    subnet_id_to_logical: Dict[str, str],
    igw_id_to_logical: Dict[str, str],
    nat_id_to_logical: Dict[str, str],
    region: str,
    prefix_region: bool,
) -> Dict[str, str]:
    """Export route tables, inline routes, and subnet associations (skip main association)."""
    rts = ec2.describe_route_tables().get("RouteTables", [])
    rt_id_to_logical: Dict[str, str] = {}

    for rt in rts:
        rtid = rt["RouteTableId"]
        vpc_id = rt.get("VpcId")
        tags = tag_list_to_dict(rt.get("Tags"))
        base = tags.get("Name", rtid) + "Rt"
        lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)
        props: Dict[str, Any] = {"VpcId": {"Ref": vpc_id_to_logical[vpc_id]}}

        # Inline routes (safe subset: igw & nat)
        routes: List[Dict[str, Any]] = []
        for r in rt.get("Routes", []):
            route: Dict[str, Any] = {}
            if "DestinationCidrBlock" in r:
                route["DestinationCidrBlock"] = r["DestinationCidrBlock"]
            if "GatewayId" in r and str(r["GatewayId"]).startswith("igw-"):
                igw = r["GatewayId"]
                if igw in igw_id_to_logical:
                    route["GatewayId"] = {"Ref": igw_id_to_logical[igw]}
            if "NatGatewayId" in r:
                ngw = r["NatGatewayId"]
                if ngw in nat_id_to_logical:
                    route["NatGatewayId"] = {"Ref": nat_id_to_logical[ngw]}
            if route:
                routes.append(route)
        if routes:
            props["Routes"] = routes

        tmpl.add_resource(lid, "AWS::EC2::RouteTable", props)
        rt_id_to_logical[rtid] = lid

        # Subnet associations (skip implicit 'Main')
        for assoc in rt.get("Associations", []):
            if assoc.get("Main"):
                continue
            subnet_id = assoc.get("SubnetId")
            if subnet_id in subnet_id_to_logical:
                assoc_id = sanitize_logical_id(lid + "Assoc" + subnet_id_to_logical[subnet_id])
                tmpl.add_resource(
                    assoc_id,
                    "AWS::EC2::SubnetRouteTableAssociation",
                    {"RouteTableId": {"Ref": lid}, "SubnetId": {"Ref": subnet_id_to_logical[subnet_id]}},
                )
    return rt_id_to_logical


def export_eips(ec2, tmpl: CFNTemplate, region: str, prefix_region: bool) -> Dict[str, str]:
    """Export Elastic IPs (VPC domain only)."""
    eips = ec2.describe_addresses().get("Addresses", [])
    eip_id_to_logical: Dict[str, str] = {}

    for e in eips:
        alloc_id = e.get("AllocationId")
        if not alloc_id:  # EC2-Classic not supported
            continue
        tags = tag_list_to_dict(e.get("Tags"))
        base = tags.get("Name", alloc_id) + "Eip"
        lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)
        props: Dict[str, Any] = {"Domain": "vpc"}
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::EIP", props)
        eip_id_to_logical[alloc_id] = lid
    return eip_id_to_logical


def export_nat_gateways(
    ec2,
    tmpl: CFNTemplate,
    subnet_id_to_logical: Dict[str, str],
    eip_id_to_logical: Dict[str, str],
    region: str,
    prefix_region: bool,
) -> Dict[str, str]:
    """Export NAT Gateways (simple: first EIP only if multiple)."""
    ngws = ec2.describe_nat_gateways().get("NatGateways", [])
    nat_id_to_logical: Dict[str, str] = {}

    for n in ngws:
        ngw_id = n["NatGatewayId"]
        subnet_id = n["SubnetId"]
        tags = tag_list_to_dict(n.get("Tags"))
        base = tags.get("Name", ngw_id) + "NatGw"
        lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)
        alloc_ids = [a.get("AllocationId") for a in n.get("NatGatewayAddresses", []) if a.get("AllocationId")]

        props: Dict[str, Any] = {"SubnetId": {"Ref": subnet_id_to_logical[subnet_id]}}
        if alloc_ids:
            a = alloc_ids[0]
            if a in eip_id_to_logical:
                props["AllocationId"] = {"Fn::GetAtt": [eip_id_to_logical[a], "AllocationId"]}
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::NatGateway", props)
        nat_id_to_logical[ngw_id] = lid
    return nat_id_to_logical


def export_security_groups(ec2, tmpl: CFNTemplate, vpc_id_to_logical: Dict[str, str], region: str, prefix_region: bool) -> Dict[str, str]:
    """Export Security Groups with ingress/egress rules (safe subset)."""
    sgs = ec2.describe_security_groups().get("SecurityGroups", [])
    sg_id_to_logical: Dict[str, str] = {}

    for sg in sgs:
        sgid = sg["GroupId"]
        vpc_id = sg.get("VpcId")
        name = sg.get("GroupName", sgid)
        desc = sg.get("Description", f"Exported {name}")
        tags = tag_list_to_dict(sg.get("Tags"))
        base = tags.get("Name", name) + "Sg"
        lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)

        def perms_to_rules(perms: List[Dict[str, Any]], is_egress: bool = False) -> List[Dict[str, Any]]:
            rules: List[Dict[str, Any]] = []
            for ip in perms:
                rule: Dict[str, Any] = {"IpProtocol": ip.get("IpProtocol", "-1")}
                if "FromPort" in ip:
                    rule["FromPort"] = ip["FromPort"]
                if "ToPort" in ip:
                    rule["ToPort"] = ip["ToPort"]

                # CIDR sources/destinations
                cidrs = [{"CidrIp": c["CidrIp"]} for c in ip.get("IpRanges", []) if "CidrIp" in c]
                cidrsv6 = [{"CidrIpv6": c["CidrIpv6"]} for c in ip.get("Ipv6Ranges", []) if "CidrIpv6" in c]

                # SG pair references
                pairs_key = "UserIdGroupPairs"
                pairs = [p for p in ip.get(pairs_key, []) if "GroupId" in p]

                # Prefer concise single-value fields when unique:
                if not is_egress:
                    if cidrs:
                        rule["CidrIp"] = cidrs[0]["CidrIp"] if len(cidrs) == 1 else None
                    if cidrsv6:
                        rule["CidrIpv6"] = cidrsv6[0]["CidrIpv6"] if len(cidrsv6) == 1 else None
                    if pairs:
                        rule["SourceSecurityGroupId"] = pairs[0]["GroupId"] if len(pairs) == 1 else None
                else:
                    if cidrs:
                        rule["CidrIp"] = cidrs[0]["CidrIp"] if len(cidrs) == 1 else None
                    if cidrsv6:
                        rule["CidrIpv6"] = cidrsv6[0]["CidrIpv6"] if len(cidrsv6) == 1 else None
                    if pairs:
                        rule["DestinationSecurityGroupId"] = pairs[0]["GroupId"] if len(pairs) == 1 else None

                # If multiple, include the full arrays too (CFN accepts both forms)
                if len(cidrs) > 1:
                    rule["IpRanges"] = cidrs
                if len(cidrsv6) > 1:
                    rule["Ipv6Ranges"] = cidrsv6
                if len(pairs) > 1:
                    rule[pairs_key] = [{"GroupId": p["GroupId"]} for p in pairs]

                rules.append(rule)
            return rules

        ingress = perms_to_rules(sg.get("IpPermissions", []), is_egress=False)
        egress = perms_to_rules(sg.get("IpPermissionsEgress", []), is_egress=True)

        props: Dict[str, Any] = {
            "GroupDescription": desc,
            "VpcId": {"Ref": vpc_id_to_logical[vpc_id]},
        }
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        if name:
            props["GroupName"] = name
        if ingress:
            props["SecurityGroupIngress"] = ingress
        if egress:
            props["SecurityGroupEgress"] = egress

        tmpl.add_resource(lid, "AWS::EC2::SecurityGroup", props)
        sg_id_to_logical[sgid] = lid

    return sg_id_to_logical


def export_instances(
    ec2,
    tmpl: CFNTemplate,
    subnet_id_to_logical: Dict[str, str],
    sg_id_to_logical: Dict[str, str],
    region: str,
    prefix_region: bool,
    instance_ids: Optional[List[str]] = None,
) -> None:
    """Export EC2 instances with conservative, reproducible properties."""
    paginator = ec2.get_paginator("describe_instances")
    paginate_args = {}
    if instance_ids:
        paginate_args["Filters"] = [{"Name": "instance-id", "Values": instance_ids}]
    for page in paginator.paginate(**paginate_args):
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                iid = inst["InstanceId"]
                tags = tag_list_to_dict(inst.get("Tags"))
                name = tags.get("Name", iid)
                base = name + "Ec2"
                lid = sanitize_logical_id((region + "-" if prefix_region else "") + base)

                props: Dict[str, Any] = {
                    "ImageId": inst.get("ImageId"),
                    "InstanceType": inst.get("InstanceType"),
                }
                if inst.get("KeyName"):
                    props["KeyName"] = inst["KeyName"]
                if inst.get("IamInstanceProfile"):
                    # Use ARN for fidelity; can be swapped to Ref manually later if needed
                    props["IamInstanceProfile"] = inst["IamInstanceProfile"].get("Arn")

                # Security groups (prefer logical Refs when we exported the SG)
                sgs: List[Any] = []
                for sg in inst.get("SecurityGroups", []):
                    sgid = sg.get("GroupId")
                    sgs.append({"Ref": sg_id_to_logical[sgid]} if sgid in sg_id_to_logical else sgid)
                if sgs:
                    props["SecurityGroupIds"] = sgs

                # Subnet (primary ENI)
                if inst.get("SubnetId") and inst["SubnetId"] in subnet_id_to_logical:
                    props["SubnetId"] = {"Ref": subnet_id_to_logical[inst["SubnetId"]]}

                # Block devices (safe subset)
                if inst.get("BlockDeviceMappings"):
                    bdm: List[Dict[str, Any]] = []
                    for m in inst["BlockDeviceMappings"]:
                        entry: Dict[str, Any] = {"DeviceName": m.get("DeviceName")}
                        ebs = m.get("Ebs")
                        if ebs:
                            e: Dict[str, Any] = {"DeleteOnTermination": ebs.get("DeleteOnTermination", True)}
                            if ebs.get("VolumeSize"):
                                e["VolumeSize"] = int(ebs["VolumeSize"])
                            if ebs.get("VolumeType"):
                                e["VolumeType"] = ebs["VolumeType"]
                            if ebs.get("Encrypted") is not None:
                                e["Encrypted"] = ebs["Encrypted"]
                            if ebs.get("KmsKeyId"):
                                e["KmsKeyId"] = ebs["KmsKeyId"]
                            entry["Ebs"] = e
                        bdm.append(entry)
                    if bdm:
                        props["BlockDeviceMappings"] = bdm

                if tags:
                    props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]

                tmpl.add_resource(lid, "AWS::EC2::Instance", props)


def get_account_id(session: boto3.session.Session) -> str:
    sts = session.client("sts")
    return sts.get_caller_identity()["Account"]


def run(
    stack_name: str,
    output_path: Path,
    regions: List[str],
    profile: Optional[str],
    assume_role_arn: Optional[str],
    external_id: Optional[str],
    skip_network: bool,
    skip_security: bool,
    skip_compute: bool,
    prefix_region: bool,
    vpc_ids: Optional[List[str]],
    instance_ids: Optional[List[str]],
) -> None:
    """Main orchestrator: scan regions, collect resources, and write YAML to ./results."""
    ensure_results_dir()
    output_path = (RESULTS_DIR / output_path.name).resolve()
    master_template = CFNTemplate(stack_name)

    # Base session (for metadata such as AccountId); role assumption applied per-region client below
    base_session = boto_session(profile=profile)
    if not regions:
        regions = [base_session.region_name or "us-east-1"]

    account_id = get_account_id(base_session) if not assume_role_arn else "assumed"
    export_time = datetime.now(timezone.utc).isoformat()

    master_template.template["Metadata"] = {
        "Exporter": "cfn_exporter.py v0.2",
        "AccountId": account_id,
        "Regions": regions,
        "ExportedAt": export_time,
        "PrefixRegion": prefix_region,
        "Filters": {"VpcIds": vpc_ids or [], "InstanceIds": instance_ids or []},
    }

    for region in regions:
        print(f"[INFO] Scanning region: {region}")
        sess = boto_session(region=region, profile=profile)
        if assume_role_arn:
            sess = assume_role_session(sess, assume_role_arn, external_id)

        ec2 = sess.client("ec2", config=Config(retries={"max_attempts": 10, "mode": "standard"}))

        vpc_id_to_logical: Dict[str, str] = {}
        subnet_id_to_logical: Dict[str, str] = {}
        igw_id_to_logical: Dict[str, str] = {}
        eip_id_to_logical: Dict[str, str] = {}
        nat_id_to_logical: Dict[str, str] = {}
        sg_id_to_logical: Dict[str, str] = {}

        if not skip_network:
            vpc_id_to_logical, _ = export_vpcs(ec2, master_template, region, prefix_region, vpc_ids)
            igw_id_to_logical = export_igws(ec2, master_template, vpc_id_to_logical, region, prefix_region)
            subnet_id_to_logical = export_subnets(ec2, master_template, vpc_id_to_logical, region, prefix_region)
            eip_id_to_logical = export_eips(ec2, master_template, region, prefix_region)
            nat_id_to_logical = export_nat_gateways(ec2, master_template, subnet_id_to_logical, eip_id_to_logical, region, prefix_region)

        if not skip_security:
            sg_id_to_logical = export_security_groups(ec2, master_template, vpc_id_to_logical, region, prefix_region)

        if not skip_network:
            # Needs nat_id_to_logical; run after NAT export and SGs (for completeness)
            export_route_tables(
                ec2,
                master_template,
                vpc_id_to_logical,
                subnet_id_to_logical,
                igw_id_to_logical,
                nat_id_to_logical,
                region,
                prefix_region,
            )

        if not skip_compute:
            export_instances(ec2, master_template, subnet_id_to_logical, sg_id_to_logical, region, prefix_region, instance_ids)

    with open(output_path, "w") as f:
        f.write(master_template.yaml())
    print(f"[OK] Wrote CloudFormation template to {output_path}")


def parse_args(argv=None):
    """Define CLI arguments (stack name, output file name, regions, scoping and auth)."""
    p = argparse.ArgumentParser(description="Export AWS infra to CloudFormation YAML (results-aware)")
    p.add_argument("--stack-name", required=True, help="Logical stack name for the exported template")
    p.add_argument("--output", default="exported_stack.yaml", help="Output YAML filename (written to ./results)")
    p.add_argument("--regions", nargs="*", default=[], help="Regions to scan; default: current boto3 config region")

    # Scoping
    p.add_argument("--vpc-ids", nargs="*", default=None, help="Limit export to these VPC IDs")
    p.add_argument("--instance-ids", nargs="*", default=None, help="Limit export to these EC2 instance IDs")

    # Skips
    p.add_argument("--no-network", action="store_true", help="Skip VPC/Subnet/RT/IGW/NAT/EIP export")
    p.add_argument("--no-security", action="store_true", help="Skip Security Groups")
    p.add_argument("--no-compute", action="store_true", help="Skip EC2 Instances")

    # Logical ID strategy
    p.add_argument("--prefix-region", action="store_true", help="Prefix logical IDs with the region to avoid collisions")

    # Auth
    p.add_argument("--profile", default=None, help="AWS named profile to use")
    p.add_argument("--assume-role-arn", default=None, help="Assume this role ARN before export (cross-account)")
    p.add_argument("--external-id", default=None, help="External ID to use when assuming the role")

    return p.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    regions = args.regions  # resolved in run()
    run(
        stack_name=args.stack_name,
        output_path=Path(args.output),
        regions=regions,
        profile=args.profile,
        assume_role_arn=args.assume_role_arn,
        external_id=args.external_id,
        skip_network=args.no_network,
        skip_security=args.no_security,
        skip_compute=args.no_compute,
        prefix_region=args.prefix_region,
        vpc_ids=args.vpc_ids,
        instance_ids=args.instance_ids,
    )

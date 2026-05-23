# iaac_cf/transform.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# -------------------------------
# Public API
# -------------------------------

@dataclass
class TransformOptions:
    dest_region: str
    fix_public_routes: bool = True  # Item (3) – enabled by default


@dataclass
class TransformChange:
    kind: str
    logical_id: str
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransformResult:
    template: Dict[str, Any]
    changes: List[TransformChange]


def apply_transforms(template: Dict[str, Any], opts: TransformOptions) -> TransformResult:
    """
    Applies conservative DR transforms. For this task, we scope to item (3):
    - Ensure public subnets' route tables have a 0.0.0.0/0 route via an IGW
      (add or rewrite if mistakenly pointing to NAT).
    """
    tpl = _normalize_template(template)
    changes: List[TransformChange] = []

    if opts.fix_public_routes:
        c = _fix_public_subnet_routes(tpl)
        changes.extend(c)

    # Breadcrumb for traceability
    _ensure_metadata_breadcrumb(tpl, {"DRTransform": {"DestRegion": opts.dest_region,
                                                      "FixPublicRoutes": bool(opts.fix_public_routes)}})

    return TransformResult(template=tpl, changes=changes)


def summarize_changes(changes: List[TransformChange]) -> Dict[str, int]:
    counts = {}
    for ch in changes:
        counts[ch.kind] = counts.get(ch.kind, 0) + 1
    return counts


# -------------------------------
# Internals
# -------------------------------

def _normalize_template(tpl: Dict[str, Any]) -> Dict[str, Any]:
    tpl.setdefault("Parameters", {})
    tpl.setdefault("Mappings", {})
    tpl.setdefault("Resources", {})
    tpl.setdefault("Outputs", {})
    return tpl


def _ensure_metadata_breadcrumb(tpl: Dict[str, Any], crumb: Dict[str, Any]) -> None:
    # Put a small breadcrumb at top-level under Metadata for auditability.
    md = tpl.get("Metadata") or {}
    md.update(crumb)
    tpl["Metadata"] = md


def _is_public_subnet(res: Dict[str, Any]) -> bool:
    props = res.get("Properties") or {}
    # Public subnets are commonly identified by MapPublicIpOnLaunch: true
    val = props.get("MapPublicIpOnLaunch", False)
    # Support both literal True and pseudo-parameters/conditions that evaluate to True
    return bool(val) is True


def _collect_vpc_and_igw(resources: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Attempt to find a VPC logical id and an IGW logical id that is attached to it.
    Returns: (vpc_id_logical, igw_id_logical) — both logical IDs in this template if present.
    """
    vpc_lids = [lid for lid, r in resources.items() if r.get("Type") == "AWS::EC2::VPC"]
    vpc_lid = vpc_lids[0] if vpc_lids else None

    igw_lid = None
    # Look for IGW and a VPCGatewayAttachment that references it
    igw_ids = [lid for lid, r in resources.items() if r.get("Type") == "AWS::EC2::InternetGateway"]
    if igw_ids:
        # Confirm it is attached
        for lid, r in resources.items():
            if r.get("Type") == "AWS::EC2::VPCGatewayAttachment":
                props = r.get("Properties") or {}
                if _ref_equals(props.get("InternetGatewayId"), igw_ids[0]):
                    igw_lid = igw_ids[0]
                    break
    return vpc_lid, igw_lid


def _ref_equals(node: Any, logical_id: str) -> bool:
    return isinstance(node, dict) and ("Ref" in node) and node["Ref"] == logical_id


def _ensure_parameter(tpl: Dict[str, Any], name: str, ptype: str, description: str) -> None:
    params = tpl.setdefault("Parameters", {})
    if name not in params:
        params[name] = {
            "Type": ptype,
            "Description": description
        }


def _gather_public_subnets(resources: Dict[str, Any]) -> List[str]:
    pubs = []
    for lid, r in resources.items():
        if r.get("Type") == "AWS::EC2::Subnet" and _is_public_subnet(r):
            pubs.append(lid)
    return pubs


def _gather_assoc_maps(resources: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Returns: map RouteTableId(logical) -> [ SubnetId(logical), ... ]
    from AWS::EC2::SubnetRouteTableAssociation resources.
    """
    rt_to_subnets: Dict[str, List[str]] = {}
    for lid, r in resources.items():
        if r.get("Type") != "AWS::EC2::SubnetRouteTableAssociation":
            continue
        props = r.get("Properties") or {}
        rt = _extract_ref(props.get("RouteTableId"))
        sn = _extract_ref(props.get("SubnetId"))
        if rt and sn:
            rt_to_subnets.setdefault(rt, []).append(sn)
    return rt_to_subnets


def _extract_ref(node: Any) -> Optional[str]:
    if isinstance(node, dict) and "Ref" in node and isinstance(node["Ref"], str):
        return node["Ref"]
    return None


def _rt_default_routes(resources: Dict[str, Any], route_table_lid: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Returns a list of (route_logical_id, route_resource) for default routes
    (DestinationCidrBlock == 0.0.0.0/0) in a given route table.
    """
    out = []
    for lid, r in resources.items():
        if r.get("Type") != "AWS::EC2::Route":
            continue
        props = r.get("Properties") or {}
        if _extract_ref(props.get("RouteTableId")) != route_table_lid:
            continue
        dest = props.get("DestinationCidrBlock")
        if dest == "0.0.0.0/0":
            out.append((lid, r))
    return out


def _fix_public_subnet_routes(tpl: Dict[str, Any]) -> List[TransformChange]:
    """
    For each public subnet:
      - find its associated route table
      - ensure there is a default route 0.0.0.0/0 via IGW
      - if a default route points to a NAT, rewrite to IGW
      - if no IGW resource, require parameter DRInternetGatewayId
    """
    resources = tpl.get("Resources") or {}
    changes: List[TransformChange] = []

    public_subnets = set(_gather_public_subnets(resources))
    if not public_subnets:
        return changes

    vpc_lid, igw_lid = _collect_vpc_and_igw(resources)
    # If no IGW resource available, we will use a parameter
    use_param_igw = igw_lid is None
    if use_param_igw:
        _ensure_parameter(
            tpl,
            "DRInternetGatewayId",
            "String",
            "Internet Gateway ID to use for default routes in public subnets during DR."
        )

    # Build map of route table -> subnets
    rt_to_subnets = _gather_assoc_maps(resources)

    # Reverse: subnet -> [route_table_ids]
    subnet_to_rts: Dict[str, List[str]] = {}
    for rt, subs in rt_to_subnets.items():
        for s in subs:
            subnet_to_rts.setdefault(s, []).append(rt)

    # For each public subnet, fix its RTs
    for subnet_lid in sorted(public_subnets):
        rts = subnet_to_rts.get(subnet_lid, [])
        if not rts:
            # Add advisory only
            _append_advisory(resources, subnet_lid, "NoRouteTableAssociation",
                             "Public subnet has no SubnetRouteTableAssociation; default route cannot be enforced automatically.")
            changes.append(TransformChange(kind="advisory-public-subnet-no-assoc",
                                           logical_id=subnet_lid))
            continue

        for rt_lid in rts:
            default_routes = _rt_default_routes(resources, rt_lid)

            if not default_routes:
                # Create a new default route via IGW
                new_lid = _unique_route_lid(resources, base=f"{rt_lid}DefaultRoute")
                route_props = {
                    "RouteTableId": {"Ref": rt_lid},
                    "DestinationCidrBlock": "0.0.0.0/0",
                    "GatewayId": ({"Ref": igw_lid} if not use_param_igw else {"Ref": "DRInternetGatewayId"}),
                }
                resources[new_lid] = {"Type": "AWS::EC2::Route", "Properties": route_props}
                changes.append(TransformChange(kind="add-default-route-via-igw",
                                               logical_id=new_lid,
                                               detail={"RouteTable": rt_lid, "Subnet": subnet_lid}))
                _append_advisory(resources, subnet_lid, "DefaultRouteAdded",
                                 f"Added default route in RT {rt_lid} via InternetGateway.")
            else:
                for route_lid, route_res in default_routes:
                    props = route_res.get("Properties") or {}
                    # If it already targets an IGW, we're fine
                    if "GatewayId" in props:
                        continue
                    # If it targets NAT, rewrite to IGW
                    if "NatGatewayId" in props:
                        props.pop("NatGatewayId", None)
                        props["GatewayId"] = ({"Ref": igw_lid} if not use_param_igw else {"Ref": "DRInternetGatewayId"})
                        route_res["Properties"] = props
                        changes.append(TransformChange(kind="rewrite-default-route-nat-to-igw",
                                                       logical_id=route_lid,
                                                       detail={"RouteTable": rt_lid, "Subnet": subnet_lid}))
                        _append_advisory(resources, subnet_lid, "DefaultRouteRewritten",
                                         f"Rewrote default route in RT {rt_lid} from NAT to IGW.")
                    else:
                        # Some other target (e.g., GatewayAttachment missing). Convert to IGW.
                        for k in ("EgressOnlyInternetGatewayId", "InstanceId", "TransitGatewayId", "VpcPeeringConnectionId", "VpcEndpointId", "NetworkInterfaceId"):
                            props.pop(k, None)
                        props["GatewayId"] = ({"Ref": igw_lid} if not use_param_igw else {"Ref": "DRInternetGatewayId"})
                        route_res["Properties"] = props
                        changes.append(TransformChange(kind="convert-default-route-to-igw",
                                                       logical_id=route_lid,
                                                       detail={"RouteTable": rt_lid, "Subnet": subnet_lid}))
                        _append_advisory(resources, subnet_lid, "DefaultRouteConverted",
                                         f"Converted default route in RT {rt_lid} to InternetGateway.")

    return changes


def _unique_route_lid(resources: Dict[str, Any], base: str) -> str:
    lid = base
    i = 1
    while lid in resources:
        i += 1
        lid = f"{base}{i}"
    return lid


def _append_advisory(resources: Dict[str, Any], logical_id: str, code: str, message: str) -> None:
    """
    Add a small Metadata.DRAdvisory entry to the subnet resource for operator visibility.
    """
    res = resources.get(logical_id)
    if not res:
        return
    md = res.get("Metadata") or {}
    advisories = md.get("DRAdvisory") or []
    advisories.append({"Code": code, "Message": message})
    md["DRAdvisory"] = advisories
    res["Metadata"] = md

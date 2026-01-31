from collections import defaultdict
from itertools import combinations

from . import passive_collapse

UCC21710_ID = "UCC21710"
UCC21710_PRIMARY_PIN_NAMES = {
    "GND",
    "IN+",
    "IN-",
    "RDY",
    "~{FLT}",
    "~{RST}/EN",
    "VCC",
    "APWM",
}
UCC21710_SECONDARY_PIN_NAMES = {
    "AIN",
    "OC",
    "COM",
    "OUTH",
    "VDD",
    "OUTL",
    "CLMPI",
    "VEE",
}


def build_rules(snapshot):
    """Extracts connection rules from the standard snapshot."""
    net_endpoints = _collect_net_endpoints(snapshot)
    rules = []
    seen = set()

    # Direct capacitor rules.
    for comp in snapshot.get("components", []):
        if passive_collapse.classify_passive(comp) != "C":
            continue
        nets = _component_nets(comp)
        if len(nets) != 2:
            continue
        net_a, net_b = sorted(nets)
        ep_a = _pick_endpoint(net_endpoints.get(net_a))
        ep_b = _pick_endpoint(net_endpoints.get(net_b))
        if not ep_a or not ep_b:
            continue
        _add_rule(rules, seen, "C_DIRECT", ep_a, ep_b)

    # Resistor/inductor path rules.
    for passive_type, rule_type in (("R", "R_PATH"), ("L", "L_PATH")):
        for nets in _passive_net_components(snapshot, passive_type):
            endpoints = []
            for net in sorted(nets):
                ep = _pick_endpoint(net_endpoints.get(net))
                if ep:
                    endpoints.append((net, ep))
            for (_, ep_a), (_, ep_b) in combinations(endpoints, 2):
                _add_rule(rules, seen, rule_type, ep_a, ep_b, allow_series=True)

    return rules


def _collect_net_endpoints(snapshot):
    net_endpoints = defaultdict(list)
    for comp in snapshot.get("components", []):
        if comp.get("category") == "passive":
            continue
        part_id = comp.get("part_id")
        category = comp.get("category")
        for pin in comp.get("pins", []):
            net = pin.get("net")
            if not net:
                continue
            endpoint = {
                "part_id": part_id,
                "category": category,
                "pin_role": pin.get("pin_role"),
                "pin_id": str(pin.get("pin_id", "")),
                "pin_name": str(pin.get("pin_name", "")),
            }
            if part_id == UCC21710_ID:
                endpoint["domain"] = _ucc21710_domain(
                    endpoint.get("pin_id"), endpoint.get("pin_name")
                )
            net_endpoints[net].append(endpoint)
    return net_endpoints


def _component_nets(comp):
    nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
    return [net for net in nets if net]


def _pick_endpoint(endpoints):
    if not endpoints:
        return None
    return sorted(endpoints, key=_endpoint_key)[0]


def _endpoint_key(endpoint):
    return (
        0 if endpoint.get("pin_role") else 1,
        endpoint.get("part_id") or "",
        endpoint.get("category") or "",
        endpoint.get("pin_role") or "",
        endpoint.get("pin_id") or "",
        endpoint.get("pin_name") or "",
        endpoint.get("domain") or "",
    )


def _endpoint_signature(endpoint):
    return (
        endpoint.get("part_id") or "",
        endpoint.get("category") or "",
        endpoint.get("pin_role") or "",
        endpoint.get("pin_id") or "",
        endpoint.get("pin_name") or "",
    )


def _rule_key(rule_type, ep_a, ep_b):
    sig_a = _endpoint_signature(ep_a)
    sig_b = _endpoint_signature(ep_b)
    ordered = tuple(sorted([sig_a, sig_b]))
    return (rule_type, ordered)


def _add_rule(rules, seen, rule_type, ep_a, ep_b, allow_series=False):
    if _should_skip_rule(rule_type, ep_a, ep_b):
        return
    key = _rule_key(rule_type, ep_a, ep_b)
    if key in seen:
        return
    seen.add(key)
    rules.append(
        {
            "rule_type": rule_type,
            "endpoint_a": ep_a,
            "endpoint_b": ep_b,
            "allow_series": bool(allow_series),
            "min_count": 1,
            "fail_on_short": True,
        }
    )


def _should_skip_rule(rule_type, ep_a, ep_b):
    if ep_a.get("part_id") != UCC21710_ID or ep_b.get("part_id") != UCC21710_ID:
        return False
    domain_a = ep_a.get("domain")
    domain_b = ep_b.get("domain")
    if domain_a and domain_b and domain_a != domain_b:
        return True
    if rule_type == "C_DIRECT" and _is_ucc21710_rdy_gnd(ep_a, ep_b):
        return True
    if rule_type == "C_DIRECT" and _is_ucc21710_rst_en_gnd(ep_a, ep_b):
        return True
    roles = {ep_a.get("pin_role"), ep_b.get("pin_role")}
    if rule_type == "C_DIRECT" and roles == {"logic_in", "logic_out"}:
        return True
    if rule_type == "R_PATH" and roles == {"supply_gnd", "supply_vdd"}:
        return True
    return False


def _is_ucc21710_rdy_gnd(ep_a, ep_b):
    if ep_a.get("pin_name") == "RDY" and ep_b.get("pin_role") == "supply_gnd":
        return True
    if ep_b.get("pin_name") == "RDY" and ep_a.get("pin_role") == "supply_gnd":
        return True
    return False


def _is_ucc21710_rst_en_gnd(ep_a, ep_b):
    names = {ep_a.get("pin_name"), ep_b.get("pin_name")}
    if "~{RST}/EN" not in names:
        return False
    return "IN-" in names or "GND" in names


def _ucc21710_domain(pin_id, pin_name):
    if pin_id and str(pin_id).isdigit():
        pin_num = int(pin_id)
        if 1 <= pin_num <= 8:
            return "secondary"
        if 9 <= pin_num <= 16:
            return "primary"
    if pin_name in UCC21710_PRIMARY_PIN_NAMES:
        return "primary"
    if pin_name in UCC21710_SECONDARY_PIN_NAMES:
        return "secondary"
    return None


def _passive_net_components(snapshot, passive_type):
    graph = defaultdict(set)
    net_nodes = set()

    for comp in snapshot.get("components", []):
        if passive_collapse.classify_passive(comp) != passive_type:
            continue
        comp_ref = comp.get("ref")
        comp_node = f"comp:{comp_ref}"
        for pin in comp.get("pins", []):
            net = pin.get("net")
            if not net:
                continue
            net_node = f"net:{net}"
            graph[comp_node].add(net_node)
            graph[net_node].add(comp_node)
            net_nodes.add(net_node)

    visited = set()
    components = []

    for node in list(graph):
        if node in visited:
            continue
        stack = [node]
        visited.add(node)
        nets = set()
        while stack:
            cur = stack.pop()
            if cur.startswith("net:"):
                nets.add(cur[4:])
            for nb in graph.get(cur, []):
                if nb in visited:
                    continue
                visited.add(nb)
                stack.append(nb)
        if nets:
            components.append(nets)

    return components

from collections import defaultdict

from . import passive_collapse


def check_rules(snapshot, rules, task_id=None):
    errors = []

    cap_pairs = _capacitor_pairs(snapshot)
    r_components = _passive_net_components(snapshot, "R")
    l_components = _passive_net_components(snapshot, "L")

    endpoint_cache = {}

    if task_id == 15:
        errors.extend(_check_task15_out_resistor(snapshot, r_components, endpoint_cache))
        return errors

    for rule in rules:
        if task_id == 6 and _rule_has_buck_en(rule):
            continue
        if task_id == 6 and _rule_has_role_pair(rule, "buck_vin", "buck_gnd"):
            continue
        if task_id == 6 and _rule_has_role_pair(rule, "buck_vin", "buck_fb"):
            continue
        # Skip C_DIRECT(mosfet_source, mosfet_drain) for half-bridge tasks (8-12)
        # This rule causes false positives due to cross-instance aggregation:
        # decoupling caps (VBUS+ <-> PGND) are mistaken for D-S snubbers
        if _is_mosfet_source_drain_cap_rule(rule):
            continue
        rule_type = rule.get("rule_type")
        ep_a = rule.get("endpoint_a", {})
        ep_b = rule.get("endpoint_b", {})

        nets_a = _resolve_endpoint_nets(snapshot, ep_a, endpoint_cache)
        nets_b = _resolve_endpoint_nets(snapshot, ep_b, endpoint_cache)

        if not nets_a or not nets_b:
            errors.append(
                f"{rule_type} endpoint missing: "
                f"{_endpoint_desc(ep_a)} or {_endpoint_desc(ep_b)}"
            )
            continue

        if rule_type == "C_DIRECT":
            ok, shorted, pair = _check_cap_rule(nets_a, nets_b, cap_pairs)
        elif rule_type == "R_PATH":
            ok, shorted, pair = _check_path_rule(nets_a, nets_b, r_components)
        elif rule_type == "L_PATH":
            ok, shorted, pair = _check_path_rule(nets_a, nets_b, l_components)
        else:
            continue

        if ok:
            continue
        if shorted:
            if task_id == 13 and _is_ucc27511_out_pair(rule_type, ep_a, ep_b):
                continue
            if _is_ucc21710_gate_short(rule_type, ep_a, ep_b):
                errors.append(
                    "UCC21710: OUTH (pin 4) and OUTL (pin 6) must each go through "
                    "separate series resistors to the GATE net; CLMPI (pin 7) may "
                    "connect to GATE. Do not tie OUTH/OUTL directly to CLMPI/GATE."
                )
                continue
            errors.append(
                f"{rule_type} shorted between {_endpoint_desc(ep_a)} and "
                f"{_endpoint_desc(ep_b)} (net {pair})"
            )
        else:
            errors.append(
                f"{rule_type} missing between {_endpoint_desc(ep_a)} and "
                f"{_endpoint_desc(ep_b)} (nets {sorted(nets_a)} vs {sorted(nets_b)})"
            )

    if task_id == 6:
        errors.extend(_check_task6_enable(snapshot, r_components, endpoint_cache))
    if task_id == 3:
        errors.extend(_check_p3_gain(snapshot))
    return errors


def check_driver_gate_links(std_snapshot, gen_snapshot):
    std_links = passive_collapse.compute_driver_gate_links(std_snapshot)
    gen_links = passive_collapse.compute_driver_gate_links(gen_snapshot)
    errors = []
    used = set()
    for std_link in std_links:
        match_idx = _find_matching_link(std_link, gen_links, used)
        if match_idx is None:
            gate = std_link["gate"]
            errors.append(
                f"Missing driver->gate link for MOSFET {gate.get('part_id') or gate.get('ref')}"
            )
        else:
            used.add(match_idx)
    return errors


def _capacitor_pairs(snapshot):
    pairs = set()
    for comp in snapshot.get("components", []):
        if passive_collapse.classify_passive(comp) != "C":
            continue
        nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
        if len(nets) != 2:
            continue
        net_a, net_b = sorted(nets)
        if net_a == net_b:
            continue
        pairs.add(frozenset([net_a, net_b]))
    return pairs


def _passive_net_components(snapshot, passive_type):
    graph = defaultdict(set)
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


def _resolve_endpoint_nets(snapshot, endpoint, cache):
    key = _endpoint_key(endpoint)
    if key in cache:
        return cache[key]

    part_id = endpoint.get("part_id")
    category = endpoint.get("category")
    pin_role = endpoint.get("pin_role")
    pin_id = endpoint.get("pin_id")
    pin_name = endpoint.get("pin_name")

    nets = set()
    for comp in snapshot.get("components", []):
        if part_id and comp.get("part_id") != part_id:
            continue
        if not part_id and category and comp.get("category") != category:
            continue
        for pin in comp.get("pins", []):
            if pin_role and pin.get("pin_role") != pin_role:
                continue
            if pin_id and str(pin.get("pin_id", "")) != str(pin_id):
                continue
            if pin_name and str(pin.get("pin_name", "")) != str(pin_name):
                continue
            net = pin.get("net")
            if net:
                nets.add(net)

    if not nets and part_id and category:
        # fallback to category match if part_id not found in generated
        for comp in snapshot.get("components", []):
            if comp.get("category") != category:
                continue
            for pin in comp.get("pins", []):
                if pin_role and pin.get("pin_role") != pin_role:
                    continue
                net = pin.get("net")
                if net:
                    nets.add(net)

    cache[key] = nets
    return nets


def _rule_has_buck_en(rule):
    for endpoint in (rule.get("endpoint_a", {}), rule.get("endpoint_b", {})):
        if endpoint.get("pin_role") == "buck_en":
            return True
    return False


def _is_mosfet_source_drain_cap_rule(rule):
    """
    Detect C_DIRECT rules between mosfet_source and mosfet_drain.

    These rules cause false positives in half-bridge scenarios because:
    1. Cross-instance aggregation: all sources and drains are collected together
    2. Decoupling caps (VBUS+ <-> PGND) are mistakenly matched as D-S snubbers
    3. D-S snubbers are optional for SiC MOSFETs

    This check is applied globally (not task-specific) since the semantic issue
    affects any circuit with multiple MOSFETs of the same type.
    """
    if rule.get("rule_type") != "C_DIRECT":
        return False
    roles = {
        rule.get("endpoint_a", {}).get("pin_role"),
        rule.get("endpoint_b", {}).get("pin_role"),
    }
    return roles == {"mosfet_source", "mosfet_drain"}


def _check_task15_out_resistor(snapshot, r_components, endpoint_cache):
    out_endpoint = {"part_id": "UCC5390E", "category": "ic", "pin_role": "out"}
    out_nets = _resolve_endpoint_nets(snapshot, out_endpoint, endpoint_cache)
    if not out_nets:
        return ["UCC5390E: OUT pin missing net"]

    supply_roles = {"primary_vdd", "primary_gnd", "secondary_vdd", "secondary_gnd"}
    supply_nets = set()
    for role in supply_roles:
        supply_nets.update(
            _resolve_endpoint_nets(
                snapshot, {"part_id": "UCC5390E", "category": "ic", "pin_role": role}, endpoint_cache
            )
        )

    for nets in r_components:
        if not (out_nets & nets):
            continue
        for net in nets:
            if net in out_nets or net in supply_nets:
                continue
            return []

    return ["UCC5390E: OUT must connect to a gate net through a resistor network"]


def _check_p3_gain(snapshot):
    target = 1.47
    tolerance = 0.2
    min_ratio = target * (1 - tolerance)
    max_ratio = target * (1 + tolerance)

    opa = None
    for comp in snapshot.get("components", []):
        if comp.get("part_id") == "OPA328":
            opa = comp
            break
    if not opa:
        return ["p3 gain check: OPA328 not found"]

    neg_net = _find_pin_net(opa, {"-IN", "IN-", "INN", "VINN"})
    pos_net = _find_pin_net(opa, {"+IN", "IN+", "INP", "VINP"})
    if not neg_net or not pos_net:
        return ["p3 gain check: missing +IN/-IN nets on OPA328"]

    resistors = []
    for comp in snapshot.get("components", []):
        if passive_collapse.classify_passive(comp) != "R":
            continue
        nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
        if len(nets) != 2:
            continue
        value = _parse_value(comp.get("value"))
        resistors.append(
            {
                "ref": comp.get("ref", "?"),
                "value": value,
                "value_raw": comp.get("value"),
                "nets": nets,
            }
        )

    errors = []
    errors.extend(_check_ratio_for_net(resistors, neg_net, "p3 gain check (-IN)", min_ratio, max_ratio))
    errors.extend(_check_ratio_for_net(resistors, pos_net, "p3 gain check (+IN)", min_ratio, max_ratio))
    return errors


def _check_ratio_for_net(resistors, target_net, label, min_ratio, max_ratio):
    related = [r for r in resistors if target_net in r["nets"]]
    if len(related) != 2:
        return [f"{label}: expected 2 resistors on net {target_net}, got {len(related)}"]

    values = []
    for r in related:
        if r["value"] is None or r["value"] <= 0:
            return [f"{label}: invalid resistor value for {r['ref']} ({r['value_raw']})"]
        values.append((r["ref"], r["value"], r["value_raw"]))

    values.sort(key=lambda x: x[1])
    ratio = values[1][1] / values[0][1]
    if ratio < min_ratio or ratio > max_ratio:
        return ["resistance is wrong"]
    return []


def _find_pin_net(comp, candidates):
    for pin in comp.get("pins", []):
        name = str(pin.get("pin_name", "")).upper()
        if name in candidates:
            return pin.get("net")
    return None


def _parse_value(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text_upper = text.upper()
    if "R" in text_upper and text_upper.replace("R", "").isdigit():
        parts = text_upper.split("R", 1)
        whole = parts[0] or "0"
        frac = parts[1] or "0"
        try:
            return float(f"{whole}.{frac}")
        except ValueError:
            return None

    import re
    match = re.match(r"^([0-9]*\.?[0-9]+)\s*([A-Za-zµu]*)$", text)
    if not match:
        return None
    base = float(match.group(1))
    suffix = match.group(2)
    if not suffix:
        return base
    suffix = suffix.replace("ohm", "").replace("OHM", "")
    suffix_lower = suffix.lower()
    if suffix_lower in {"p"}:
        return base * 1e-12
    if suffix_lower in {"n"}:
        return base * 1e-9
    if suffix_lower in {"u", "µ"}:
        return base * 1e-6
    if suffix_lower in {"k"}:
        return base * 1e3
    if suffix_lower in {"meg"} or suffix in {"M", "MEG"}:
        return base * 1e6
    if suffix == "m":
        return base * 1e-3
    if suffix_lower in {"g"}:
        return base * 1e9
    if suffix_lower.endswith("k"):
        return base * 1e3
    if suffix_lower.endswith("m"):
        return base * (1e-3 if suffix.endswith("m") else 1e6)
    if suffix_lower.endswith("meg"):
        return base * 1e6
    return None


def _rule_has_role_pair(rule, role_a, role_b):
    roles = {
        rule.get("endpoint_a", {}).get("pin_role"),
        rule.get("endpoint_b", {}).get("pin_role"),
    }
    return role_a in roles and role_b in roles


def _check_task6_enable(snapshot, r_components, endpoint_cache):
    errors = []
    en_endpoint = {"part_id": "TPS54302", "category": "ic", "pin_role": "buck_en"}
    vin_endpoint = {"part_id": "TPS54302", "category": "ic", "pin_role": "buck_vin"}
    gnd_endpoint = {"part_id": "TPS54302", "category": "ic", "pin_role": "buck_gnd"}

    en_nets = _resolve_endpoint_nets(snapshot, en_endpoint, endpoint_cache)
    if not _is_connected_nets(en_nets):
        return errors

    vin_nets = _resolve_endpoint_nets(snapshot, vin_endpoint, endpoint_cache)
    gnd_nets = _resolve_endpoint_nets(snapshot, gnd_endpoint, endpoint_cache)

    ok_vin, short_vin, _ = _check_path_rule(en_nets, vin_nets, r_components)
    ok_gnd, short_gnd, _ = _check_path_rule(en_nets, gnd_nets, r_components)

    if ok_vin and ok_gnd:
        return errors

    if short_vin or short_gnd:
        errors.append(
            "EN should not be directly shorted; use a resistor divider between VIN and GND"
        )
        return errors

    errors.append(
        "EN requires a resistor divider to VIN and GND, or leave EN unconnected/NC"
    )
    return errors


def _is_connected_nets(nets):
    if not nets:
        return False
    usable = {net for net in nets if str(net).upper() not in {"NC", "__NOCONNECT"}}
    return bool(usable)


def _endpoint_key(endpoint):
    return (
        endpoint.get("part_id") or "",
        endpoint.get("category") or "",
        endpoint.get("pin_role") or "",
        endpoint.get("pin_id") or "",
        endpoint.get("pin_name") or "",
    )


def _endpoint_desc(endpoint):
    part_id = endpoint.get("part_id") or endpoint.get("category") or "component"
    role = endpoint.get("pin_role")
    details = []
    pin_id = endpoint.get("pin_id")
    pin_name = endpoint.get("pin_name")
    if pin_id:
        details.append(str(pin_id))
    if pin_name:
        details.append(str(pin_name))
    if role:
        if details:
            return f"{part_id}:{role}({', '.join(details)})"
        return f"{part_id}:{role}"
    if details:
        return f"{part_id}:{', '.join(details)}"
    return f"{part_id}:pin"


def _is_ucc21710_gate_short(rule_type, ep_a, ep_b):
    if rule_type != "R_PATH":
        return False
    if ep_a.get("part_id") != "UCC21710" or ep_b.get("part_id") != "UCC21710":
        return False
    roles = {ep_a.get("pin_role"), ep_b.get("pin_role")}
    if "sense_minus" not in roles:
        return False
    return "out_plus" in roles or "out_minus" in roles


def _is_ucc27511_out_pair(rule_type, ep_a, ep_b):
    if rule_type != "R_PATH":
        return False
    if ep_a.get("part_id") != "UCC27511" or ep_b.get("part_id") != "UCC27511":
        return False
    roles = {ep_a.get("pin_role"), ep_b.get("pin_role")}
    return roles == {"out_plus", "out_minus"}


def _check_cap_rule(nets_a, nets_b, cap_pairs):
    shorted = False
    for net_a in nets_a:
        for net_b in nets_b:
            if net_a == net_b:
                shorted = True
                continue
            if frozenset([net_a, net_b]) in cap_pairs:
                return True, False, None
    if shorted and not _has_nonshort_pair(nets_a, nets_b):
        return False, True, _first_common(nets_a, nets_b)
    return False, False, None


def _check_path_rule(nets_a, nets_b, components):
    shorted = False
    for net_a in nets_a:
        for net_b in nets_b:
            if net_a == net_b:
                shorted = True
                continue
            if _nets_connected(net_a, net_b, components):
                return True, False, None
    if shorted and not _has_nonshort_pair(nets_a, nets_b):
        return False, True, _first_common(nets_a, nets_b)
    return False, False, None


def _nets_connected(net_a, net_b, components):
    for nets in components:
        if net_a in nets and net_b in nets:
            return True
    return False


def _has_nonshort_pair(nets_a, nets_b):
    return any(net_a != net_b for net_a in nets_a for net_b in nets_b)


def _first_common(nets_a, nets_b):
    for net in nets_a:
        if net in nets_b:
            return net
    return None


def _find_matching_link(std_link, gen_links, used):
    for idx, link in enumerate(gen_links):
        if idx in used:
            continue
        if not _drivers_compatible(std_link["driver"], link["driver"]):
            continue
        if not _gates_compatible(std_link["gate"], link["gate"]):
            continue
        if not _fingerprint_compatible(std_link["fingerprint"], link["fingerprint"]):
            continue
        return idx
    return None


def _drivers_compatible(std_driver, gen_driver):
    if std_driver.get("category") and gen_driver.get("category"):
        if std_driver.get("category") != gen_driver.get("category"):
            return False
    return _normalize_role(std_driver.get("pin_role")) == _normalize_role(
        gen_driver.get("pin_role")
    )


def _gates_compatible(std_gate, gen_gate):
    if std_gate.get("category") and gen_gate.get("category"):
        if std_gate.get("category") != gen_gate.get("category"):
            return False
    return std_gate.get("pin_role") == gen_gate.get("pin_role")


def _fingerprint_compatible(std_fp, gen_fp):
    if std_fp.get("dc_path") and not gen_fp.get("dc_path"):
        return False
    if std_fp.get("has_series_resistor") and not gen_fp.get("has_series_resistor"):
        return False
    if std_fp.get("has_shunt_cap") and not gen_fp.get("has_shunt_cap"):
        return False
    return True


def _normalize_role(role):
    if not role:
        return role
    if role in ("out_plus", "out_minus"):
        return "out"
    return role

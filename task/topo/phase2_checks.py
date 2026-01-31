from collections import deque

from .build_topology import index_snapshot
from . import passive_collapse

GATE_FLOAT_TASKS = {8, 9, 10, 11, 12}
STRICT_HALFBRIDGE_TASKS = {8, 9, 10, 11, 12}
KS_SOURCE_RLC_TASKS = {9, 10, 11}


def run_phase2_checks(snapshot, kg_store, task_id=None):
    errors = []
    errors.extend(_check_constraints(snapshot, kg_store, task_id=task_id))
    errors.extend(_check_acs37010_ip_short(snapshot))
    errors.extend(_check_mgj2d_vin_short(snapshot))
    if task_id == 6:
        errors.extend(_check_tps54302_diode_pairs(snapshot))
    if task_id in STRICT_HALFBRIDGE_TASKS:
        errors.extend(_check_mosfet_pins_connected(snapshot))
        errors.extend(_check_kelvin_source_distinct(snapshot))
        errors.extend(_check_vbus_decoupling_caps(snapshot))
    if task_id in KS_SOURCE_RLC_TASKS:
        errors.extend(_check_kelvin_source_rlc_isolation(snapshot))
    if task_id == 15:
        errors.extend(_check_ucc5390e_vin_minus(snapshot))
    if task_id == 13:
        errors.extend(_check_ucc27511_outputs(snapshot))
    return errors


def _check_constraints(snapshot, kg_store, task_id=None):
    errors = []
    index = index_snapshot(snapshot)
    nets = index["nets"]
    allow_gate_float = task_id in GATE_FLOAT_TASKS

    for comp in snapshot.get("components", []):
        part_id = comp.get("part_id", "")
        ref = comp.get("ref", "")
        constraints = kg_store.get_constraints(part_id) if kg_store else []
        if not constraints:
            continue

        for constraint in constraints:
            ctype = constraint.get("type")
            if ctype == "must_be_connected":
                pins = constraint.get("pins", [])
                for pin in pins:
                    pin_info = _find_pin(comp, pin)
                    if not pin_info:
                        continue
                    if not _is_connected(pin_info):
                        errors.append(f"{ref}: pin {pin} is unconnected")

            elif ctype == "supply_pair":
                vdd_pin = constraint.get("vdd_pin")
                gnd_pin = constraint.get("gnd_pin")
                vdd_info = _find_pin(comp, vdd_pin)
                gnd_info = _find_pin(comp, gnd_pin)
                if not vdd_info or not _is_connected(vdd_info):
                    errors.append(f"{ref}: supply pin {vdd_pin} missing net")
                if not gnd_info or not _is_connected(gnd_info):
                    errors.append(f"{ref}: ground pin {gnd_pin} missing net")
                if vdd_info and gnd_info:
                    vdd_net = vdd_info.get("net")
                    gnd_net = gnd_info.get("net")
                    if _is_connected(vdd_info) and _is_connected(gnd_info) and vdd_net == gnd_net:
                        errors.append(
                            f"{ref}: supply pair shorted ({vdd_pin} and {gnd_pin} on {vdd_net})"
                        )

            elif ctype == "differential_pair_must_be_distinct":
                pins = constraint.get("pins", [])
                if len(pins) >= 2:
                    pin_a = _find_pin(comp, pins[0])
                    pin_b = _find_pin(comp, pins[1])
                    if pin_a and pin_b:
                        net_a = pin_a.get("net")
                        net_b = pin_b.get("net")
                        if _is_connected(pin_a) and _is_connected(pin_b) and net_a == net_b:
                            errors.append(
                                f"{ref}: differential pins on same net ({pins[0]}={net_a})"
                            )

            elif ctype == "driving_pair":
                gate_pin = constraint.get("gate_pin")
                gate_info = _find_pin(comp, gate_pin)
                if gate_info and _is_connected(gate_info):
                    if not allow_gate_float:
                        net_name = gate_info.get("net")
                        endpoint_count = len(nets.get(net_name, {}).get("endpoints", []))
                        if endpoint_count <= 1:
                            errors.append(f"{ref}: gate net appears floating ({gate_pin} on {net_name})")
                else:
                    errors.append(f"{ref}: gate pin {gate_pin} missing net")

    errors.extend(_check_acs37010_vref(snapshot))
    errors.extend(_check_kelvin_source_short(snapshot))
    errors.extend(_check_bootstrap_caps(snapshot))
    errors.extend(_check_ucc5390e_output_resistor(snapshot))

    return errors


def _check_acs37010_vref(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "ACS37010":
            continue
        ref = comp.get("ref", "")
        vref_info = _find_pin(comp, "VREF")
        gnd_info = _find_pin(comp, "GND")
        if not vref_info or not gnd_info:
            continue
        vref_net = vref_info.get("net")
        gnd_net = gnd_info.get("net")
        if vref_net and gnd_net and vref_net == gnd_net:
            errors.append(f"{ref}: VREF should not be tied to GND")
    return errors


def _check_acs37010_ip_short(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "ACS37010":
            continue
        ref = comp.get("ref", "")
        ipp_info = _find_pin(comp, "IP+")
        ipm_info = _find_pin(comp, "IP-")
        if not ipp_info or not ipm_info:
            continue
        if _is_connected(ipp_info) and _is_connected(ipm_info):
            net_p = ipp_info.get("net")
            net_m = ipm_info.get("net")
            if net_p == net_m:
                errors.append(f"{ref}: IP+ and IP- must not be shorted ({net_p})")
    return errors


def _check_mgj2d_vin_short(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "MGJ2D121505SC":
            continue
        ref = comp.get("ref", "")
        vplus = _find_pin(comp, "+VIN")
        vminus = _find_pin(comp, "-VIN")
        if not vplus or not vminus:
            continue
        if _is_connected(vplus) and _is_connected(vminus):
            net_p = vplus.get("net")
            net_m = vminus.get("net")
            if net_p == net_m:
                errors.append(f"{ref}: +VIN and -VIN must not be shorted ({net_p})")
    return errors


def _check_tps54302_diode_pairs(snapshot):
    errors = []
    diode_pairs = set()
    for comp in snapshot.get("components", []):
        if not _is_passive_type(comp, "D"):
            continue
        nets = [pin.get("net") for pin in comp.get("pins", []) if _is_connected(pin)]
        if len(nets) != 2:
            continue
        net_a, net_b = nets
        if net_a and net_b:
            diode_pairs.add(tuple(sorted([net_a, net_b])))

    if not diode_pairs:
        return errors

    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "TPS54302":
            continue
        ref = comp.get("ref", "")
        for pin_a, pin_b in (("1", "2"), ("2", "3"), ("1", "6")):
            pin_a_info = _find_pin(comp, pin_a)
            pin_b_info = _find_pin(comp, pin_b)
            if not pin_a_info or not pin_b_info:
                continue
            if not (_is_connected(pin_a_info) and _is_connected(pin_b_info)):
                continue
            net_a = pin_a_info.get("net")
            net_b = pin_b_info.get("net")
            if not net_a or not net_b:
                continue
            if tuple(sorted([net_a, net_b])) in diode_pairs:
                errors.append(
                    f"{ref}: diode detected between pins {pin_a} and {pin_b} "
                    f"({net_a} <-> {net_b})"
                )
    return errors


def _check_kelvin_source_short(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        ref = comp.get("ref", "")
        kelvin_pins = [
            pin for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source"
        ]
        for pin in kelvin_pins:
            net = pin.get("net")
            if not net or str(net).upper() == "NC":
                errors.append(f"{ref}: kelvin source pin must be connected to a net")
        source_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_source" and pin.get("net")
        }
        kelvin_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source" and pin.get("net")
        }
        if not source_nets or not kelvin_nets:
            continue
        if source_nets & kelvin_nets:
            net = sorted(source_nets & kelvin_nets)[0]
            errors.append(f"{ref}: kelvin source should not be shorted to source net ({net})")
    return errors


def _check_kelvin_source_distinct(snapshot):
    errors = []
    ks_by_ref = {}
    for comp in snapshot.get("components", []):
        if comp.get("category") != "MOSFET":
            continue
        ref = comp.get("ref", "")
        ks_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source" and _is_connected(pin)
        }
        if not ks_nets:
            continue
        if len(ks_nets) > 1:
            errors.append(f"{ref}: kelvin source pins must be tied to a single net")
        ks_by_ref[ref] = ks_nets

    if len(ks_by_ref) < 2:
        return errors

    unique_nets = set()
    for nets in ks_by_ref.values():
        unique_nets.update(nets)

    if len(unique_nets) < len(ks_by_ref):
        errors.append("Kelvin source nets must be distinct between MOSFETs")
    return errors


def _check_kelvin_source_rlc_isolation(snapshot):
    errors = []
    graph = _build_bipartite_graph(snapshot)
    if not graph:
        return errors
    allowed = _allowed_rlc_nodes(snapshot, graph)
    for comp in snapshot.get("components", []):
        if comp.get("category") != "MOSFET":
            continue
        ref = comp.get("ref", "")
        ks_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_kelvin_source" and _is_connected(pin)
        }
        source_nets = {
            pin.get("net")
            for pin in comp.get("pins", [])
            if pin.get("pin_role") == "mosfet_source" and _is_connected(pin)
        }
        if not ks_nets or not source_nets:
            continue
        for ks_net in ks_nets:
            for source_net in source_nets:
                if ks_net == source_net:
                    errors.append(
                        f"{ref}: kelvin source must not connect to source net ({ks_net})"
                    )
                    break
                if _has_rlc_path(graph, allowed, ks_net, source_net):
                    errors.append(
                        f"{ref}: kelvin source must not connect to source net via R/L/C network "
                        f"({ks_net} <-> {source_net})"
                    )
                    break
            if errors and errors[-1].startswith(f"{ref}:"):
                break
    return errors


def _build_bipartite_graph(snapshot):
    graph = {}
    for comp in snapshot.get("components", []):
        comp_ref = comp.get("ref")
        if not comp_ref:
            continue
        comp_node = f"comp:{comp_ref}"
        graph.setdefault(comp_node, set())
        for pin in comp.get("pins", []):
            net_name = pin.get("net")
            if not net_name:
                continue
            net_node = f"net:{net_name}"
            graph.setdefault(net_node, set())
            graph[comp_node].add(net_node)
            graph[net_node].add(comp_node)
    return graph


def _allowed_rlc_nodes(snapshot, graph):
    allowed = {node for node in graph if node.startswith("net:")}
    for comp in snapshot.get("components", []):
        comp_ref = comp.get("ref")
        if not comp_ref:
            continue
        if any(_is_passive_type(comp, p) for p in ("R", "L", "C")):
            allowed.add(f"comp:{comp_ref}")
    return allowed


def _has_rlc_path(graph, allowed, start_net, end_net):
    start = f"net:{start_net}"
    end = f"net:{end_net}"
    if start not in graph or end not in graph:
        return False
    q = deque([start])
    visited = {start}
    while q:
        node = q.popleft()
        if node == end:
            return True
        for nb in graph.get(node, []):
            if nb in visited or nb not in allowed:
                continue
            visited.add(nb)
            q.append(nb)
    return False


def _check_mosfet_pins_connected(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("category") != "MOSFET":
            continue
        ref = comp.get("ref", "")
        for pin in comp.get("pins", []):
            net = pin.get("net")
            if not net or str(net).upper() in {"NC", "__NOCONNECT"}:
                pin_id = pin.get("pin_id") or pin.get("pin_name") or "?"
                errors.append(f"{ref}: pin {pin_id} is unconnected (MOSFET pins must all connect)")
                break
    return errors


def _check_vbus_decoupling_caps(snapshot):
    errors = []
    allowed_ground = {"GND", "PGND"}
    for comp in snapshot.get("components", []):
        if not _is_passive_type(comp, "C"):
            continue
        ref = comp.get("ref", "")
        nets = {pin.get("net") for pin in comp.get("pins", []) if _is_connected(pin)}
        nets_upper = {str(net).upper() for net in nets}
        if len(nets_upper) != 2:
            errors.append(f"{ref}: decoupling cap must connect between VBUS+ and GND/PGND")
            continue
        if "VBUS+" not in nets_upper:
            errors.append(f"{ref}: decoupling cap must connect between VBUS+ and GND/PGND")
            continue
        other = [n for n in nets_upper if n != "VBUS+"]
        if not other or other[0] not in allowed_ground:
            errors.append(f"{ref}: decoupling cap must connect between VBUS+ and GND/PGND")
    return errors


def _check_ucc27511_outputs(snapshot):
    errors = []
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "UCC27511":
            continue
        ref = comp.get("ref", "")
        for label in ("OUTH", "OUTL"):
            pin_info = _find_pin(comp, label)
            if not pin_info or not _is_connected(pin_info):
                errors.append(f"{ref}: {label} must be connected")
                continue
            net = str(pin_info.get("net", "")).upper()
            if net in {"GND", "PGND"}:
                errors.append(f"{ref}: {label} must not be tied to GND/PGND ({pin_info.get('net')})")
    return errors


def _check_bootstrap_caps(snapshot):
    errors = []
    capacitors = []
    for comp in snapshot.get("components", []):
        if _is_passive_type(comp, "C"):
            nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
            capacitors.append(nets)

    for comp in snapshot.get("components", []):
        hb_info = _find_pin_by_role(comp, "halfbridge_hb")
        hs_info = _find_pin_by_role(comp, "halfbridge_hs")
        if not hb_info or not hs_info:
            continue
        hb_net = hb_info.get("net")
        hs_net = hs_info.get("net")
        if not hb_net or not hs_net:
            continue
        if not _has_cap_between(capacitors, hb_net, hs_net):
            ref = comp.get("ref", "")
            errors.append(f"{ref}: bootstrap capacitor missing between HB and HS")
    return errors


def _check_ucc5390e_output_resistor(snapshot):
    errors = []
    resistor_nets = []
    for comp in snapshot.get("components", []):
        if _is_passive_type(comp, "R"):
            nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
            resistor_nets.append(nets)

    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "UCC5390E":
            continue
        out_info = _find_pin(comp, "OUT")
        if not out_info or not out_info.get("net"):
            continue
        out_net = out_info.get("net")
        if not any(out_net in nets for nets in resistor_nets):
            ref = comp.get("ref", "")
            errors.append(f"{ref}: output resistor missing on OUT net ({out_net})")
    return errors


def _check_ucc5390e_vin_minus(snapshot):
    errors = []
    index = index_snapshot(snapshot)
    nets = index["nets"]
    for comp in snapshot.get("components", []):
        if comp.get("part_id") != "UCC5390E":
            continue
        ref = comp.get("ref", "")
        pin_info = _find_pin(comp, "VEE2") or _find_pin(comp, "VIN-")
        if not pin_info:
            continue
        if not _is_connected(pin_info):
            errors.append(f"{ref}: VEE2 (VIN-) must be connected")
            continue
        net_name = pin_info.get("net")
        endpoint_count = len(nets.get(net_name, {}).get("endpoints", []))
        if endpoint_count <= 1:
            errors.append(f"{ref}: VEE2 (VIN-) net appears floating ({net_name})")
    return errors


def _find_pin_by_role(comp, role):
    for pin in comp.get("pins", []):
        if pin.get("pin_role") == role:
            return pin
    return None


def _is_passive_type(comp, passive_type):
    part_id = (comp.get("part_id") or "").strip()
    ref = (comp.get("ref") or "").strip()
    category = comp.get("category", "")
    if part_id == passive_type:
        return True
    if category != "passive":
        return False
    prefix = ref[:1].upper()
    return prefix == passive_type


def _has_cap_between(capacitors, net_a, net_b):
    for nets in capacitors:
        if net_a in nets and net_b in nets:
            return True
    return False


def _find_pin(comp, pin_key):
    pin_key = str(pin_key)
    for pin in comp.get("pins", []):
        if str(pin.get("pin_id", "")) == pin_key:
            return pin
        if str(pin.get("pin_name", "")) == pin_key:
            return pin
    return None


def _is_connected(pin_info):
    net = pin_info.get("net")
    if not net:
        return False
    if str(net).upper() in {"NC", "__NOCONNECT"}:
        return False
    return True

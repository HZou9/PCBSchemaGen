from collections import deque

DRIVER_OUT_ROLES = {
    "out",
    "out_plus",
    "out_minus",
    "gate_ho",
    "gate_lo",
    "logic_out",
}

GND_ROLES = {"supply_gnd", "mosfet_source", "mosfet_kelvin_source"}


def classify_passive(component):
    part_id = (component.get("part_id") or "").strip()
    ref = (component.get("ref") or "").strip()
    category = component.get("category", "")

    if part_id in ("R", "C", "L", "D"):
        return part_id
    if category != "passive":
        return None

    prefix = ref[:1].upper()
    if prefix in ("R", "C", "L", "D"):
        return prefix
    return None


def build_bipartite_graph(snapshot):
    graph = {}
    net_nodes = set()
    comp_nodes = set()

    for comp in snapshot.get("components", []):
        comp_ref = comp.get("ref")
        comp_node = f"comp:{comp_ref}"
        comp_nodes.add(comp_node)
        graph.setdefault(comp_node, set())
        for pin in comp.get("pins", []):
            net_name = pin.get("net")
            if not net_name:
                continue
            net_node = f"net:{net_name}"
            net_nodes.add(net_node)
            graph.setdefault(net_node, set())
            graph[comp_node].add(net_node)
            graph[net_node].add(comp_node)

    return graph, net_nodes, comp_nodes


def compute_driver_gate_links(snapshot):
    graph, net_nodes, _ = build_bipartite_graph(snapshot)
    nets_by_name = {n.get("name"): n for n in snapshot.get("nets", [])}

    drivers = []
    gates = []

    for comp in snapshot.get("components", []):
        category = comp.get("category")
        for pin in comp.get("pins", []):
            role = pin.get("pin_role")
            if role in DRIVER_OUT_ROLES and pin.get("net"):
                drivers.append(
                    {
                        "ref": comp.get("ref"),
                        "part_id": comp.get("part_id"),
                        "category": category,
                        "pin_role": role,
                        "net": pin.get("net"),
                    }
                )
            if pin.get("pin_role") == "mosfet_gate" and pin.get("net"):
                gates.append(
                    {
                        "ref": comp.get("ref"),
                        "part_id": comp.get("part_id"),
                        "category": category,
                        "pin_role": "mosfet_gate",
                        "net": pin.get("net"),
                    }
                )

    links = []
    for driver in drivers:
        for gate in gates:
            if driver["net"] == gate["net"]:
                fp = _fingerprint_for_connection(snapshot, driver["net"], gate["net"], graph)
                links.append(
                    {
                        "driver": driver,
                        "gate": gate,
                        "fingerprint": fp,
                    }
                )
                continue

            start = f"net:{driver['net']}"
            end = f"net:{gate['net']}"
            if start not in graph or end not in graph:
                continue
            if not _path_exists(graph, start, end, snapshot, allow_caps=True):
                continue
            fp = _fingerprint_for_connection(snapshot, driver["net"], gate["net"], graph)
            links.append(
                {
                    "driver": driver,
                    "gate": gate,
                    "fingerprint": fp,
                }
            )

    return links


def _path_exists(graph, start, end, snapshot, allow_caps=True):
    allowed = _allowed_nodes(snapshot, allow_caps=allow_caps)
    q = deque([start])
    visited = {start}
    while q:
        node = q.popleft()
        if node == end:
            return True
        for nb in graph.get(node, []):
            if nb in visited:
                continue
            if nb not in allowed:
                continue
            visited.add(nb)
            q.append(nb)
    return False


def _allowed_nodes(snapshot, allow_caps=True):
    allowed = set()
    for comp in snapshot.get("components", []):
        comp_ref = comp.get("ref")
        comp_node = f"comp:{comp_ref}"
        passive_type = classify_passive(comp)
        if passive_type is None:
            continue
        if passive_type == "C" and not allow_caps:
            continue
        allowed.add(comp_node)
    for net in snapshot.get("nets", []):
        allowed.add(f"net:{net.get('name')}")
    return allowed


def _fingerprint_for_connection(snapshot, start_net, end_net, graph):
    passive_nodes = _collect_passive_nodes(snapshot, start_net, end_net, graph)
    has_resistor = False
    has_diode = False
    diode_direction = "unknown"
    has_shunt_cap = False

    dc_path = _path_exists(graph, f"net:{start_net}", f"net:{end_net}", snapshot, allow_caps=False)

    ref_nets = _reference_nets(snapshot)

    diode_dirs = set()
    for comp in snapshot.get("components", []):
        comp_ref = comp.get("ref")
        comp_node = f"comp:{comp_ref}"
        if comp_node not in passive_nodes:
            continue
        ptype = classify_passive(comp)
        if ptype == "R":
            has_resistor = True
        if ptype == "D":
            has_diode = True
            direction = _diode_direction(comp, start_net, end_net, graph, snapshot)
            if direction:
                diode_dirs.add(direction)
        if ptype == "C":
            if _capacitor_shunts_gate(comp, end_net, ref_nets):
                has_shunt_cap = True

    if len(diode_dirs) == 1:
        diode_direction = diode_dirs.pop()
    elif len(diode_dirs) > 1:
        diode_direction = "mixed"

    return {
        "dc_path": dc_path,
        "has_series_resistor": has_resistor,
        "has_diode": has_diode,
        "diode_direction": diode_direction,
        "has_shunt_cap": has_shunt_cap,
    }


def _collect_passive_nodes(snapshot, start_net, end_net, graph):
    allowed = _allowed_nodes(snapshot, allow_caps=True)
    start = f"net:{start_net}"
    end = f"net:{end_net}"
    q = deque([start])
    visited = {start}
    passives = set()

    while q:
        node = q.popleft()
        if node == end:
            continue
        for nb in graph.get(node, []):
            if nb in visited:
                continue
            if nb not in allowed:
                continue
            visited.add(nb)
            if nb.startswith("comp:"):
                passives.add(nb)
            q.append(nb)

    return passives


def _reference_nets(snapshot):
    refs = set()
    for net in snapshot.get("nets", []):
        name = net.get("name")
        if str(name).upper() == "GND":
            refs.add(name)
        for ep in net.get("endpoints", []):
            if ep.get("pin_role") in GND_ROLES:
                refs.add(name)
    return refs


def _capacitor_shunts_gate(comp, gate_net, ref_nets):
    nets = {pin.get("net") for pin in comp.get("pins", []) if pin.get("net")}
    if gate_net not in nets:
        return False
    for net in nets:
        if net in ref_nets:
            return True
    return False


def _diode_direction(comp, start_net, end_net, graph, snapshot):
    anode_net = None
    cathode_net = None
    for pin in comp.get("pins", []):
        name = (pin.get("pin_name") or "").upper()
        role = pin.get("pin_role")
        if name == "A" or role == "diode_anode":
            anode_net = pin.get("net")
        if name == "K" or role == "diode_cathode":
            cathode_net = pin.get("net")

    if not anode_net or not cathode_net:
        return None

    dist_a_start = _shortest_path_len(graph, f"net:{start_net}", f"net:{anode_net}", snapshot)
    dist_k_start = _shortest_path_len(graph, f"net:{start_net}", f"net:{cathode_net}", snapshot)
    dist_a_end = _shortest_path_len(graph, f"net:{end_net}", f"net:{anode_net}", snapshot)
    dist_k_end = _shortest_path_len(graph, f"net:{end_net}", f"net:{cathode_net}", snapshot)

    if dist_a_start is None or dist_k_start is None or dist_a_end is None or dist_k_end is None:
        return None

    if dist_a_start <= dist_k_start and dist_k_end <= dist_a_end:
        return "forward"
    if dist_k_start <= dist_a_start and dist_a_end <= dist_k_end:
        return "reverse"
    return "unknown"


def _shortest_path_len(graph, start, end, snapshot):
    allowed = _allowed_nodes(snapshot, allow_caps=True)
    q = deque([(start, 0)])
    visited = {start}
    while q:
        node, dist = q.popleft()
        if node == end:
            return dist
        for nb in graph.get(node, []):
            if nb in visited:
                continue
            if nb not in allowed and nb != end:
                continue
            visited.add(nb)
            q.append((nb, dist + 1))
    return None

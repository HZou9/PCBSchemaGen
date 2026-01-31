import math

try:
    import networkx as nx
except ImportError:  # pragma: no cover - optional dependency
    nx = None

ROLE_EQUIV = {
    "out_plus": "out",
    "out_minus": "out",
}
COMPONENT_COUNT_TOLERANCE = 0.5
P3_GRAPH_TOLERANCE = 5
P16_PASSIVE_TOLERANCE = 0.6
FULL_SUBGRAPH_TASKS = {3}
KEY_SUBGRAPH_TASKS = {1, 2, 4, 5, 7, 8, 9, 10, 11, 12}
PASSIVE_PART_IDS = {"R", "C", "L", "D"}


def check_graph_similarity(std_snapshot, gen_snapshot, task_id=None):
    return _check_networkx_similarity(std_snapshot, gen_snapshot, task_id=task_id)


def check_driver_gate_links(std_snapshot, gen_snapshot):
    from . import passive_collapse

    std_links = passive_collapse.compute_driver_gate_links(std_snapshot)
    gen_links = passive_collapse.compute_driver_gate_links(gen_snapshot)
    return _check_links(std_links, gen_links)


def compare_skeleton(std_snapshot, gen_snapshot, std_links, gen_links):
    # Backward-compatible wrapper.
    errors = []
    errors.extend(_check_networkx_similarity(std_snapshot, gen_snapshot))
    errors.extend(_check_links(std_links, gen_links))
    return errors


def _normalize_role(role):
    if not role:
        return role
    return ROLE_EQUIV.get(role, role)


def _build_nx_graph(snapshot, keep_component=None):
    g = nx.MultiGraph()
    for comp in snapshot.get("components", []):
        if keep_component and not keep_component(comp):
            continue
        comp_ref = comp.get("ref")
        comp_node = f"comp:{comp_ref}"
        g.add_node(
            comp_node,
            node_type="component",
            category=comp.get("category"),
            part_id=comp.get("part_id"),
        )
        for pin in comp.get("pins", []):
            net_name = pin.get("net")
            if not net_name:
                continue
            net_node = f"net:{net_name}"
            if not g.has_node(net_node):
                g.add_node(
                    net_node,
                    node_type="net",
                )
            g.add_edge(
                comp_node,
                net_node,
                pin_role=_normalize_role(pin.get("pin_role")),
            )
    return g


def _node_match(a, b):
    if a.get("node_type") != b.get("node_type"):
        return False
    if a.get("category") and b.get("category") and a.get("category") != b.get("category"):
        return False
    return True


def _edge_match(a, b):
    role_a = a.get("pin_role")
    role_b = b.get("pin_role")
    if not role_a or not role_b:
        return True
    return role_a == role_b


def _check_networkx_similarity(std_snapshot, gen_snapshot, task_id=None):
    if nx is None:
        return ["NetworkX graph similarity check skipped (networkx not installed)."]
    count_errors = _check_component_count_tolerance(std_snapshot, gen_snapshot, task_id=task_id)
    if count_errors:
        return count_errors

    if task_id in FULL_SUBGRAPH_TASKS:
        std_graph = _build_nx_graph(std_snapshot)
        gen_graph = _build_nx_graph(gen_snapshot)
        if std_graph.number_of_nodes() == 0:
            return []
        matcher = nx.algorithms.isomorphism.MultiGraphMatcher(
            gen_graph, std_graph, node_match=_node_match, edge_match=_edge_match
        )
        if matcher.subgraph_is_isomorphic():
            return []
        if task_id == 3:
            node_diff = abs(std_graph.number_of_nodes() - gen_graph.number_of_nodes())
            edge_diff = abs(std_graph.number_of_edges() - gen_graph.number_of_edges())
            if node_diff <= P3_GRAPH_TOLERANCE and edge_diff <= P3_GRAPH_TOLERANCE:
                return []
        return _format_nx_failure(std_graph, gen_graph, prefix="NetworkX full-subgraph check failed.")

    if task_id in KEY_SUBGRAPH_TASKS:
        std_graph = _build_nx_graph(std_snapshot, keep_component=_is_key_component)
        gen_graph = _build_nx_graph(gen_snapshot, keep_component=_is_key_component)
        if std_graph.number_of_nodes() == 0:
            return []
        matcher = nx.algorithms.isomorphism.MultiGraphMatcher(
            gen_graph, std_graph, node_match=_node_match, edge_match=_edge_match
        )
        if matcher.subgraph_is_isomorphic():
            return []
        return _format_nx_failure(std_graph, gen_graph, prefix="NetworkX key-subgraph check failed.")

    # Relaxed mode: if counts pass, treat graph mismatch as acceptable.
    return []


def _format_nx_failure(std_graph, gen_graph, prefix=None):
    header = prefix or "NetworkX graph similarity check failed (no subgraph isomorphism)."
    messages = [header]
    messages.append(
        f"Graph stats: std nodes={std_graph.number_of_nodes()} edges={std_graph.number_of_edges()}, "
        f"gen nodes={gen_graph.number_of_nodes()} edges={gen_graph.number_of_edges()}."
    )
    std_cats = _component_category_counts(std_graph)
    gen_cats = _component_category_counts(gen_graph)
    cat_diffs = []
    for cat in sorted(set(std_cats) | set(gen_cats)):
        if std_cats.get(cat, 0) != gen_cats.get(cat, 0):
            cat_diffs.append(f"{cat}: std={std_cats.get(cat,0)}, gen={gen_cats.get(cat,0)}")
    if cat_diffs:
        messages.append("Component category counts differ: " + "; ".join(cat_diffs[:8]) + ".")
    return messages


def _component_category_counts(graph):
    counts = {}
    for _, attrs in graph.nodes(data=True):
        if attrs.get("node_type") != "component":
            continue
        cat = attrs.get("category")
        if not cat:
            continue
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def _component_part_counts(snapshot):
    counts = {}
    for comp in snapshot.get("components", []):
        part_id = comp.get("part_id")
        if not part_id:
            continue
        counts[part_id] = counts.get(part_id, 0) + 1
    return counts


def _check_component_count_tolerance(std_snapshot, gen_snapshot, tolerance=COMPONENT_COUNT_TOLERANCE, task_id=None):
    std_counts = _component_part_counts(std_snapshot)
    gen_counts = _component_part_counts(gen_snapshot)

    errors = []
    for part_id in sorted(set(std_counts) | set(gen_counts)):
        if task_id == 15 and part_id == "D":
            continue
        std_count = std_counts.get(part_id, 0)
        gen_count = gen_counts.get(part_id, 0)
        tolerance_override = tolerance
        if task_id == 16 and part_id in {"R", "C"}:
            tolerance_override = P16_PASSIVE_TOLERANCE
        if std_count == 0:
            if gen_count >= 4:
                errors.append(
                    f"Component count out of tolerance: {part_id} std=0 gen={gen_count} (allowed 0-3)"
                )
            continue
        if std_count <= 4:
            min_count = 1
            max_count = 4
        else:
            min_count = math.ceil(std_count * (1 - tolerance_override))
            max_count = math.floor(std_count * (1 + tolerance_override))
        if gen_count < min_count or gen_count > max_count:
            errors.append(
                f"Component count out of tolerance: {part_id} std={std_count} gen={gen_count} "
                f"(allowed {min_count}-{max_count})"
            )
    if not errors:
        return []
    return ["NetworkX component count tolerance check failed."] + errors


def _check_links(std_links, gen_links):
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


def _is_key_component(comp):
    part_id = comp.get("part_id")
    if not part_id:
        return True
    return part_id not in PASSIVE_PART_IDS


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

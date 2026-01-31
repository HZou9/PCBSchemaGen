"""
Isolation domain identification for complex PCB circuits.

This module identifies isolation domains in a circuit by analyzing
components with isolation boundaries (transformers, isolated DC-DC converters,
isolated gate drivers).
"""

from collections import deque


def identify_isolation_domains(snapshot, kg_store):
    """
    Identify isolation domains in a circuit.

    Returns:
        dict: {
            'primary': set of net names in primary domain,
            'secondary': list of sets, each containing net names in a secondary domain
        }
    """
    # Find all isolation boundary components
    iso_components = _find_isolation_components(snapshot, kg_store)

    if not iso_components:
        # No isolation boundaries - everything is in primary domain
        all_nets = {net['name'] for net in snapshot.get('nets', [])}
        return {'primary': all_nets, 'secondary': []}

    # Build net adjacency graph (excluding isolation boundaries)
    net_graph = _build_net_graph(snapshot, iso_components)

    # Find primary domain by BFS from anchor nets (VIN, VBUS, etc.)
    primary_nets = _find_primary_domain(snapshot, net_graph, iso_components)

    # Find secondary domains by BFS from secondary pins of each isolation component
    secondary_domains = _find_secondary_domains(snapshot, net_graph, iso_components, primary_nets)

    return {'primary': primary_nets, 'secondary': secondary_domains}


def _find_isolation_components(snapshot, kg_store):
    """Find components with isolation boundaries."""
    iso_components = []

    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '')
        comp_info = kg_store.get_component(part_id) if kg_store else None

        if comp_info and comp_info.get('isolation_boundary'):
            iso_components.append({
                'ref': comp.get('ref'),
                'part_id': part_id,
                'primary_pins': set(comp_info.get('primary_pins', [])),
                'secondary_pins': set(comp_info.get('secondary_pins', [])),
                'pins': comp.get('pins', [])
            })

    return iso_components


def _build_net_graph(snapshot, iso_components):
    """
    Build a graph where nets are connected if they share a component
    (excluding isolation boundary crossings).
    """
    # Map ref -> iso_component info
    iso_refs = {ic['ref']: ic for ic in iso_components}

    # Map net_name -> set of connected net names
    net_graph = {}

    # Map ref -> list of (pin_num, net_name)
    comp_pins = {}
    for net in snapshot.get('nets', []):
        net_name = net.get('name')
        if net_name not in net_graph:
            net_graph[net_name] = set()

        for endpoint in net.get('endpoints', []):
            ref = endpoint.get('ref')
            pin_id = endpoint.get('pin_id')
            if ref not in comp_pins:
                comp_pins[ref] = []
            comp_pins[ref].append((pin_id, net_name))

    # Connect nets through components
    for ref, pins in comp_pins.items():
        if ref in iso_refs:
            # For isolation components, only connect within same side
            iso_comp = iso_refs[ref]
            primary_pins = iso_comp['primary_pins']
            secondary_pins = iso_comp['secondary_pins']

            primary_nets = [net for pin, net in pins if _pin_in_set(pin, primary_pins)]
            secondary_nets = [net for pin, net in pins if _pin_in_set(pin, secondary_pins)]

            # Connect primary nets to each other
            for i, net1 in enumerate(primary_nets):
                for net2 in primary_nets[i+1:]:
                    net_graph.setdefault(net1, set()).add(net2)
                    net_graph.setdefault(net2, set()).add(net1)

            # Connect secondary nets to each other
            for i, net1 in enumerate(secondary_nets):
                for net2 in secondary_nets[i+1:]:
                    net_graph.setdefault(net1, set()).add(net2)
                    net_graph.setdefault(net2, set()).add(net1)
        else:
            # For regular components, all pins' nets are connected
            nets = [net for _, net in pins]
            for i, net1 in enumerate(nets):
                for net2 in nets[i+1:]:
                    net_graph.setdefault(net1, set()).add(net2)
                    net_graph.setdefault(net2, set()).add(net1)

    return net_graph


def _pin_in_set(pin_id, pin_set):
    """Check if pin_id is in the pin set (handles string/int conversion)."""
    try:
        pin_num = int(pin_id)
        return pin_num in pin_set
    except (ValueError, TypeError):
        return str(pin_id) in {str(p) for p in pin_set}


def _find_primary_domain(snapshot, net_graph, iso_components):
    """
    Find primary domain nets using BFS from anchor nets.
    Anchor nets are typically: VIN, VBUS, VBUS_P, VCC, and primary-side GNDs.
    """
    # Look for anchor nets
    anchor_patterns = ['VIN', 'VBUS', 'VCC', 'V12', 'V5', 'GND_PRI', 'PGND']

    # Find starting nets
    start_nets = set()
    for net in snapshot.get('nets', []):
        net_name = net.get('name', '').upper()
        for pattern in anchor_patterns:
            if pattern in net_name:
                start_nets.add(net['name'])
                break

    # If no anchors found, start from first net with "VIN" or just first net
    if not start_nets:
        for net in snapshot.get('nets', []):
            if 'VIN' in net.get('name', '').upper():
                start_nets.add(net['name'])
                break

    if not start_nets and snapshot.get('nets'):
        start_nets.add(snapshot['nets'][0]['name'])

    # BFS to find all connected nets
    return _bfs_connected_nets(start_nets, net_graph)


def _bfs_connected_nets(start_nets, net_graph):
    """BFS to find all nets connected to start_nets."""
    visited = set()
    queue = deque(start_nets)

    while queue:
        net = queue.popleft()
        if net in visited:
            continue
        visited.add(net)

        for neighbor in net_graph.get(net, []):
            if neighbor not in visited:
                queue.append(neighbor)

    return visited


def _find_secondary_domains(snapshot, net_graph, iso_components, primary_nets):
    """Find secondary domains starting from isolation component secondary pins."""
    secondary_domains = []
    all_visited = primary_nets.copy()

    for iso_comp in iso_components:
        # Find nets connected to secondary pins
        sec_start_nets = set()
        for pin in iso_comp.get('pins', []):
            pin_id = pin.get('pin_id')
            if _pin_in_set(pin_id, iso_comp['secondary_pins']):
                net_name = pin.get('net')
                if net_name and net_name not in all_visited:
                    sec_start_nets.add(net_name)

        if sec_start_nets:
            # BFS from secondary pins
            domain = _bfs_connected_nets(sec_start_nets, net_graph)
            domain -= all_visited  # Remove already visited nets
            if domain:
                secondary_domains.append(domain)
                all_visited.update(domain)

    return secondary_domains


def get_net_domain(net_name, domains):
    """
    Get which domain a net belongs to.

    Returns:
        str: 'primary', 'secondary_0', 'secondary_1', etc., or 'unknown'
    """
    if net_name in domains.get('primary', set()):
        return 'primary'

    for i, sec_domain in enumerate(domains.get('secondary', [])):
        if net_name in sec_domain:
            return f'secondary_{i}'

    return 'unknown'


def check_isolation_boundary_violations(snapshot, kg_store):
    """
    Check for direct connections across isolation boundaries.

    Returns:
        list: Error messages for any violations found
    """
    errors = []

    iso_components = _find_isolation_components(snapshot, kg_store)

    for iso_comp in iso_components:
        ref = iso_comp['ref']
        primary_pins = iso_comp['primary_pins']
        secondary_pins = iso_comp['secondary_pins']

        # Get nets connected to primary and secondary sides
        primary_nets = set()
        secondary_nets = set()

        for pin in iso_comp.get('pins', []):
            pin_id = pin.get('pin_id')
            net_name = pin.get('net')
            if not net_name or net_name == 'NC':
                continue

            if _pin_in_set(pin_id, primary_pins):
                primary_nets.add(net_name)
            elif _pin_in_set(pin_id, secondary_pins):
                secondary_nets.add(net_name)

        # Check for overlap (direct short across isolation)
        overlap = primary_nets & secondary_nets
        if overlap:
            for net in overlap:
                errors.append(
                    f"{ref}: Net '{net}' connects both primary and secondary sides "
                    f"(isolation barrier violation)"
                )

    return errors

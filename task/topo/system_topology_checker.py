"""
System topology checker for complex PCB circuits.

This module verifies system-level topology requirements for complex tasks
like synchronous buck/boost converters, DAB, LLC, motor drives, etc.

Uses graph-based verification to check actual power stage connections,
not just component counts.
"""

from .build_topology import index_snapshot
from collections import deque


# Task templates defining expected component counts and topology patterns
TASK_TEMPLATES = {
    17: {  # CONV_BUCK_SYNC
        'name': 'Synchronous Buck Converter',
        'min_mosfets': 2,
        'min_gate_drivers': 2,
        'min_isolated_supplies': 1,
        'requires_inductor': True,
        'min_output_caps': 4,
        'topology_type': 'sync_buck',
    },
    18: {  # CONV_BOOST_SYNC
        'name': 'Synchronous Boost Converter',
        'min_mosfets': 2,
        'min_gate_drivers': 2,
        'min_isolated_supplies': 1,
        'requires_inductor': True,
        'min_output_caps': 4,
        'topology_type': 'sync_boost',
    },
    19: {  # CONV_4SW_BUCKBOOST
        'name': '4-Switch Buck-Boost Converter',
        'min_mosfets': 4,
        'min_gate_drivers': 4,
        'min_isolated_supplies': 2,
        'topology_type': '4sw_buckboost',
    },
    20: {  # CONV_DAB_ISOLATED
        'name': 'Dual Active Bridge Converter',
        'min_mosfets': 8,
        'min_gate_drivers': 8,
        'min_isolated_supplies': 2,
        'requires_transformer': True,
        # Hard requirements: DAB primary series path must contain C_film + inductor (Inductor_power or L).
        'requires_blocking_cap': True,
        'requires_resonant_inductor': True,
        'topology_type': 'dab',
    },
    21: {  # CONV_LLC_RESONANT
        'name': 'LLC Resonant Converter',
        # Corrected: full-bridge on primary + full-bridge on secondary (DAB-like, with resonant tank requirement).
        'min_mosfets': 8,
        'min_gate_drivers': 8,
        'min_isolated_supplies': 2,
        'requires_transformer': True,
        'requires_resonant_cap': True,
        'requires_resonant_inductor': True,
        'topology_type': 'llc',
    },
    22: {  # DRIVE_3PH_MOTOR
        'name': '3-Phase Motor Drive',
        'min_mosfets': 6,
        'min_gate_drivers': 6,
        'min_isolated_supplies': 3,
        'topology_type': '3ph_inverter',
    },
    23: {  # INV_GRID_1PH
        'name': 'Single-Phase Grid Inverter',
        'min_mosfets': 4,
        'min_gate_drivers': 4,
        'min_isolated_supplies': 2,
        'topology_type': '1ph_fullbridge',
    },
}

# Component identification patterns
MOSFET_PATTERNS = ['IMZA', 'IMLT', 'IMT', 'IMW', 'BSC']
GATE_DRIVER_IDS = {'UCC5390E', 'UCC21710', 'UCC27211', 'UCC27511'}
ISOLATED_SUPPLY_IDS = {'MGJ2D121505SC'}
TRANSFORMER_IDS = {'transformer_PQ5050'}
FILM_CAP_IDS = {'C_film'}
POWER_INDUCTOR_IDS = {'Inductor_power'}
GENERIC_INDUCTOR_IDS = {'L'}

# Passive parts allowed for graph path checks (connectivity/tank presence).
PATH_PART_IDS = {'R', 'C', 'C_film', 'Inductor_power', 'L'}


def check_system_topology(snapshot, task_id, kg_store=None):
    """
    Check system-level topology for complex tasks.

    Returns:
        list: Error messages for any topology issues found
    """
    errors = []

    template = TASK_TEMPLATES.get(task_id)
    if not template:
        return []  # Not a complex task

    # Count components
    counts = _count_components(snapshot)

    # Check minimum component counts
    errors.extend(_check_component_counts(counts, template, task_id))

    # Check special requirements
    if template.get('requires_transformer'):
        if counts['transformers'] == 0:
            errors.append(
                f"Task {task_id} ({template['name']}) requires a transformer "
                f"but none found"
            )

    if template.get('requires_resonant_cap'):
        if counts['film_caps'] == 0:
            errors.append(
                f"Task {task_id} ({template['name']}) requires film capacitors "
                f"for resonant tank, but none found"
            )

    if template.get('requires_resonant_inductor'):
        if counts['power_inductors'] == 0 and counts['inductors'] == 0:
            errors.append(
                f"Task {task_id} ({template['name']}) requires power inductor "
                f"(Inductor_power or L) for resonant tank, but none found"
            )

    if template.get('requires_blocking_cap'):
        if counts['film_caps'] == 0:
            errors.append(
                f"Task {task_id} ({template['name']}) requires blocking capacitors "
                f"in series with transformer, but none found"
            )

    # Check inductor requirement
    if template.get('requires_inductor'):
        if counts['power_inductors'] == 0:
            errors.append(
                f"Task {task_id} ({template['name']}) requires a power inductor "
                f"but none found"
            )

    # Check output capacitor requirement
    if template.get('min_output_caps', 0) > 0:
        vout_cap_count = _count_output_caps(snapshot)
        if vout_cap_count < template['min_output_caps']:
            errors.append(
                f"Task {task_id} ({template['name']}) requires at least "
                f"{template['min_output_caps']} output capacitors, "
                f"but only {vout_cap_count} found on VOUT nets"
            )

    # Check VBUS decoupling
    errors.extend(_check_vbus_decoupling(snapshot, task_id))

    # ========================================================================
    # GRAPH-BASED TOPOLOGY VERIFICATION
    # ========================================================================
    topology_type = template.get('topology_type')
    if topology_type:
        topo_errors = _verify_power_topology(snapshot, topology_type, kg_store)
        errors.extend(topo_errors)

    return errors


def _verify_power_topology(snapshot, topology_type, kg_store):
    """
    Verify power stage topology using graph-based connection checking.

    This function extracts the power-stage subgraph and verifies it matches
    the expected topology pattern.
    """
    errors = []

    # Build power component graph
    power_graph = _build_power_graph(snapshot, kg_store)

    if topology_type == 'sync_buck':
        errors.extend(_verify_sync_buck(power_graph, snapshot))
    elif topology_type == 'sync_boost':
        errors.extend(_verify_sync_boost(power_graph, snapshot))
    elif topology_type == '4sw_buckboost':
        errors.extend(_verify_4sw_buckboost(power_graph, snapshot))
    elif topology_type == 'dab':
        errors.extend(_verify_dab(power_graph, snapshot))
    elif topology_type == 'llc':
        errors.extend(_verify_llc(power_graph, snapshot))
    elif topology_type == '3ph_inverter':
        errors.extend(_verify_3ph_inverter(power_graph, snapshot))
    elif topology_type == '1ph_fullbridge':
        errors.extend(_verify_1ph_fullbridge(power_graph, snapshot))

    return errors


def _build_power_graph(snapshot, kg_store):
    """
    Build a graph representation of the power stage.

    Returns:
        dict: {
            'mosfets': list of {ref, part_id, drain_net, source_net, gate_net, ks_net},
            'inductors': list of {ref, terminal_a_net, terminal_b_net},
            'transformers': list of {ref, pri1_net, pri2_net, sec1_net, sec2_net},
            'nets': dict of net_name -> list of (ref, pin_role)
        }
    """
    graph = {
        'mosfets': [],
        'inductors': [],
        'transformers': [],
        'nets': {},  # net_name -> [(ref, pin_role), ...]
    }

    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '')
        ref = comp.get('ref', '')
        part_id_upper = part_id.upper()

        # Check if MOSFET
        if any(p in part_id_upper for p in MOSFET_PATTERNS):
            mosfet_info = _extract_mosfet_connections(comp, kg_store)
            if mosfet_info:
                graph['mosfets'].append(mosfet_info)
                # Add to nets graph
                for pin_role, net_name in [
                    ('drain', mosfet_info.get('drain_net')),
                    ('source', mosfet_info.get('source_net')),
                ]:
                    if net_name and net_name != 'NC':
                        graph['nets'].setdefault(net_name, []).append((ref, f'mosfet_{pin_role}'))

        # Check if inductor (power or generic)
        elif part_id in POWER_INDUCTOR_IDS or part_id in GENERIC_INDUCTOR_IDS:
            inductor_info = _extract_inductor_connections(comp)
            if inductor_info:
                graph['inductors'].append(inductor_info)
                # Add to nets graph
                for term, net_name in [
                    ('terminal_a', inductor_info.get('terminal_a_net')),
                    ('terminal_b', inductor_info.get('terminal_b_net')),
                ]:
                    if net_name and net_name != 'NC':
                        if net_name not in graph['nets']:
                            graph['nets'][net_name] = []
                        graph['nets'][net_name].append((ref, f'inductor_{term}'))

        # Check if transformer
        elif part_id in TRANSFORMER_IDS:
            xfmr_info = _extract_transformer_connections(comp)
            if xfmr_info:
                graph['transformers'].append(xfmr_info)

    return graph


def _extract_mosfet_connections(comp, kg_store):
    """Extract drain, source, gate, and KS connections from a MOSFET."""
    info = {'ref': comp.get('ref', ''), 'part_id': comp.get('part_id', '')}

    part_id = comp.get('part_id', '')

    # Get pin roles from kg_store or use defaults
    pin_roles = {}
    if kg_store:
        kg_comp = kg_store.get_component(part_id)
        if kg_comp:
            pin_roles = kg_comp.get('pin_roles', {})

    # Build pin number to net mapping
    pin_nets = {}
    for pin in comp.get('pins', []):
        pin_num = str(pin.get('pin_id', ''))
        net = pin.get('net', '')
        pin_nets[pin_num] = net

    # Map pin roles to nets
    for pin_num, role in pin_roles.items():
        net = pin_nets.get(str(pin_num), '')
        if role == 'mosfet_drain':
            info['drain_net'] = net
        elif role == 'mosfet_source':
            info['source_net'] = net
        elif role == 'mosfet_gate':
            info['gate_net'] = net
        elif role == 'mosfet_kelvin_source':
            info['ks_net'] = net

    # Fallback for common MOSFET pinouts if kg_store didn't have info
    if 'drain_net' not in info:
        # Common patterns
        if part_id == 'IMZA65R015M2H':
            info['drain_net'] = pin_nets.get('1', '')
            info['source_net'] = pin_nets.get('2', '')
            info['ks_net'] = pin_nets.get('3', '')
            info['gate_net'] = pin_nets.get('4', '')
        elif 'BSC' in part_id.upper():
            # TDSON-8: S=1-3, G=4, D=5-9
            info['source_net'] = pin_nets.get('1', '')
            info['gate_net'] = pin_nets.get('4', '')
            info['drain_net'] = pin_nets.get('5', '')

    return info


def _extract_inductor_connections(comp):
    """Extract terminal A and B connections from an inductor (Inductor_power or L)."""
    info = {'ref': comp.get('ref', ''), 'part_id': comp.get('part_id', '')}

    part_id = comp.get('part_id', '')
    if part_id in GENERIC_INDUCTOR_IDS:
        net_a, net_b = _extract_two_terminal_nets(comp)
        info['terminal_a_net'] = net_a
        info['terminal_b_net'] = net_b
        return info

    pin_nets = {}
    for pin in comp.get('pins', []):
        pin_num = str(pin.get('pin_id', ''))
        net = pin.get('net', '')
        pin_nets[pin_num] = net

    # Inductor_power: pins 1-6 = Terminal A, pins 7-12 = Terminal B
    # All pins in a terminal group should be on the same net
    terminal_a_nets = set()
    terminal_b_nets = set()

    for p in range(1, 7):
        net = pin_nets.get(str(p), '')
        if net and net != 'NC':
            terminal_a_nets.add(net)

    for p in range(7, 13):
        net = pin_nets.get(str(p), '')
        if net and net != 'NC':
            terminal_b_nets.add(net)

    # Should be exactly one net per terminal
    info['terminal_a_net'] = list(terminal_a_nets)[0] if len(terminal_a_nets) == 1 else None
    info['terminal_b_net'] = list(terminal_b_nets)[0] if len(terminal_b_nets) == 1 else None

    return info


def _extract_two_terminal_nets(comp):
    """Extract the two nets connected to a 2-terminal component (R/C/L/C_film)."""
    nets = []
    for pin in comp.get('pins', []):
        net = pin.get('net', '')
        if not net or net == 'NC':
            continue
        if net not in nets:
            nets.append(net)
    if len(nets) < 2:
        return None, None
    return nets[0], nets[1]


def _extract_transformer_connections(comp):
    """Extract primary and secondary winding connections from a transformer."""
    info = {'ref': comp.get('ref', '')}

    pin_nets = {}
    for pin in comp.get('pins', []):
        pin_num = str(pin.get('pin_id', ''))
        net = pin.get('net', '')
        pin_nets[pin_num] = net

    # transformer_PQ5050: Pri_1 (1-3), Pri_2 (4-6), Sec_1 (7-9), Sec_2 (10-12)
    def get_winding_net(pins):
        nets = set()
        for p in pins:
            net = pin_nets.get(str(p), '')
            if net and net != 'NC':
                nets.add(net)
        return list(nets)[0] if len(nets) == 1 else None

    info['pri1_net'] = get_winding_net([1, 2, 3])
    info['pri2_net'] = get_winding_net([4, 5, 6])
    info['sec1_net'] = get_winding_net([7, 8, 9])
    info['sec2_net'] = get_winding_net([10, 11, 12])

    return info


def _verify_sync_buck(power_graph, snapshot):
    """
    Verify synchronous buck converter topology.

    Expected connections:
    - Q1 (HS): Drain → VIN/VBUS, Source → VSW
    - Q2 (LS): Drain → VSW, Source → GND/PGND
    - Inductor: Terminal_A → VSW, Terminal_B → VOUT

    Key verification:
    1. Find VSW node (common to Q1.Source, Q2.Drain, and Inductor.Terminal_A)
    2. Verify Q1.Drain connects to input supply net
    3. Verify Q2.Source connects to ground net
    4. Verify Inductor.Terminal_B connects to output net
    """
    errors = []
    mosfets = power_graph['mosfets']
    inductors = power_graph['inductors']
    nets = power_graph['nets']

    if len(mosfets) < 2:
        errors.append("Sync buck requires at least 2 MOSFETs")
        return errors

    if len(inductors) < 1:
        errors.append("Sync buck requires a power inductor")
        return errors

    # Find VSW node: should have 2 MOSFET connections and 1 inductor connection
    vsw_candidates = []
    for net_name, connections in nets.items():
        mosfet_pins = [c for c in connections if 'mosfet' in c[1]]
        inductor_pins = [c for c in connections if 'inductor' in c[1]]

        # VSW should have exactly: 1 source (HS) + 1 drain (LS) + 1 inductor terminal
        if len(mosfet_pins) >= 2 and len(inductor_pins) >= 1:
            # Check that we have both drain and source connections
            has_source = any('source' in pin[1] for pin in mosfet_pins)
            has_drain = any('drain' in pin[1] for pin in mosfet_pins)
            if has_source and has_drain:
                vsw_candidates.append(net_name)

    if not vsw_candidates:
        errors.append(
            "Cannot find VSW (switch node): Expected a net connecting "
            "HS MOSFET source, LS MOSFET drain, and inductor terminal"
        )
        return errors

    vsw_net = vsw_candidates[0]  # Use first candidate

    # Identify HS and LS MOSFETs based on VSW connection
    hs_mosfet = None
    ls_mosfet = None

    for m in mosfets:
        if m.get('source_net') == vsw_net:
            hs_mosfet = m
        elif m.get('drain_net') == vsw_net:
            ls_mosfet = m

    if not hs_mosfet:
        errors.append(
            f"Cannot identify high-side MOSFET: No MOSFET has source connected to VSW ({vsw_net})"
        )
    if not ls_mosfet:
        errors.append(
            f"Cannot identify low-side MOSFET: No MOSFET has drain connected to VSW ({vsw_net})"
        )

    if not hs_mosfet or not ls_mosfet:
        return errors

    # Verify HS drain connects to input supply
    hs_drain = hs_mosfet.get('drain_net', '')
    if not _is_input_supply_net(hs_drain):
        errors.append(
            f"HS MOSFET ({hs_mosfet['ref']}) drain ({hs_drain}) should connect to "
            f"input supply (VIN/VBUS), but doesn't appear to"
        )

    # Verify LS source connects to ground
    ls_source = ls_mosfet.get('source_net', '')
    if not _is_ground_net(ls_source):
        errors.append(
            f"LS MOSFET ({ls_mosfet['ref']}) source ({ls_source}) should connect to "
            f"ground (GND/PGND), but doesn't appear to"
        )

    # Verify inductor connects VSW to VOUT
    for ind in inductors:
        term_a = ind.get('terminal_a_net', '')
        term_b = ind.get('terminal_b_net', '')

        if term_a == vsw_net:
            if not _is_output_net(term_b):
                errors.append(
                    f"Inductor ({ind['ref']}) terminal B ({term_b}) should connect to "
                    f"output (VOUT), but doesn't appear to"
                )
        elif term_b == vsw_net:
            if not _is_output_net(term_a):
                errors.append(
                    f"Inductor ({ind['ref']}) terminal A ({term_a}) should connect to "
                    f"output (VOUT), but doesn't appear to"
                )
        else:
            errors.append(
                f"Inductor ({ind['ref']}) is not connected to VSW ({vsw_net})"
            )

    return errors


def _verify_sync_boost(power_graph, snapshot):
    """
    Verify synchronous boost converter topology.

    Expected connections:
    - Inductor: Terminal_A → VIN, Terminal_B → VSW
    - Q1 (LS/main switch): Drain → VSW, Source → GND
    - Q2 (HS/sync rectifier): Drain → VOUT, Source → VSW
    """
    errors = []
    mosfets = power_graph['mosfets']
    inductors = power_graph['inductors']
    nets = power_graph['nets']

    if len(mosfets) < 2:
        errors.append("Sync boost requires at least 2 MOSFETs")
        return errors

    if len(inductors) < 1:
        errors.append("Sync boost requires a power inductor")
        return errors

    # Find VSW node: should have 2 MOSFET connections and 1 inductor connection
    vsw_candidates = []
    for net_name, connections in nets.items():
        mosfet_pins = [c for c in connections if 'mosfet' in c[1]]
        inductor_pins = [c for c in connections if 'inductor' in c[1]]

        if len(mosfet_pins) >= 2 and len(inductor_pins) >= 1:
            has_source = any('source' in pin[1] for pin in mosfet_pins)
            has_drain = any('drain' in pin[1] for pin in mosfet_pins)
            if has_source and has_drain:
                vsw_candidates.append(net_name)

    if not vsw_candidates:
        errors.append(
            "Cannot find VSW (switch node): Expected a net connecting "
            "2 MOSFETs and inductor"
        )
        return errors

    vin_net = _resolve_named_net(snapshot, "VIN")
    vout_net = _resolve_named_net(snapshot, "VOUT")

    best_error = None
    for vsw_net in vsw_candidates:
        # Identify LS (main switch): Drain=VSW, Source=GND
        ls = next(
            (m for m in mosfets if m.get('drain_net') == vsw_net and _is_ground_net(m.get('source_net', ''))),
            None,
        )
        # Identify HS (sync rectifier): Source=VSW, Drain=VOUT
        hs = next(
            (m for m in mosfets if m.get('source_net') == vsw_net and (m.get('drain_net') == vout_net or _is_output_net(m.get('drain_net', '')))),
            None,
        )

        local_errors = []
        if not ls:
            local_errors.append(f"Boost: cannot find low-side MOSFET with drain=VSW ({vsw_net}) and source=GND")
        if not hs:
            local_errors.append(f"Boost: cannot find high-side MOSFET with source=VSW ({vsw_net}) and drain=VOUT")

        # Verify inductor connects VIN -> VSW
        if vin_net:
            has_vin_to_vsw = False
            for ind in inductors:
                a = ind.get('terminal_a_net', '')
                b = ind.get('terminal_b_net', '')
                if not a or not b:
                    continue
                if (a == vin_net and b == vsw_net) or (b == vin_net and a == vsw_net):
                    has_vin_to_vsw = True
                    break
            if not has_vin_to_vsw:
                local_errors.append(f"Boost: expected inductor between VIN ({vin_net}) and VSW ({vsw_net})")
        else:
            local_errors.append("Boost: cannot find VIN net in snapshot (expected Net('VIN'))")

        if not local_errors:
            return []  # Found a valid pattern
        if best_error is None:
            best_error = local_errors

    errors.extend(best_error or [f"Boost: VSW candidates found ({vsw_candidates}) but none match boost topology"])
    return errors


def _verify_4sw_buckboost(power_graph, snapshot):
    """Verify 4-switch buck-boost converter topology."""
    errors = []
    mosfets = power_graph['mosfets']
    inductors = power_graph['inductors']
    nets = power_graph['nets']

    if len(mosfets) < 4:
        errors.append("4-switch buck-boost requires at least 4 MOSFETs")
        return errors

    if len(inductors) < 1:
        errors.append("4-switch buck-boost requires a power inductor between the two switch nodes")
        return errors

    vin_net = _resolve_named_net(snapshot, "VIN")
    vout_net = _resolve_named_net(snapshot, "VOUT")
    if not vout_net:
        errors.append("4-switch buck-boost expects an output net named VOUT")
        return errors

    # Find two VSW nodes: each should have a HS+LS MOSFET pair, and one inductor terminal.
    vsw_candidates = []
    for net_name, connections in nets.items():
        mosfet_pins = [c for c in connections if 'mosfet' in c[1]]
        inductor_pins = [c for c in connections if 'inductor' in c[1]]
        if len(mosfet_pins) >= 2 and len(inductor_pins) >= 1:
            has_source = any('source' in pin[1] for pin in mosfet_pins)
            has_drain = any('drain' in pin[1] for pin in mosfet_pins)
            if has_source and has_drain:
                vsw_candidates.append(net_name)

    if len(vsw_candidates) < 2:
        errors.append(
            "4-switch buck-boost: cannot find two switch nodes (VSW): "
            "expected two nets each tying HS source + LS drain + inductor terminal"
        )
        return errors

    # Identify an input-side half-bridge (HS drain VIN) and output-side half-bridge (HS drain VOUT)
    def find_hb(vsw, expected_bus_net):
        hs = next((m for m in mosfets if m.get('source_net') == vsw and m.get('drain_net') == expected_bus_net), None)
        ls = next((m for m in mosfets if m.get('drain_net') == vsw and _is_ground_net(m.get('source_net', ''))), None)
        return hs, ls

    best = None
    for a in vsw_candidates:
        for b in vsw_candidates:
            if a == b:
                continue
            hs_in, ls_in = (find_hb(a, vin_net) if vin_net else (None, None))
            hs_out, ls_out = find_hb(b, vout_net)
            if not (hs_in and ls_in and hs_out and ls_out):
                continue

            # Check the inductor is between the two switch nodes.
            has_ind = any(
                (ind.get('terminal_a_net') == a and ind.get('terminal_b_net') == b)
                or (ind.get('terminal_a_net') == b and ind.get('terminal_b_net') == a)
                for ind in inductors
            )
            if not has_ind:
                continue

            best = (a, b)
            break
        if best:
            break

    if not best:
        errors.append(
            "4-switch buck-boost: expected two half-bridges (VIN-side and VOUT-side) "
            "with an inductor between their switch nodes"
        )
        return errors

    return []


def _verify_dab(power_graph, snapshot):
    """Verify dual active bridge converter topology."""
    errors = []
    mosfets = power_graph['mosfets']
    transformers = power_graph['transformers']

    if len(mosfets) < 8:
        errors.append("DAB requires at least 8 MOSFETs (4 per bridge)")
        return errors

    if len(transformers) < 1:
        errors.append("DAB requires a transformer")
        return errors

    xfmr = transformers[0]
    pri1 = xfmr.get('pri1_net')
    pri2 = xfmr.get('pri2_net')
    sec1 = xfmr.get('sec1_net')
    sec2 = xfmr.get('sec2_net')
    if not all([pri1, pri2, sec1, sec2]):
        errors.append("DAB: transformer primary/secondary nets are incomplete (check transformer pin wiring)")
        return errors

    # Output (benchmark) provides two named ports; they must form a full-bridge and connect to one transformer side.
    vsw_1 = _resolve_named_net(snapshot, "VSW_1")
    vsw_2 = _resolve_named_net(snapshot, "VSW_2")
    if not vsw_1 or not vsw_2:
        errors.append("DAB: expected named ports VSW_1 and VSW_2")
        return errors

    output_bridge, out_errs = _infer_full_bridge_from_vsw(mosfets, [vsw_1, vsw_2])
    if out_errs:
        errors.extend([f"DAB: output bridge: {e}" for e in out_errs])
        return errors

    pri_terms = (pri1, pri2)
    sec_terms = (sec1, sec2)
    out_side = _bridge_transformer_side(snapshot, output_bridge['vsw_nodes'], pri_terms, sec_terms, allowed_parts=PATH_PART_IDS)
    if out_side == 'none':
        errors.append(
            f"DAB: output bridge switch nodes ({vsw_1}, {vsw_2}) are not connected to transformer (pri={pri1, pri2}, sec={sec1, sec2})"
        )
        return errors

    other_terms = sec_terms if out_side == 'pri' else pri_terms
    other_bridge, other_errs = _infer_other_bridge_connected_to_terms(
        snapshot,
        mosfets,
        excluded_bus_gnd=(output_bridge['bus'], output_bridge['gnd']),
        transformer_terms=other_terms,
        allowed_parts=PATH_PART_IDS,
    )
    if other_errs:
        errors.extend([f"DAB: {e}" for e in other_errs])
        return errors

    # Determine which bridge is the VIN/VBUS-referenced input bridge.
    input_bridge, input_errs = _select_input_bridge(snapshot, [output_bridge, other_bridge])
    if input_errs:
        errors.extend([f"DAB: {e}" for e in input_errs])
        return errors

    # Apply the tank requirement on whichever transformer side the input bridge actually drives.
    input_side = _bridge_transformer_side(snapshot, input_bridge['vsw_nodes'], pri_terms, sec_terms, allowed_parts=PATH_PART_IDS)
    if input_side == 'none':
        errors.append("DAB: input bridge is not connected to transformer (unexpected wiring)")
        return errors
    target_terms = list(pri_terms if input_side == 'pri' else sec_terms)

    if not _exists_required_tank_path(
        snapshot,
        starts=input_bridge['vsw_nodes'],
        targets=target_terms,
        require_film=True,
        require_inductor=True,
        allowed_parts=PATH_PART_IDS,
    ):
        errors.append("DAB: missing series tank elements (need both C_film and inductor on VIN-side path to transformer)")

    return errors


def _verify_llc(power_graph, snapshot):
    """Verify LLC resonant converter topology."""
    errors = []
    mosfets = power_graph['mosfets']
    transformers = power_graph['transformers']

    if len(mosfets) < 8:
        errors.append("LLC requires at least 8 MOSFETs (full-bridge primary + full-bridge secondary)")
        return errors

    if len(transformers) < 1:
        errors.append("LLC requires a transformer")
        return errors

    xfmr = transformers[0]
    pri1 = xfmr.get('pri1_net')
    pri2 = xfmr.get('pri2_net')
    sec1 = xfmr.get('sec1_net')
    sec2 = xfmr.get('sec2_net')
    if not all([pri1, pri2, sec1, sec2]):
        errors.append("LLC: transformer primary/secondary nets are incomplete (check transformer pin wiring)")
        return errors

    vsw_1 = _resolve_named_net(snapshot, "VSW_1")
    vsw_2 = _resolve_named_net(snapshot, "VSW_2")
    if not vsw_1 or not vsw_2:
        errors.append("LLC: expected named ports VSW_1 and VSW_2")
        return errors

    output_bridge, out_errs = _infer_full_bridge_from_vsw(mosfets, [vsw_1, vsw_2])
    if out_errs:
        errors.extend([f"LLC: output bridge: {e}" for e in out_errs])
        return errors

    pri_terms = (pri1, pri2)
    sec_terms = (sec1, sec2)
    out_side = _bridge_transformer_side(snapshot, output_bridge['vsw_nodes'], pri_terms, sec_terms, allowed_parts=PATH_PART_IDS)
    if out_side == 'none':
        errors.append(
            f"LLC: output bridge switch nodes ({vsw_1}, {vsw_2}) are not connected to transformer (pri={pri1, pri2}, sec={sec1, sec2})"
        )
        return errors

    other_terms = sec_terms if out_side == 'pri' else pri_terms
    other_bridge, other_errs = _infer_other_bridge_connected_to_terms(
        snapshot,
        mosfets,
        excluded_bus_gnd=(output_bridge['bus'], output_bridge['gnd']),
        transformer_terms=other_terms,
        allowed_parts=PATH_PART_IDS,
    )
    if other_errs:
        errors.extend([f"LLC: {e}" for e in other_errs])
        return errors

    input_bridge, input_errs = _select_input_bridge(snapshot, [output_bridge, other_bridge])
    if input_errs:
        errors.extend([f"LLC: {e}" for e in input_errs])
        return errors

    input_side = _bridge_transformer_side(snapshot, input_bridge['vsw_nodes'], pri_terms, sec_terms, allowed_parts=PATH_PART_IDS)
    if input_side == 'none':
        errors.append("LLC: input bridge is not connected to transformer (unexpected wiring)")
        return errors
    target_terms = list(pri_terms if input_side == 'pri' else sec_terms)

    # LLC must have resonant tank \"intervening\": require BOTH switch nodes to reach the transformer via (C_film + inductor).
    for vsw in input_bridge['vsw_nodes']:
        if not _exists_required_tank_path(
            snapshot,
            starts=[vsw],
            targets=target_terms,
            require_film=True,
            require_inductor=True,
            allowed_parts=PATH_PART_IDS,
        ):
            errors.append(f"LLC: resonant tank missing between {vsw} and transformer (need C_film + inductor)")

    return errors


def _verify_3ph_inverter(power_graph, snapshot):
    """Verify 3-phase inverter topology."""
    errors = []
    mosfets = power_graph['mosfets']

    if len(mosfets) < 6:
        errors.append("3-phase inverter requires at least 6 MOSFETs")
        return errors

    vsw_1 = _resolve_named_net(snapshot, "VSW_1")
    vsw_2 = _resolve_named_net(snapshot, "VSW_2")
    vsw_3 = _resolve_named_net(snapshot, "VSW_3")
    missing = [n for n in (vsw_1, vsw_2, vsw_3) if not n]
    if missing:
        errors.append("3-phase inverter: expected output nets named VSW_1, VSW_2, VSW_3")
        return errors

    _, hb_errs = _infer_multi_half_bridges(mosfets, [vsw_1, vsw_2, vsw_3], require_input_bus=True)
    if hb_errs:
        errors.extend([f"3-phase inverter: {e}" for e in hb_errs])
    return errors


def _verify_1ph_fullbridge(power_graph, snapshot):
    """Verify single-phase full-bridge inverter topology."""
    errors = []
    mosfets = power_graph['mosfets']

    if len(mosfets) < 4:
        errors.append("Single-phase full-bridge requires at least 4 MOSFETs")
        return errors

    vsw_1 = _resolve_named_net(snapshot, "VSW_1")
    vsw_2 = _resolve_named_net(snapshot, "VSW_2")
    if not vsw_1 or not vsw_2:
        errors.append("Single-phase inverter: expected output nets named VSW_1 and VSW_2")
        return errors

    _, hb_errs = _infer_multi_half_bridges(mosfets, [vsw_1, vsw_2], require_input_bus=True)
    if hb_errs:
        errors.extend([f"Single-phase inverter: {e}" for e in hb_errs])
    return errors


def _is_input_supply_net(net_name):
    """Check if net name looks like an input supply."""
    if not net_name:
        return False
    name_upper = net_name.upper()
    return any(pattern in name_upper for pattern in ['VIN', 'VBUS', 'VDC', 'VBAT', 'V+'])


def _is_output_net(net_name):
    """Check if net name looks like an output."""
    if not net_name:
        return False
    name_upper = net_name.upper()
    return any(pattern in name_upper for pattern in ['VOUT', 'OUT', 'VO', 'OUTPUT'])


def _is_ground_net(net_name):
    """Check if net name looks like a ground."""
    if not net_name:
        return False
    name_upper = net_name.upper()
    return any(pattern in name_upper for pattern in ['GND', 'PGND', 'VSS', 'COM', 'GROUND'])


def _count_components(snapshot):
    """Count components by category."""
    counts = {
        'mosfets': 0,
        'gate_drivers': 0,
        'isolated_supplies': 0,
        'transformers': 0,
        'film_caps': 0,
        'power_inductors': 0,
        'inductors': 0,
        'caps': 0,
        'resistors': 0,
    }

    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '')
        part_id_upper = part_id.upper()

        if any(p in part_id_upper for p in MOSFET_PATTERNS):
            counts['mosfets'] += 1
        elif part_id in GATE_DRIVER_IDS:
            counts['gate_drivers'] += 1
        elif part_id in ISOLATED_SUPPLY_IDS:
            counts['isolated_supplies'] += 1
        elif part_id in TRANSFORMER_IDS:
            counts['transformers'] += 1
        elif part_id in FILM_CAP_IDS:
            counts['film_caps'] += 1
        elif part_id in POWER_INDUCTOR_IDS:
            counts['power_inductors'] += 1
        elif part_id in GENERIC_INDUCTOR_IDS:
            counts['inductors'] += 1
        elif part_id == 'C':
            counts['caps'] += 1
        elif part_id == 'R':
            counts['resistors'] += 1

    return counts


def _resolve_named_net(snapshot, desired_name):
    """Resolve a canonical net name (e.g., VIN/VOUT/VSW_1) to the snapshot's actual net name."""
    desired_upper = str(desired_name).upper()
    for net in snapshot.get('nets', []):
        name = net.get('name', '')
        if str(name).upper() == desired_upper:
            return name
    return None


def _build_passive_net_graph(snapshot, allowed_parts):
    """
    Build a net adjacency graph using only allowed passive parts.

    Returns:
        dict: net -> list of (neighbor_net, part_id, ref)
    """
    graph = {}
    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '')
        if part_id not in allowed_parts:
            continue
        ref = comp.get('ref', '')

        if part_id in POWER_INDUCTOR_IDS:
            ind = _extract_inductor_connections(comp)
            net_a = ind.get('terminal_a_net')
            net_b = ind.get('terminal_b_net')
        else:
            net_a, net_b = _extract_two_terminal_nets(comp)

        if not net_a or not net_b or net_a == net_b:
            continue

        graph.setdefault(net_a, []).append((net_b, part_id, ref))
        graph.setdefault(net_b, []).append((net_a, part_id, ref))
    return graph


def _path_exists(snapshot, start_net, end_net, allowed_parts, require_film=False, require_inductor=False):
    """
    Path existence check on a net graph induced by allowed parts.

    If require_film/require_inductor are set, the path must traverse at least one
    C_film and/or an inductor (Inductor_power or L) edge.
    """
    if not start_net or not end_net:
        return False
    if start_net == end_net:
        # Zero-length path is allowed only if no required elements are demanded.
        return not (require_film or require_inductor)

    net_graph = _build_passive_net_graph(snapshot, allowed_parts)
    q = deque()
    seen = set()
    q.append((start_net, False, False))

    while q:
        net, has_film, has_ind = q.popleft()
        state = (net, has_film, has_ind)
        if state in seen:
            continue
        seen.add(state)

        for nb, part_id, _ref in net_graph.get(net, []):
            nb_has_film = has_film or (part_id == 'C_film')
            nb_has_ind = has_ind or (part_id in POWER_INDUCTOR_IDS or part_id in GENERIC_INDUCTOR_IDS)
            if nb == end_net:
                if (not require_film or nb_has_film) and (not require_inductor or nb_has_ind):
                    return True
            q.append((nb, nb_has_film, nb_has_ind))

    return False


def _nets_connected(snapshot, net_a, net_b, allowed_parts):
    """Check if two nets are identical or connected via allowed passive parts."""
    if not net_a or not net_b:
        return False
    if net_a == net_b:
        return True
    return _path_exists(snapshot, net_a, net_b, allowed_parts, require_film=False, require_inductor=False)


def _side_terms_match_or_connected(snapshot, transformer_terms, expected_terms, allowed_parts):
    """Check transformer (term1, term2) matches expected (a, b) up to swap, or is connected via passives."""
    t1, t2 = transformer_terms
    a, b = expected_terms
    if (t1 == a and t2 == b) or (t1 == b and t2 == a):
        return True
    # Allow passive elements between transformer and bridge.
    return (_nets_connected(snapshot, t1, a, allowed_parts) and _nets_connected(snapshot, t2, b, allowed_parts)) or (
        _nets_connected(snapshot, t1, b, allowed_parts) and _nets_connected(snapshot, t2, a, allowed_parts)
    )


def _infer_half_bridge_on_vsw(mosfets, vsw_net):
    """
    Infer a (HS, LS) pair around a given switch node.

    Returns:
        dict or None, list[str] errors
    """
    if not vsw_net:
        return None, ["missing VSW net"]

    hs_candidates = [m for m in mosfets if m.get('source_net') == vsw_net and m.get('drain_net')]
    ls_candidates = [m for m in mosfets if m.get('drain_net') == vsw_net and m.get('source_net')]
    if not hs_candidates:
        return None, [f"no high-side candidate with source=VSW ({vsw_net})"]
    if not ls_candidates:
        return None, [f"no low-side candidate with drain=VSW ({vsw_net})"]

    best = None
    best_score = -1
    for hs in hs_candidates:
        for ls in ls_candidates:
            if hs.get('ref') == ls.get('ref'):
                continue
            bus = hs.get('drain_net', '')
            gnd = ls.get('source_net', '')
            if not bus or not gnd:
                continue
            score = 0
            if _is_ground_net(gnd):
                score += 3
            if not _is_ground_net(bus):
                score += 1
            if _is_input_supply_net(bus):
                score += 1
            if score > best_score:
                best_score = score
                best = {'vsw': vsw_net, 'hs': hs, 'ls': ls, 'bus': bus, 'gnd': gnd}

    if not best:
        return None, [f"cannot form half-bridge around {vsw_net}"]
    if not _is_ground_net(best['gnd']):
        return best, [f"LS source ({best['gnd']}) does not look like a ground net"]
    return best, []


def _infer_full_bridge_from_vsw(mosfets, vsw_nets):
    """Infer a full bridge made of half-bridges on the given switch nodes."""
    if len(vsw_nets) != 2:
        return None, ["expected exactly 2 switch nodes for full-bridge"]
    hb1, e1 = _infer_half_bridge_on_vsw(mosfets, vsw_nets[0])
    hb2, e2 = _infer_half_bridge_on_vsw(mosfets, vsw_nets[1])
    errors = []
    errors.extend(e1)
    errors.extend(e2)
    if not hb1 or not hb2:
        return None, errors
    if hb1['bus'] != hb2['bus'] or hb1['gnd'] != hb2['gnd']:
        errors.append(
            f"half-bridges do not share common bus/gnd (HB1 bus/gnd={hb1['bus']}/{hb1['gnd']}, "
            f"HB2 bus/gnd={hb2['bus']}/{hb2['gnd']})"
        )
    return {'vsw_nodes': [hb1['vsw'], hb2['vsw']], 'bus': hb1['bus'], 'gnd': hb1['gnd'], 'half_bridges': [hb1, hb2]}, errors


def _infer_multi_half_bridges(mosfets, vsw_nets, require_input_bus=False):
    """Infer N half-bridges that share a common input bus and ground."""
    half_bridges = []
    errors = []
    for vsw in vsw_nets:
        hb, hb_errs = _infer_half_bridge_on_vsw(mosfets, vsw)
        if hb_errs:
            errors.append(f"{vsw}: " + "; ".join(hb_errs))
        if hb:
            half_bridges.append(hb)

    if len(half_bridges) != len(vsw_nets):
        return None, errors

    bus = half_bridges[0]['bus']
    gnd = half_bridges[0]['gnd']
    for hb in half_bridges[1:]:
        if hb['bus'] != bus or hb['gnd'] != gnd:
            errors.append(
                f"half-bridges do not share common bus/gnd (expected {bus}/{gnd}, got {hb['bus']}/{hb['gnd']})"
            )

    if require_input_bus and not _is_input_supply_net(bus):
        errors.append(f"bus net ({bus}) does not look like an input supply (VIN/VBUS/...)")

    return {'bus': bus, 'gnd': gnd, 'half_bridges': half_bridges}, errors


def _enumerate_half_bridges(mosfets):
    """Enumerate half-bridge candidates based on drain/source connections around a common switch node."""
    by_source = {}
    by_drain = {}
    for m in mosfets:
        s = m.get('source_net')
        d = m.get('drain_net')
        if s:
            by_source.setdefault(s, []).append(m)
        if d:
            by_drain.setdefault(d, []).append(m)

    half_bridges = []
    for vsw in set(by_source) & set(by_drain):
        for hs in by_source.get(vsw, []):
            for ls in by_drain.get(vsw, []):
                if hs.get('ref') == ls.get('ref'):
                    continue
                bus = hs.get('drain_net')
                gnd = ls.get('source_net')
                if not bus or not gnd:
                    continue
                if not _is_ground_net(gnd):
                    continue
                if _is_ground_net(bus):
                    continue
                half_bridges.append({'vsw': vsw, 'hs': hs, 'ls': ls, 'bus': bus, 'gnd': gnd})

    return half_bridges


def _infer_primary_bridge_connected_to_transformer(snapshot, mosfets, transformer_primary_terms, allowed_parts):
    """
    Infer a primary full-bridge on VIN/VBUS-like bus that connects to transformer primary.
    Returns: ({vsw_nodes, bus, gnd}, errors)
    """
    pri1, pri2 = transformer_primary_terms
    if not pri1 or not pri2:
        return None, ["transformer primary nets are missing"]

    candidates = [hb for hb in _enumerate_half_bridges(mosfets) if _is_input_supply_net(hb['bus'])]
    if not candidates:
        return None, ["cannot find any VIN/VBUS-referenced half-bridges"]

    # Group by (bus, gnd) and search for 2 distinct switch nodes that reach pri1/pri2.
    groups = {}
    for hb in candidates:
        groups.setdefault((hb['bus'], hb['gnd']), []).append(hb)

    best = None
    best_score = -1
    for (bus, gnd), hbs in groups.items():
        vsw_nodes = sorted({hb['vsw'] for hb in hbs})
        if len(vsw_nodes) < 2:
            continue
        for i in range(len(vsw_nodes)):
            for j in range(i + 1, len(vsw_nodes)):
                a = vsw_nodes[i]
                b = vsw_nodes[j]
                # Need to cover both transformer primary terminals.
                a_reaches_pri1 = _nets_connected(snapshot, a, pri1, allowed_parts)
                a_reaches_pri2 = _nets_connected(snapshot, a, pri2, allowed_parts)
                b_reaches_pri1 = _nets_connected(snapshot, b, pri1, allowed_parts)
                b_reaches_pri2 = _nets_connected(snapshot, b, pri2, allowed_parts)

                covers_pri1 = a_reaches_pri1 or b_reaches_pri1
                covers_pri2 = a_reaches_pri2 or b_reaches_pri2
                if not (covers_pri1 and covers_pri2):
                    continue

                score = int(a_reaches_pri1) + int(a_reaches_pri2) + int(b_reaches_pri1) + int(b_reaches_pri2)
                if score > best_score:
                    best_score = score
                    best = {'vsw_nodes': [a, b], 'bus': bus, 'gnd': gnd}

    if not best:
        return None, ["cannot find an input full-bridge connected to transformer primary terminals"]
    return best, []


def _exists_required_tank_path(snapshot, starts, targets, require_film, require_inductor, allowed_parts):
    """Return True if any start->target path exists that includes required elements."""
    for s in starts:
        for t in targets:
            if _path_exists(
                snapshot,
                s,
                t,
                allowed_parts,
                require_film=require_film,
                require_inductor=require_inductor,
            ):
                return True
    return False


def _check_component_counts(counts, template, task_id):
    """Check if component counts meet minimum requirements."""
    errors = []

    if counts['mosfets'] < template.get('min_mosfets', 0):
        errors.append(
            f"Task {task_id} ({template['name']}) requires at least "
            f"{template['min_mosfets']} MOSFETs, but only {counts['mosfets']} found"
        )

    if counts['gate_drivers'] < template.get('min_gate_drivers', 0):
        errors.append(
            f"Task {task_id} ({template['name']}) requires at least "
            f"{template['min_gate_drivers']} gate drivers, but only {counts['gate_drivers']} found"
        )

    if counts['isolated_supplies'] < template.get('min_isolated_supplies', 0):
        errors.append(
            f"Task {task_id} ({template['name']}) requires at least "
            f"{template['min_isolated_supplies']} isolated power supplies, "
            f"but only {counts['isolated_supplies']} found"
        )

    return errors


def _count_output_caps(snapshot):
    """Count capacitors connected to VOUT-like nets."""
    cap_count = 0

    for net in snapshot.get('nets', []):
        net_name = net.get('name', '').upper()
        if 'VOUT' in net_name or net_name == 'OUT' or 'OUTPUT' in net_name:
            for endpoint in net.get('endpoints', []):
                comp = _find_component_by_ref(snapshot, endpoint.get('ref', ''))
                if comp and comp.get('part_id') == 'C':
                    cap_count += 1

    return cap_count


def _check_vbus_decoupling(snapshot, task_id):
    """Check for adequate VBUS decoupling capacitors."""
    errors = []

    vbus_nets = []
    for net in snapshot.get('nets', []):
        net_name = net.get('name', '').upper()
        if 'VBUS' not in net_name and 'VIN' not in net_name:
            continue

        # Only enforce on nets that actually serve as a MOSFET drain bus (high dv/dt loop),
        # not on VIN logic rails that don't feed the power stage.
        has_mosfet_drain = any(ep.get('pin_role') == 'mosfet_drain' for ep in net.get('endpoints', []))
        if has_mosfet_drain:
            vbus_nets.append(net)

    for vbus_net in vbus_nets:
        cap_count = 0
        for endpoint in vbus_net.get('endpoints', []):
            comp = _find_component_by_ref(snapshot, endpoint.get('ref', ''))
            if comp and comp.get('part_id') == 'C':
                cap_count += 1

        if task_id in [17, 18, 19, 20, 21, 22, 23]:
            if cap_count < 8:
                errors.append(
                    f"VBUS net '{vbus_net.get('name')}' has only {cap_count} decoupling capacitors. "
                    f"High dv/dt applications MUST have at least 8 capacitors."
                )

    return errors


def _bridge_covers_terms(snapshot, vsw_nodes, transformer_terms, allowed_parts):
    """Return True if both transformer terminals are connected (directly or via passives) to the bridge's switch nodes."""
    t1, t2 = transformer_terms
    if not t1 or not t2:
        return False
    if not vsw_nodes:
        return False

    def reaches(term):
        return any(_nets_connected(snapshot, vsw, term, allowed_parts) for vsw in vsw_nodes)

    return reaches(t1) and reaches(t2)


def _bridge_transformer_side(snapshot, vsw_nodes, pri_terms, sec_terms, allowed_parts):
    """
    Determine which transformer side a bridge connects to.
    Returns: 'pri', 'sec', 'both', or 'none'
    """
    pri_ok = _bridge_covers_terms(snapshot, vsw_nodes, pri_terms, allowed_parts)
    sec_ok = _bridge_covers_terms(snapshot, vsw_nodes, sec_terms, allowed_parts)
    if pri_ok and sec_ok:
        return 'both'
    if pri_ok:
        return 'pri'
    if sec_ok:
        return 'sec'
    return 'none'


def _infer_bridge_candidates(mosfets):
    """Infer (bus, gnd, vsw_nodes) bridge candidates from MOSFET drain/source connectivity."""
    groups = {}
    for hb in _enumerate_half_bridges(mosfets):
        groups.setdefault((hb['bus'], hb['gnd']), set()).add(hb['vsw'])
    candidates = []
    for (bus, gnd), vsws in groups.items():
        if len(vsws) < 2:
            continue
        candidates.append({'bus': bus, 'gnd': gnd, 'vsw_nodes': sorted(vsws)})
    return candidates


def _infer_other_bridge_connected_to_terms(snapshot, mosfets, excluded_bus_gnd, transformer_terms, allowed_parts):
    """Find a bridge candidate (excluding excluded_bus_gnd) that connects to the given transformer terminals."""
    candidates = [b for b in _infer_bridge_candidates(mosfets) if (b['bus'], b['gnd']) != excluded_bus_gnd]
    for b in candidates:
        if _bridge_covers_terms(snapshot, b['vsw_nodes'], transformer_terms, allowed_parts):
            # For DAB/LLC we only need the two-leg full bridge; keep first two switch nodes for downstream logic.
            return {'bus': b['bus'], 'gnd': b['gnd'], 'vsw_nodes': b['vsw_nodes'][:2]}, []
    return None, [f"cannot find a second full-bridge connected to transformer terminals {transformer_terms}"]


def _select_input_bridge(snapshot, bridges):
    """Select the VIN-side bridge among candidates, prioritizing a net literally named VIN when present."""
    vin_net = _resolve_named_net(snapshot, "VIN")
    if vin_net:
        preferred = [b for b in bridges if b.get('bus') == vin_net or 'VIN' in str(b.get('bus', '')).upper()]
        if preferred:
            return preferred[0], []

    candidates = [b for b in bridges if _is_input_supply_net(b.get('bus', ''))]
    if not candidates:
        return None, ["cannot identify VIN/VBUS-referenced input bridge (bus net not VIN/VBUS-like)"]
    return candidates[0], []


def _find_component_by_ref(snapshot, ref):
    """Find a component by its reference designator."""
    for comp in snapshot.get('components', []):
        if comp.get('ref') == ref:
            return comp
    return None


def is_complex_task(task_id):
    """Check if a task ID is a complex task (P17-P23)."""
    return task_id in TASK_TEMPLATES


def get_task_template(task_id):
    """Get the template for a task."""
    return TASK_TEMPLATES.get(task_id)

"""
Interface checker for complex PCB circuits.

This module verifies that functional blocks (gate drivers, MOSFETs,
power supplies) are correctly interconnected.
"""

from .build_topology import index_snapshot


# Gate driver part IDs
ISOLATED_GATE_DRIVERS = {'UCC5390E', 'UCC21710'}
BOOTSTRAP_GATE_DRIVERS = {'UCC27211'}
LOW_SIDE_GATE_DRIVERS = {'UCC27511'}
ALL_GATE_DRIVERS = ISOLATED_GATE_DRIVERS | BOOTSTRAP_GATE_DRIVERS | LOW_SIDE_GATE_DRIVERS

# MOSFET part ID patterns
MOSFET_PATTERNS = ['IMZA', 'IMLT', 'IMT', 'IMW', 'BSC']

# Isolated power supply part IDs
ISOLATED_SUPPLIES = {'MGJ2D121505SC'}


def check_interfaces(snapshot, kg_store):
    """
    Check interface connections between functional blocks.

    Returns:
        list: Error messages for any interface issues found
    """
    errors = []

    # Index the snapshot for quick lookups
    index = index_snapshot(snapshot)

    # Find all components by category
    gate_drivers = _find_gate_drivers(snapshot)
    mosfets = _find_mosfets(snapshot)
    iso_supplies = _find_isolated_supplies(snapshot)

    # Check gate driver to MOSFET connections
    errors.extend(_check_gate_driver_to_mosfet(snapshot, index, gate_drivers, mosfets, kg_store))

    # Check gate resistor presence
    errors.extend(_check_gate_resistors(snapshot, index, gate_drivers, mosfets))

    # Check Kelvin source connections
    errors.extend(_check_kelvin_source_connections(snapshot, index, gate_drivers, mosfets, kg_store))

    # Check isolated supply connections
    errors.extend(_check_isolated_supply_connections(snapshot, index, iso_supplies, gate_drivers))

    # Check bootstrap capacitor for UCC27211
    errors.extend(_check_bootstrap_connections(snapshot, index, gate_drivers))

    return errors


def _find_gate_drivers(snapshot):
    """Find all gate driver components."""
    drivers = []
    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '')
        if part_id in ALL_GATE_DRIVERS:
            drivers.append(comp)
    return drivers


def _find_mosfets(snapshot):
    """Find all MOSFET components."""
    mosfets = []
    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '').upper()
        if any(pattern in part_id for pattern in MOSFET_PATTERNS):
            mosfets.append(comp)
    return mosfets


def _find_isolated_supplies(snapshot):
    """Find all isolated power supply components."""
    supplies = []
    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '')
        if part_id in ISOLATED_SUPPLIES:
            supplies.append(comp)
    return supplies


def _get_pin_net(comp, pin_id_or_name):
    """Get the net connected to a specific pin."""
    for pin in comp.get('pins', []):
        if str(pin.get('pin_id')) == str(pin_id_or_name):
            return pin.get('net')
        if pin.get('pin_name') == pin_id_or_name:
            return pin.get('net')
    return None


def _is_not_connected(net):
    """Check if a net represents a not-connected state."""
    if not net:
        return True
    return net in ('NC', '__NOCONNECT', 'NOCONNECT')


def _check_gate_driver_to_mosfet(snapshot, index, gate_drivers, mosfets, kg_store):
    """Check that gate driver outputs connect to MOSFET gates."""
    errors = []

    # Build map of net -> connected MOSFETs with gate pin
    mosfet_gate_nets = {}
    for mosfet in mosfets:
        ref = mosfet.get('ref', '')
        part_id = mosfet.get('part_id', '')
        gate_pin = _get_mosfet_gate_pin(part_id, kg_store)

        if gate_pin:
            gate_net = _get_pin_net(mosfet, gate_pin)
            if gate_net and gate_net != 'NC':
                if gate_net not in mosfet_gate_nets:
                    mosfet_gate_nets[gate_net] = []
                mosfet_gate_nets[gate_net].append(ref)

    # Check each gate driver
    for driver in gate_drivers:
        ref = driver.get('ref', '')
        part_id = driver.get('part_id', '')
        output_pins = _get_driver_output_pins(part_id)

        for out_pin in output_pins:
            out_net = _get_pin_net(driver, out_pin)
            if _is_not_connected(out_net):
                errors.append(f"{ref}: Gate driver output pin {out_pin} not connected")
                continue

            # Check if this net connects to any MOSFET gate
            # Note: It might connect via a gate resistor, so we check path
            connected_to_gate = _check_path_to_mosfet_gate(
                out_net, mosfet_gate_nets, index, snapshot
            )
            if not connected_to_gate:
                errors.append(
                    f"{ref}: Gate driver output (pin {out_pin}, net '{out_net}') "
                    f"does not connect to any MOSFET gate"
                )

    return errors


def _get_mosfet_gate_pin(part_id, kg_store):
    """Get the gate pin number for a MOSFET."""
    if kg_store:
        comp = kg_store.get_component(part_id)
        if comp:
            pin_roles = comp.get('pin_roles', {})
            for pin, role in pin_roles.items():
                if role == 'mosfet_gate':
                    return pin

    # Fallback: known patterns
    if part_id == 'IMZA65R015M2H':
        return '4'
    if part_id == 'IMT65R033M2H':
        return '1'
    if part_id == 'IMLT65R015M2H':
        return '8'
    if part_id == 'IMW65R015M2H':
        return '1'
    if part_id == 'BSC052N08NS5':
        return '4'

    return None


def _get_driver_output_pins(part_id):
    """Get output pin numbers for a gate driver."""
    if part_id == 'UCC5390E':
        return ['6']  # OUT
    if part_id == 'UCC21710':
        return ['4', '6']  # OUTH, OUTL
    if part_id == 'UCC27211':
        return ['3', '8']  # HO, LO
    if part_id == 'UCC27511':
        return ['2', '3']  # OUTH, OUTL
    return []


def _check_path_to_mosfet_gate(start_net, mosfet_gate_nets, index, snapshot):
    """
    Check if there's a path from start_net to any MOSFET gate net.
    Path can go through resistors (gate resistors) and diodes (for separate
    turn-on/turn-off control networks).

    Typical gate drive topologies:
    1. Simple: Driver OUT → R → Gate
    2. Separate Rg_on/Rg_off: Driver OUT → R_on → D_on → Gate
                              Driver OUT → D_off → R_off → Gate
    """
    if start_net in mosfet_gate_nets:
        return True

    # BFS through resistor and diode connections
    # These are the passive components commonly used in gate drive networks
    gate_path_components = {'R', 'D'}

    visited = {start_net}
    queue = [start_net]

    while queue:
        current_net = queue.pop(0)
        net_info = index['nets'].get(current_net, {})

        for endpoint in net_info.get('endpoints', []):
            ref = endpoint.get('ref', '')
            comp = _find_component_by_ref(snapshot, ref)
            if comp and comp.get('part_id') in gate_path_components:
                # Find other net connected to this resistor or diode
                for pin in comp.get('pins', []):
                    other_net = pin.get('net')
                    if other_net and other_net != current_net and other_net not in visited:
                        if other_net in mosfet_gate_nets:
                            return True
                        visited.add(other_net)
                        queue.append(other_net)

    return False


def _find_component_by_ref(snapshot, ref):
    """Find a component by its reference designator."""
    for comp in snapshot.get('components', []):
        if comp.get('ref') == ref:
            return comp
    return None


def _check_gate_resistors(snapshot, index, gate_drivers, mosfets):
    """Check that gate resistors exist between drivers and MOSFETs."""
    errors = []

    for driver in gate_drivers:
        ref = driver.get('ref', '')
        part_id = driver.get('part_id', '')
        output_pins = _get_driver_output_pins(part_id)

        for out_pin in output_pins:
            out_net = _get_pin_net(driver, out_pin)
            if _is_not_connected(out_net):
                continue

            # Check if a resistor is on this net
            has_resistor = False
            net_info = index['nets'].get(out_net, {})
            for endpoint in net_info.get('endpoints', []):
                comp = _find_component_by_ref(snapshot, endpoint.get('ref', ''))
                if comp and comp.get('part_id') == 'R':
                    has_resistor = True
                    break

            if not has_resistor:
                # Check if directly connected to MOSFET gate (no resistor)
                for endpoint in net_info.get('endpoints', []):
                    comp = _find_component_by_ref(snapshot, endpoint.get('ref', ''))
                    if comp and _is_mosfet(comp.get('part_id', '')):
                        # Direct connection without resistor
                        errors.append(
                            f"{ref}: Gate driver output (pin {out_pin}) connects "
                            f"directly to MOSFET {endpoint.get('ref')} without gate resistor"
                        )

    return errors


def _is_mosfet(part_id):
    """Check if part_id is a MOSFET."""
    part_id_upper = part_id.upper()
    return any(pattern in part_id_upper for pattern in MOSFET_PATTERNS)


def _check_kelvin_source_connections(snapshot, index, gate_drivers, mosfets, kg_store):
    """Check that gate driver returns connect to Kelvin Source (not power source)."""
    errors = []

    # Build map of Kelvin Source nets
    ks_nets = {}  # net -> mosfet ref
    power_source_nets = {}  # net -> mosfet ref

    for mosfet in mosfets:
        ref = mosfet.get('ref', '')
        part_id = mosfet.get('part_id', '')

        # Get KS and Source pins
        ks_pin = _get_mosfet_ks_pin(part_id, kg_store)
        source_pins = _get_mosfet_source_pins(part_id, kg_store)

        if ks_pin:
            ks_net = _get_pin_net(mosfet, ks_pin)
            if ks_net and ks_net != 'NC':
                ks_nets[ks_net] = ref

        for src_pin in source_pins:
            src_net = _get_pin_net(mosfet, src_pin)
            if src_net and src_net != 'NC':
                power_source_nets[src_net] = ref

    # Check isolated gate drivers - their GND2 should connect to KS
    for driver in gate_drivers:
        ref = driver.get('ref', '')
        part_id = driver.get('part_id', '')

        if part_id not in ISOLATED_GATE_DRIVERS:
            continue

        # Get driver's secondary ground pin
        gnd2_pin = _get_driver_gnd2_pin(part_id)
        if not gnd2_pin:
            continue

        gnd2_net = _get_pin_net(driver, gnd2_pin)
        if _is_not_connected(gnd2_net):
            errors.append(f"{ref}: Isolated gate driver GND2 (pin {gnd2_pin}) not connected")
            continue

        # Check if connected to KS (good) or power source (bad for MOSFETs with KS)
        if gnd2_net in ks_nets:
            pass  # Good - connected to Kelvin Source
        elif gnd2_net in power_source_nets:
            # Check if this MOSFET has KS pin
            mosfet_ref = power_source_nets[gnd2_net]
            mosfet = _find_component_by_ref(snapshot, mosfet_ref)
            if mosfet:
                mosfet_part_id = mosfet.get('part_id', '')
                ks_pin = _get_mosfet_ks_pin(mosfet_part_id, kg_store)
                if ks_pin:
                    errors.append(
                        f"{ref}: Gate driver GND2 connects to power Source of {mosfet_ref}, "
                        f"but should connect to Kelvin Source (pin {ks_pin}) to avoid "
                        f"common-source inductance"
                    )

    return errors


def _get_mosfet_ks_pin(part_id, kg_store):
    """Get Kelvin Source pin for a MOSFET."""
    if kg_store:
        comp = kg_store.get_component(part_id)
        if comp:
            pin_roles = comp.get('pin_roles', {})
            for pin, role in pin_roles.items():
                if role == 'mosfet_kelvin_source':
                    return pin

    # Fallback
    if part_id == 'IMZA65R015M2H':
        return '3'
    if part_id == 'IMT65R033M2H':
        return '2'
    if part_id == 'IMLT65R015M2H':
        return '7'

    return None


def _get_mosfet_source_pins(part_id, kg_store):
    """Get power Source pins for a MOSFET."""
    if kg_store:
        comp = kg_store.get_component(part_id)
        if comp:
            pin_roles = comp.get('pin_roles', {})
            return [pin for pin, role in pin_roles.items() if role == 'mosfet_source']

    return []


def _get_driver_gnd2_pin(part_id):
    """Get secondary ground pin for an isolated gate driver."""
    if part_id == 'UCC5390E':
        return '7'  # GND2
    if part_id == 'UCC21710':
        return '3'  # COM (secondary side)
    return None


def _check_isolated_supply_connections(snapshot, index, iso_supplies, gate_drivers):
    """Check that isolated supplies connect to gate drivers correctly."""
    errors = []

    for supply in iso_supplies:
        ref = supply.get('ref', '')
        part_id = supply.get('part_id', '')

        # Get output pins
        if part_id == 'MGJ2D121505SC':
            vout_plus = _get_pin_net(supply, '7')  # +VOUT
            vout_zero = _get_pin_net(supply, '6')  # 0V
            vout_minus = _get_pin_net(supply, '5')  # -VOUT

            # Check connections
            if _is_not_connected(vout_plus):
                errors.append(f"{ref}: +VOUT (pin 7) not connected")
            if _is_not_connected(vout_zero):
                errors.append(f"{ref}: 0V (pin 6) not connected")
            if _is_not_connected(vout_minus):
                errors.append(f"{ref}: -VOUT (pin 5) not connected")

            # Check for correct polarity: +VOUT should connect to VDD/VCC2
            # This is harder to verify without more context

    return errors


def _check_bootstrap_connections(snapshot, index, gate_drivers):
    """Check bootstrap capacitor for UCC27211."""
    errors = []

    for driver in gate_drivers:
        ref = driver.get('ref', '')
        part_id = driver.get('part_id', '')

        if part_id != 'UCC27211':
            continue

        # HB (pin 2) and HS (pin 4) should have a capacitor between them
        hb_net = _get_pin_net(driver, '2')
        hs_net = _get_pin_net(driver, '4')

        if _is_not_connected(hb_net):
            errors.append(f"{ref}: Bootstrap pin HB (pin 2) not connected")
            continue
        if _is_not_connected(hs_net):
            errors.append(f"{ref}: Switch node HS (pin 4) not connected")
            continue

        # Check for capacitor between HB and HS
        hb_endpoints = index['nets'].get(hb_net, {}).get('endpoints', [])
        hs_endpoints = index['nets'].get(hs_net, {}).get('endpoints', [])

        # Find capacitors on each net
        hb_caps = set()
        for ep in hb_endpoints:
            comp = _find_component_by_ref(snapshot, ep.get('ref', ''))
            if comp and comp.get('part_id') == 'C':
                hb_caps.add(ep.get('ref'))

        hs_caps = set()
        for ep in hs_endpoints:
            comp = _find_component_by_ref(snapshot, ep.get('ref', ''))
            if comp and comp.get('part_id') == 'C':
                hs_caps.add(ep.get('ref'))

        # Check for common capacitor
        bootstrap_cap = hb_caps & hs_caps
        if not bootstrap_cap:
            errors.append(
                f"{ref}: No bootstrap capacitor found between HB (pin 2, net {hb_net}) "
                f"and HS (pin 4, net {hs_net})"
            )

    return errors

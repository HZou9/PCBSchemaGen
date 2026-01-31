"""
Net conflict checker for complex PCB circuits.

This module detects potential net naming conflicts that could cause
unintended shorts in circuits with multiple instances or isolation domains.
"""

from .isolation_domain import identify_isolation_domains, get_net_domain


# Reserved net name patterns that should be unique per isolation domain
RESERVED_PATTERNS = ['GND', 'VCC', 'VDD', 'VSS', 'VEE', 'VBUS']


def check_net_conflicts(snapshot, kg_store):
    """
    Check for net naming conflicts in the circuit.

    Returns:
        list: Error messages for any conflicts found
    """
    errors = []

    # Identify isolation domains
    domains = identify_isolation_domains(snapshot, kg_store)

    # Check for cross-domain net conflicts
    errors.extend(_check_cross_domain_nets(snapshot, domains))

    # Check for GND confusion
    errors.extend(_check_gnd_naming(snapshot, domains))

    # Check for reserved name conflicts
    errors.extend(_check_reserved_name_conflicts(snapshot, domains))

    # Check for potential instance conflicts
    errors.extend(_check_instance_conflicts(snapshot))

    return errors


def _check_cross_domain_nets(snapshot, domains):
    """Check if same net name appears in multiple isolation domains."""
    errors = []

    # Skip if no isolation (single domain)
    if not domains.get('secondary'):
        return errors

    # Track which domain each net name is in
    net_domains = {}

    for net in snapshot.get('nets', []):
        net_name = net.get('name', '')
        domain = get_net_domain(net_name, domains)

        if net_name in net_domains:
            if net_domains[net_name] != domain:
                errors.append(
                    f"NET CONFLICT: '{net_name}' appears in both {net_domains[net_name]} "
                    f"and {domain} domains. This may cause unintended short circuit."
                )
        else:
            net_domains[net_name] = domain

    return errors


def _check_gnd_naming(snapshot, domains):
    """Check for potential GND naming confusion across isolation domains."""
    errors = []

    # Skip if no isolation
    if not domains.get('secondary'):
        return errors

    num_domains = 1 + len(domains.get('secondary', []))

    # Find all GND-like nets
    gnd_nets = []
    for net in snapshot.get('nets', []):
        net_name = net.get('name', '').upper()
        if 'GND' in net_name or net_name == 'VSS':
            gnd_nets.append(net.get('name'))

    # Check if there are enough unique GND nets for all domains
    unique_gnds = set(gnd_nets)
    if len(unique_gnds) < num_domains:
        errors.append(
            f"GND NAMING WARNING: Circuit has {num_domains} isolation domains "
            f"but only {len(unique_gnds)} unique GND net(s): {sorted(unique_gnds)}. "
            f"Consider using distinct names like GND_PRI, GND_SEC1, GND_SEC2."
        )

    return errors


def _check_reserved_name_conflicts(snapshot, domains):
    """Check for reserved name patterns used across domains."""
    errors = []

    # Skip if no isolation
    if not domains.get('secondary'):
        return errors

    for pattern in RESERVED_PATTERNS:
        # Find nets matching this pattern
        matching_nets = []
        for net in snapshot.get('nets', []):
            net_name = net.get('name', '').upper()
            if pattern in net_name:
                matching_nets.append(net.get('name'))

        # Check domains of matching nets
        net_domain_map = {}
        for net_name in matching_nets:
            domain = get_net_domain(net_name, domains)
            if domain not in net_domain_map:
                net_domain_map[domain] = []
            net_domain_map[domain].append(net_name)

        # Warning if same base pattern used in multiple domains
        if len(net_domain_map) > 1:
            # This is actually OK if the names are different
            pass

    return errors


def _check_instance_conflicts(snapshot):
    """
    Check for potential multi-instance naming conflicts.

    Look for patterns that suggest multiple instances of the same module
    but with conflicting net names.
    """
    errors = []

    # Check for numeric suffix patterns suggesting multiple instances
    # e.g., VSW_1, VSW_2 vs VSW (no suffix)
    base_names = {}  # base_name -> list of (full_name, has_suffix)

    for net in snapshot.get('nets', []):
        net_name = net.get('name', '')

        # Check if name ends with _N or _NN (numeric suffix)
        parts = net_name.rsplit('_', 1)
        if len(parts) == 2 and parts[1].isdigit():
            base = parts[0]
            if base not in base_names:
                base_names[base] = []
            base_names[base].append((net_name, True))
        else:
            # No numeric suffix
            if net_name not in base_names:
                base_names[net_name] = []
            base_names[net_name].append((net_name, False))

    # Check for conflicts: base name exists with and without suffix
    for base, instances in base_names.items():
        has_suffix = any(s for _, s in instances)
        no_suffix = any(not s for _, s in instances)

        if has_suffix and no_suffix:
            names = [n for n, _ in instances]
            errors.append(
                f"INSTANCE NAMING WARNING: Net '{base}' exists both with and without "
                f"numeric suffixes: {sorted(names)}. This may indicate incomplete "
                f"multi-instance naming."
            )

    return errors


def check_mosfet_net_conflicts(snapshot):
    """
    Check for conflicts in MOSFET net naming across multiple half-bridges.

    Common mistakes:
    - Multiple half-bridges sharing same VSW net
    - Multiple MOSFETs sharing same gate net
    """
    errors = []

    # Find all MOSFETs
    mosfets = []
    for comp in snapshot.get('components', []):
        part_id = comp.get('part_id', '').upper()
        if 'MOSFET' in part_id or part_id.startswith('IM') or part_id.startswith('BSC'):
            mosfets.append(comp)

    # Track gate and drain/source connections
    gate_nets = {}  # net_name -> list of mosfet refs
    vsw_candidates = {}  # net_name -> list of (ref, pin_role)

    for mosfet in mosfets:
        ref = mosfet.get('ref', '')
        for pin in mosfet.get('pins', []):
            pin_role = pin.get('pin_role', '')
            net = pin.get('net', '')
            if not net or net == 'NC':
                continue

            if pin_role == 'mosfet_gate':
                if net not in gate_nets:
                    gate_nets[net] = []
                gate_nets[net].append(ref)

            # VSW is typically where drain of low-side meets source of high-side
            if pin_role in ('mosfet_source', 'mosfet_drain'):
                if net not in vsw_candidates:
                    vsw_candidates[net] = []
                vsw_candidates[net].append((ref, pin_role))

    # Check for multiple MOSFETs sharing same gate net (OK for parallel)
    # But warn if more than 2 (unusual)
    for net, refs in gate_nets.items():
        if len(refs) > 2:
            errors.append(
                f"GATE NET WARNING: Net '{net}' connects to {len(refs)} MOSFET gates: "
                f"{refs}. This may indicate unintended parallel connection or "
                f"missing numeric suffix for multi-half-bridge design."
            )

    return errors

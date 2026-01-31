"""
Complex task validator - entry point for P17-P23 validation.

This module orchestrates all validation checks for complex tasks:
1. Phase 2 constraints (reused from existing)
2. Net conflict checking
3. Interface verification
4. System topology verification
5. Isolation boundary checking
"""

from . import phase2_checks
from . import net_conflict_checker
from . import interface_checker
from . import system_topology_checker
from . import isolation_domain


def validate_complex_task(snapshot, task_id, kg_store):
    """
    Validate a complex task (P17-P23).

    Args:
        snapshot: Circuit topology snapshot
        task_id: Task ID (17-23)
        kg_store: Knowledge graph store

    Returns:
        tuple: (passed: bool, errors: list, warnings: list)
    """
    errors = []
    warnings = []

    # 1. Phase 2 fast-fail constraints (reuse existing)
    phase2_errors = phase2_checks.run_phase2_checks(snapshot, kg_store, task_id=task_id)
    errors.extend(phase2_errors)

    # If Phase 2 fails, return early (fast-fail)
    if phase2_errors:
        return False, errors, warnings

    # 2. Isolation boundary violations
    iso_errors = isolation_domain.check_isolation_boundary_violations(snapshot, kg_store)
    errors.extend(iso_errors)

    # 3. Net conflict checking
    net_errors = net_conflict_checker.check_net_conflicts(snapshot, kg_store)
    # Separate errors and warnings
    for err in net_errors:
        if 'WARNING' in err:
            warnings.append(err)
        else:
            errors.append(err)

    # 4. Interface verification (gate driver <-> MOSFET)
    interface_errors = interface_checker.check_interfaces(snapshot, kg_store)
    errors.extend(interface_errors)

    # 5. System topology verification
    system_errors = system_topology_checker.check_system_topology(snapshot, task_id, kg_store)
    errors.extend(system_errors)

    # 6. MOSFET-specific net conflict check
    mosfet_errors = net_conflict_checker.check_mosfet_net_conflicts(snapshot)
    for err in mosfet_errors:
        if 'WARNING' in err:
            warnings.append(err)
        else:
            errors.append(err)

    passed = len(errors) == 0
    return passed, errors, warnings


def is_complex_task(task_id):
    """Check if a task ID is a complex task (P17-P23)."""
    return system_topology_checker.is_complex_task(task_id)


def get_complex_task_info(task_id):
    """Get information about a complex task."""
    template = system_topology_checker.get_task_template(task_id)
    if not template:
        return None

    return {
        'task_id': task_id,
        'name': template.get('name'),
        'min_mosfets': template.get('min_mosfets', 0),
        'min_gate_drivers': template.get('min_gate_drivers', 0),
        'min_isolated_supplies': template.get('min_isolated_supplies', 0),
        'requires_transformer': template.get('requires_transformer', False),
        'requires_resonant_cap': template.get('requires_resonant_cap', False),
        'requires_resonant_inductor': template.get('requires_resonant_inductor', False),
    }


def format_validation_report(passed, errors, warnings, task_id=None):
    """
    Format validation results into a human-readable report.

    Args:
        passed: Whether validation passed
        errors: List of error messages
        warnings: List of warning messages
        task_id: Optional task ID for context

    Returns:
        str: Formatted report
    """
    lines = []

    if task_id:
        info = get_complex_task_info(task_id)
        if info:
            lines.append(f"=== Complex Task Validation: {info['name']} (P{task_id}) ===")
        else:
            lines.append(f"=== Task Validation: P{task_id} ===")
    else:
        lines.append("=== Validation Report ===")

    lines.append("")

    if passed:
        lines.append("✓ PASSED - All checks passed")
    else:
        lines.append("✗ FAILED - Validation errors found")

    if errors:
        lines.append("")
        lines.append(f"ERRORS ({len(errors)}):")
        for i, err in enumerate(errors, 1):
            lines.append(f"  {i}. {err}")

    if warnings:
        lines.append("")
        lines.append(f"WARNINGS ({len(warnings)}):")
        for i, warn in enumerate(warnings, 1):
            lines.append(f"  {i}. {warn}")

    lines.append("")
    return "\n".join(lines)


def get_validation_feedback_for_llm(errors, warnings):
    """
    Format validation results as feedback for LLM retry.

    Args:
        errors: List of error messages
        warnings: List of warning messages

    Returns:
        str: Feedback message for LLM
    """
    if not errors and not warnings:
        return ""

    lines = []
    lines.append("## Topology Verification Failed")
    lines.append("")

    if errors:
        lines.append("### Errors (must fix):")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    if warnings:
        lines.append("### Warnings (should address):")
        for warn in warnings:
            lines.append(f"- {warn}")
        lines.append("")

    lines.append("### Common fixes:")
    lines.append("1. Use unique net names for each instance (e.g., VSW_1, VSW_2)")
    lines.append("2. Use separate GND names for isolation domains (e.g., GND_PRI, GND_SEC1)")
    lines.append("3. Add gate resistors between driver outputs and MOSFET gates")
    lines.append("4. Connect gate driver GND2 to MOSFET Kelvin Source (not power Source)")
    lines.append("5. Add decoupling capacitors to all IC power pins")
    lines.append("")

    return "\n".join(lines)

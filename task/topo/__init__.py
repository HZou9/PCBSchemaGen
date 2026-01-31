"""Topology verification modules."""

from .kg_loader import KGStore, infer_category
from .build_topology import index_snapshot
from .phase2_checks import run_phase2_checks
from .isolation_domain import identify_isolation_domains, check_isolation_boundary_violations
from .net_conflict_checker import check_net_conflicts, check_mosfet_net_conflicts
from .interface_checker import check_interfaces
from .system_topology_checker import check_system_topology, is_complex_task
from .complex_task_validator import (
    validate_complex_task,
    format_validation_report,
    get_validation_feedback_for_llm,
    get_complex_task_info,
)

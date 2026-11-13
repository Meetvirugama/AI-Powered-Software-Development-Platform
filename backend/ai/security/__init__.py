"""Provenance and Taint Tracking Security Package.

Provides data provenance models, taint tracking and propagation engines,
capability-based execution policy enforcement, cryptographically bound approvals,
and structured security audit logging.
"""

from ai.security.provenance import (
    DataProvenance,
    TrustLevel,
    create_provenance,
)
from ai.security.provenance_audit import (
    ProvenanceAuditEvent,
    ProvenanceAuditEventType,
    ProvenanceAuditLogger,
    get_provenance_audit_logger,
    reset_provenance_audit_logger,
)
from ai.security.taint_policy import (
    ActionRiskLevel,
    ExecutionApproval,
    PolicyDecision,
    PolicyEvaluationResult,
    TaintPolicyEngine,
    canonicalize_tool_arguments,
    compute_argument_hash,
    get_taint_policy_engine,
)
from ai.security.taint_tracker import (
    TaintTracker,
    get_taint_tracker,
    reset_taint_tracker,
)

__all__ = [
    "ActionRiskLevel",
    "DataProvenance",
    "ExecutionApproval",
    "PolicyDecision",
    "PolicyEvaluationResult",
    "ProvenanceAuditEvent",
    "ProvenanceAuditEventType",
    "ProvenanceAuditLogger",
    "TaintPolicyEngine",
    "TaintTracker",
    "TrustLevel",
    "canonicalize_tool_arguments",
    "compute_argument_hash",
    "create_provenance",
    "get_provenance_audit_logger",
    "get_taint_policy_engine",
    "get_taint_tracker",
    "reset_provenance_audit_logger",
    "reset_taint_tracker",
]

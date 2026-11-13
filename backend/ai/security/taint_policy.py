"""Taint Policy Engine and Execution Gate.

Reference:
- CaMeL (Capability-based execution policies)
- Design Patterns for Securing LLM Agents (Context-Minimisation & Plan-then-Execute)
- Task Security Specification (§8 Execution Policy & §9 Narrowly Scoped Human Approval)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import logging
import re
from typing import Any, Sequence
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ai.security.provenance import DataProvenance, TrustLevel
from ai.security.provenance_audit import (
    ProvenanceAuditEventType,
    ProvenanceAuditLogger,
    get_provenance_audit_logger,
)
from ai.security.taint_tracker import TaintTracker, get_taint_tracker
from app.core.input_security import UnsafePathError, validate_repo_relative_path
from app.core.secret_redaction import redact, redact_obj

logger = logging.getLogger(__name__)

# Patterns matching sensitive secret files
_PROTECTED_FILE_PATTERNS = (
    re.compile(r"^\.env(\.[a-zA-Z0-9_-]+)?$", re.IGNORECASE),
    re.compile(r"^.*id_rsa(\.pub)?$", re.IGNORECASE),
    re.compile(r"^.*credentials(\.json|\.yml|\.yaml)?$", re.IGNORECASE),
    re.compile(r"^\.github/workflows/.*deploy.*\.ya?ml$", re.IGNORECASE),
    re.compile(r"^.*master\.key$", re.IGNORECASE),
)

_PROTECTED_LITERAL_FILES = frozenset({
    ".env",
    ".env.production",
    ".env.local",
    ".env.test",
    ".github/workflows/deploy.yml",
    "id_rsa",
    "id_ed25519",
})

# Network exfiltration commands
_NETWORK_EXFIL_COMMANDS = frozenset({
    "curl",
    "wget",
    "nc",
    "netcat",
    "ncat",
    "ssh",
    "scp",
    "sftp",
    "telnet",
    "ftp",
})

# Dangerous shell tokens
_SHELL_METACHAR_PATTERN = re.compile(r"[;&|`$><\n\r\x00]")

_FORBIDDEN_FLAGS = frozenset({
    "-c",
    "--command",
    "--upload-pack",
    "--receive-pack",
    "--exec",
    "-o",
    "--override-ini",
    "--rootdir",
    "--import-mode",
})

# Standard safe test commands
_SAFE_COMMAND_PREFIXES = (
    "pytest",
    "python -m unittest",
    "python3 -m unittest",
    "python -m pytest",
    "python3 -m pytest",
    "npm test",
    "npm run test",
    "vitest",
    "npx vitest",
    "git diff",
    "git status",
)


def canonicalize_tool_arguments(arguments: dict[str, Any] | None) -> str:
    """Deterministically serialize tool arguments into a sorted JSON string."""
    if arguments is None:
        arguments = {}
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_argument_hash(arguments: dict[str, Any] | None) -> str:
    """Compute deterministic SHA-256 digest of canonicalized tool arguments."""
    canonical = canonicalize_tool_arguments(arguments)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PolicyDecision(str, Enum):
    """Execution policy determination."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class ActionRiskLevel(str, Enum):
    """Categorized operation risk severity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionApproval(BaseModel):
    """Cryptographically bound, single-use approval for sensitive execution operations."""

    model_config = ConfigDict(frozen=False, extra="ignore")

    approval_id: str = Field(
        default_factory=lambda: f"appr-{uuid4().hex[:12]}",
        description="Unique approval identifier.",
    )
    task_id: str = Field(..., description="Target task ID.")
    step_id: str = Field(..., description="Target step or action identifier.")
    action_type: str = Field(..., description="Action category being approved.")
    resource_scope: list[str] = Field(
        default_factory=list,
        description="List of approved target files or resources.",
    )
    argument_digest: str = Field(
        ...,
        description="SHA-256 hash of canonicalized arguments.",
    )
    provenance_ids: list[str] = Field(
        default_factory=list,
        description="Provenance IDs governing the approved action.",
    )
    approved_by: str = Field(..., description="Identifier of the approving entity.")
    approved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC timestamp of approval grant.",
    )
    expires_at: str = Field(..., description="UTC expiration timestamp.")
    status: str = Field(
        default="approved",
        description="Status: 'approved', 'consumed', 'expired', or 'revoked'.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context, including repository_id and workspace_id.",
    )

    def is_valid_for(
        self,
        *,
        task_id: str,
        action_type: str,
        arguments: dict[str, Any] | None,
        resource_scope: list[str] | None = None,
        repository_id: str | None = None,
    ) -> bool:
        """Verify that this approval strictly matches all contextual execution bounds."""
        if self.status != "approved":
            return False

        # Expiration check
        try:
            exp = datetime.fromisoformat(self.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                self.status = "expired"
                return False
        except Exception:
            return False

        # Task binding
        if str(self.task_id) != str(task_id):
            return False

        # Action type binding
        if self.action_type.lower() != action_type.lower():
            return False

        # Cryptographic argument binding
        expected_hash = compute_argument_hash(arguments)
        if self.argument_digest != expected_hash:
            return False

        # Repository binding if specified
        if repository_id and "repository_id" in self.metadata:
            if str(self.metadata["repository_id"]) != str(repository_id):
                return False

        # Resource scope binding
        if resource_scope:
            approved_scope = set(self.resource_scope)
            for res in resource_scope:
                if res not in approved_scope:
                    return False

        return True

    def consume(self) -> None:
        """Mark approval as atomically consumed."""
        self.status = "consumed"


class PolicyEvaluationResult(BaseModel):
    """Result of an execution policy evaluation."""

    decision: PolicyDecision
    reason: str
    action_risk: ActionRiskLevel = ActionRiskLevel.LOW
    approval_required: bool = False
    matching_approval_id: str | None = None
    denial_reason: str | None = None

    @property
    def is_allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW


class TaintPolicyEngine:
    """Enforces capability-based policies across untrusted inputs and tool execution boundaries."""

    def __init__(
        self,
        tracker: TaintTracker | None = None,
        audit_logger: ProvenanceAuditLogger | None = None,
        protected_files: Sequence[str] | None = None,
    ) -> None:
        self.tracker = tracker or get_taint_tracker()
        self.audit_logger = audit_logger or get_provenance_audit_logger()
        self._protected_files = set(protected_files or _PROTECTED_LITERAL_FILES)

    def is_protected_file(self, file_path: str) -> bool:
        """Check if file path targets a secret or protected configuration file."""
        norm = file_path.strip()
        while norm.startswith("./"):
            norm = norm[2:]
        if norm in self._protected_files:
            return True
        for pat in _PROTECTED_FILE_PATTERNS:
            if pat.match(norm) or pat.match(norm.split("/")[-1]):
                return True
        return False

    def check_taint(self, provenance_ids: list[str]) -> bool:
        """Determine if any associated provenance ID is tainted. Fails closed."""
        if not provenance_ids:
            # Missing provenance fails closed for policy evaluation
            return True
        for pid in provenance_ids:
            if self.tracker.is_tainted(pid):
                return True
        return False

    def evaluate(
        self,
        *,
        action_type: str,
        arguments: dict[str, Any] | None = None,
        target_files: list[str] | None = None,
        provenance_ids: list[str] | None = None,
        task_id: str | None = None,
        repository_id: str | None = None,
        workspace_id: str | None = None,
        approvals: list[ExecutionApproval] | None = None,
    ) -> PolicyEvaluationResult:
        """Evaluate an operation against taint tracking and capability policies."""
        clean_action = str(action_type or "edit").lower().strip()
        args = dict(arguments or {})
        files = list(target_files or [])
        prov_ids = list(provenance_ids or [])
        is_tainted = self.check_taint(prov_ids)

        # 1. Inspect target files for protected secret paths
        for f in files:
            try:
                validate_repo_relative_path(f)
            except UnsafePathError as exc:
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.DENY,
                    reason=f"Unsafe file path '{f}': {exc}",
                    action_risk=ActionRiskLevel.HIGH,
                    denial_reason=str(exc),
                )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            if self.is_protected_file(f):
                # Never allow writing, patching, deleting, or tainted-reading protected secrets
                if clean_action in ("edit", "modify", "write", "create", "patch", "delete", "rm") or is_tainted:
                    res = PolicyEvaluationResult(
                        decision=PolicyDecision.DENY,
                        reason=f"Operation '{clean_action}' on protected secret/configuration file '{f}' is prohibited.",
                        action_risk=ActionRiskLevel.CRITICAL,
                        denial_reason="PROTECTED_FILE_ACCESS",
                    )
                    self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                    return res

        # 2. Inspect / Read Operations
        if clean_action in ("inspect", "read", "grep", "search", "list_dir"):
            res = PolicyEvaluationResult(
                decision=PolicyDecision.ALLOW,
                reason="Repository inspection permitted within workspace bounds.",
                action_risk=ActionRiskLevel.LOW,
            )
            self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
            return res

        # 3. Code Modifications (edit, create, patch, refactor)
        if clean_action in ("edit", "modify", "create", "write", "patch", "refactor"):
            # Legitimate bug fixing from tainted issue is permitted within workspace bounds on safe files
            res = PolicyEvaluationResult(
                decision=PolicyDecision.ALLOW,
                reason="Workspace code modification authorized on non-protected files.",
                action_risk=ActionRiskLevel.MEDIUM if is_tainted else ActionRiskLevel.LOW,
            )
            self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
            return res

        # 4. File Deletion
        if clean_action in ("delete", "rm"):
            # Tainted file deletion requires human approval
            if is_tainted:
                matched = self._find_matching_approval(
                    approvals=approvals,
                    task_id=task_id,
                    action_type=clean_action,
                    arguments=args,
                    resource_scope=files,
                    repository_id=repository_id,
                )
                if matched:
                    res = PolicyEvaluationResult(
                        decision=PolicyDecision.ALLOW,
                        reason="File deletion authorized by validated human approval.",
                        action_risk=ActionRiskLevel.HIGH,
                        matching_approval_id=matched.approval_id,
                    )
                else:
                    res = PolicyEvaluationResult(
                        decision=PolicyDecision.REQUIRES_APPROVAL,
                        reason="Deletion of files influenced by untrusted input requires explicit human approval.",
                        action_risk=ActionRiskLevel.HIGH,
                        approval_required=True,
                    )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            res = PolicyEvaluationResult(
                decision=PolicyDecision.ALLOW,
                reason="File deletion permitted for trusted task scope.",
                action_risk=ActionRiskLevel.MEDIUM,
            )
            self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
            return res

        # 5. Shell Command Operations
        if clean_action in ("command", "execute_command", "run_command", "bash", "sh", "exec", "test", "verify"):
            cmd = str(args.get("command", "") or args.get("cmd", "")).strip()

            # Check for network exfiltration commands
            cmd_tokens = [tok.lower() for tok in cmd.split()]
            if any(net_cmd in cmd_tokens for net_cmd in _NETWORK_EXFIL_COMMANDS):
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.DENY,
                    reason=f"Outbound network execution command '{cmd}' is prohibited.",
                    action_risk=ActionRiskLevel.CRITICAL,
                    denial_reason="NETWORK_EXFILTRATION_PROHIBITED",
                )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            # Check for secret exfiltration (cat .env, env, printenv)
            if any(f in cmd.lower() for f in (".env", "id_rsa", "credentials", "printenv")):
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.DENY,
                    reason=f"Command accessing secrets or environment variables is prohibited: '{cmd}'.",
                    action_risk=ActionRiskLevel.CRITICAL,
                    denial_reason="SECRET_ACCESS_COMMAND_PROHIBITED",
                )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            # Check shell metacharacters
            if _SHELL_METACHAR_PATTERN.search(cmd):
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.DENY,
                    reason="Command contains forbidden shell metacharacters or chaining operators.",
                    action_risk=ActionRiskLevel.HIGH,
                    denial_reason="SHELL_METACHARACTERS_PROHIBITED",
                )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            # Check forbidden flags
            if any(flg in cmd.split() for flg in _FORBIDDEN_FLAGS):
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.DENY,
                    reason="Command contains prohibited execution flags.",
                    action_risk=ActionRiskLevel.HIGH,
                    denial_reason="FORBIDDEN_COMMAND_FLAGS",
                )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            # Safe test runner commands can execute autonomously
            is_safe_cmd = any(cmd.startswith(prefix) for prefix in _SAFE_COMMAND_PREFIXES)
            if is_safe_cmd:
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.ALLOW,
                    reason="Safe testing/verification command permitted.",
                    action_risk=ActionRiskLevel.LOW,
                )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            # Arbitrary commands from tainted source require approval
            if is_tainted:
                matched = self._find_matching_approval(
                    approvals=approvals,
                    task_id=task_id,
                    action_type=clean_action,
                    arguments=args,
                    resource_scope=files,
                    repository_id=repository_id,
                )
                if matched:
                    res = PolicyEvaluationResult(
                        decision=PolicyDecision.ALLOW,
                        reason="Shell command execution authorized by validated human approval.",
                        action_risk=ActionRiskLevel.HIGH,
                        matching_approval_id=matched.approval_id,
                    )
                else:
                    res = PolicyEvaluationResult(
                        decision=PolicyDecision.REQUIRES_APPROVAL,
                        reason=f"Untrusted-derived shell command '{cmd}' requires explicit human approval.",
                        action_risk=ActionRiskLevel.HIGH,
                        approval_required=True,
                    )
                self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
                return res

            # Trusted arbitrary command
            res = PolicyEvaluationResult(
                decision=PolicyDecision.ALLOW,
                reason="Command execution authorized under trusted policy.",
                action_risk=ActionRiskLevel.MEDIUM,
            )
            self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
            return res

        # 6. Publication / Pull Request
        if clean_action in ("publish", "pull_request", "publish_pr"):
            matched = self._find_matching_approval(
                approvals=approvals,
                task_id=task_id,
                action_type=clean_action,
                arguments=args,
                resource_scope=files,
                repository_id=repository_id,
            )
            if matched:
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.ALLOW,
                    reason="Publication authorized by human approval.",
                    action_risk=ActionRiskLevel.HIGH,
                    matching_approval_id=matched.approval_id,
                )
            else:
                res = PolicyEvaluationResult(
                    decision=PolicyDecision.REQUIRES_APPROVAL,
                    reason="Publishing changes requires human review and authorization.",
                    action_risk=ActionRiskLevel.HIGH,
                    approval_required=True,
                )
            self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
            return res

        # Default fallback: safe allow for low-risk unhandled actions
        res = PolicyEvaluationResult(
            decision=PolicyDecision.ALLOW,
            reason=f"Action '{clean_action}' permitted under default policy.",
            action_risk=ActionRiskLevel.LOW,
        )
        self._record_audit(task_id, None, clean_action, prov_ids, res, files, args)
        return res

    def evaluate_step(
        self,
        step: Any,
        task_id: str,
        repository_id: str | None = None,
        workspace_id: str | None = None,
        approvals: list[ExecutionApproval] | None = None,
        step_input: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        """Evaluate a PlanStep object before execution in AgentExecutionLoop."""
        step_id = getattr(step, "step_id", "unknown")
        action_type = getattr(step, "action_type", None) or getattr(step, "step_type", "edit")
        expected_files = list(getattr(step, "expected_files", []) or getattr(step, "target_files", []) or [])
        prov_ids = list(getattr(step, "provenance_ids", []) or [])
        if getattr(step, "provenance", None):
            prov_ids.append(step.provenance.provenance_id)

        # Merge step arguments
        args: dict[str, Any] = dict(step_input or {})
        if hasattr(step, "command") and getattr(step, "command", None):
            args["command"] = getattr(step, "command")

        res = self.evaluate(
            action_type=action_type,
            arguments=args,
            target_files=expected_files,
            provenance_ids=prov_ids,
            task_id=task_id,
            repository_id=repository_id,
            workspace_id=workspace_id,
            approvals=approvals,
        )
        return res

    def create_approval(
        self,
        *,
        task_id: str,
        step_id: str,
        action_type: str,
        arguments: dict[str, Any] | None,
        provenance_ids: list[str] | None = None,
        resource_scope: list[str] | None = None,
        approved_by: str = "human_operator",
        ttl_seconds: int = 3600,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionApproval:
        """Issue an ExecutionApproval cryptographically bound to the canonical argument hash."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        arg_digest = compute_argument_hash(arguments)

        clean_meta = redact_obj(dict(metadata or {}))
        approval = ExecutionApproval(
            task_id=str(task_id),
            step_id=str(step_id),
            action_type=action_type.lower(),
            resource_scope=list(resource_scope or []),
            argument_digest=arg_digest,
            provenance_ids=list(provenance_ids or []),
            approved_by=approved_by,
            approved_at=now.isoformat(),
            expires_at=expires.isoformat(),
            status="approved",
            metadata=clean_meta,
        )

        self.audit_logger.record_event(
            event_type=ProvenanceAuditEventType.EXECUTION_APPROVED,
            task_id=task_id,
            step_id=step_id,
            action_type=action_type,
            provenance_ids=provenance_ids,
            policy_decision="APPROVED",
            reason=f"Approval granted by {approved_by} (hash: {arg_digest[:12]})",
            resource_scope=resource_scope,
        )

        return approval

    def _find_matching_approval(
        self,
        approvals: list[ExecutionApproval] | None,
        task_id: str | None,
        action_type: str,
        arguments: dict[str, Any] | None,
        resource_scope: list[str] | None,
        repository_id: str | None,
    ) -> ExecutionApproval | None:
        """Find and validate a matching unconsumed approval record."""
        if not approvals or not task_id:
            return None

        for app in approvals:
            if app.is_valid_for(
                task_id=task_id,
                action_type=action_type,
                arguments=arguments,
                resource_scope=resource_scope,
                repository_id=repository_id,
            ):
                return app
        return None

    def _record_audit(
        self,
        task_id: str | None,
        step_id: str | None,
        action_type: str,
        provenance_ids: list[str],
        result: PolicyEvaluationResult,
        resource_scope: list[str],
        arguments: dict[str, Any],
    ) -> None:
        """Record evaluation event in audit logger."""
        event_type = ProvenanceAuditEventType.EXECUTION_POLICY_EVALUATED
        if result.decision == PolicyDecision.DENY:
            event_type = ProvenanceAuditEventType.EXECUTION_DENIED
        elif result.decision == PolicyDecision.REQUIRES_APPROVAL:
            event_type = ProvenanceAuditEventType.EXECUTION_APPROVAL_REQUIRED

        self.audit_logger.record_event(
            event_type=event_type,
            task_id=task_id,
            step_id=step_id,
            action_type=action_type,
            provenance_ids=provenance_ids,
            policy_decision=result.decision.value,
            reason=result.reason,
            resource_scope=resource_scope,
            metadata={"arguments": redact_obj(arguments), "risk": result.action_risk.value},
        )


_GLOBAL_POLICY_ENGINE = TaintPolicyEngine()


def get_taint_policy_engine() -> TaintPolicyEngine:
    """Return global singleton TaintPolicyEngine."""
    return _GLOBAL_POLICY_ENGINE


__all__ = [
    "ActionRiskLevel",
    "ExecutionApproval",
    "PolicyDecision",
    "PolicyEvaluationResult",
    "TaintPolicyEngine",
    "canonicalize_tool_arguments",
    "compute_argument_hash",
    "get_taint_policy_engine",
]

"""Unified Rule Registry for Bug Detection & Defect Scanning.

Part of Phase 3: Hybrid Candidate Discovery & Rule Registry (task.md).
Centralized catalog of deterministic defect rules, security patterns,
language applicability, CWE references, and remediation guidance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DefectRule:
    """A registered defect detection rule."""
    rule_id: str
    name: str
    category: str  # "security", "null_safety", "resource_leak", "boundary_condition", "unhandled_exception", "configuration", "logic_error"
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"
    description: str
    languages: list[str] = field(default_factory=lambda: ["python", "javascript", "typescript"])
    remediation_template: str = ""
    cwe_id: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "languages": self.languages,
            "remediation_template": self.remediation_template,
            "cwe_id": self.cwe_id,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


class RuleRegistry:
    """Manages rule metadata, language support, versions and defect classification."""

    _instance: RuleRegistry | None = None

    def __init__(self) -> None:
        self._rules: dict[str, DefectRule] = {}
        self._populate_default_rules()

    @classmethod
    def get_instance(cls) -> RuleRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, rule: DefectRule) -> None:
        """Register or override a defect rule."""
        self._rules[rule.rule_id] = rule

    def get(self, rule_id: str) -> DefectRule | None:
        """Retrieve a rule by its unique identifier."""
        return self._rules.get(rule_id)

    def list_rules(
        self,
        category: str | None = None,
        language: str | None = None,
        severity: str | None = None,
    ) -> list[DefectRule]:
        """Query rules matching optional category, language, or severity filters."""
        rules = list(self._rules.values())
        if category:
            rules = [r for r in rules if r.category.lower() == category.lower()]
        if language:
            lang_clean = language.lower()
            rules = [r for r in rules if "all" in r.languages or lang_clean in [l.lower() for l in r.languages]]
        if severity:
            rules = [r for r in rules if r.severity.upper() == severity.upper()]
        return [r for r in rules if r.enabled]

    def _populate_default_rules(self) -> None:
        """Initialize built-in defect and security rules."""
        defaults = [
            # Security: Taint and Injection
            DefectRule(
                rule_id="TAINT-SQL-001",
                name="SQL Injection via Untrusted Input",
                category="security",
                severity="CRITICAL",
                description="Untrusted user input reaches a database query execution sink without parameterized binding.",
                languages=["python", "javascript", "typescript"],
                remediation_template="Use parameterized queries (e.g. `execute(sql, (param,))`) or ORM models instead of string interpolation.",
                cwe_id="CWE-89",
            ),
            DefectRule(
                rule_id="TAINT-CMD-001",
                name="Command Injection via Untrusted Input",
                category="security",
                severity="CRITICAL",
                description="Untrusted user input is passed directly to an operating system command execution shell.",
                languages=["python", "javascript", "typescript"],
                remediation_template="Avoid shell execution; pass arguments as an explicit sequence to `subprocess.run(..., shell=False)`.",
                cwe_id="CWE-78",
            ),
            DefectRule(
                rule_id="TAINT-PATH-001",
                name="Path Traversal via Untrusted Input",
                category="security",
                severity="HIGH",
                description="Untrusted file path reaches a filesystem operation without canonical validation or basename stripping.",
                languages=["python", "javascript", "typescript"],
                remediation_template="Use `os.path.basename()` or verify resolved path stays within safe base directory.",
                cwe_id="CWE-22",
            ),
            DefectRule(
                rule_id="SEC-AUTH-001",
                name="Hardcoded Secret or Insecure Credential",
                category="security",
                severity="CRITICAL",
                description="Plaintext password, token, or private key detected in source code.",
                languages=["python", "javascript", "typescript", "all"],
                remediation_template="Extract secrets into environment variables and reference via configuration management.",
                cwe_id="CWE-798",
            ),
            DefectRule(
                rule_id="SEC-SSRF-001",
                name="Server-Side Request Forgery (SSRF)",
                category="security",
                severity="HIGH",
                description="Unsanitized URL supplied by user passed directly to external HTTP client.",
                languages=["python", "javascript", "typescript"],
                remediation_template="Validate target host against an allowed domain whitelist before issuing request.",
                cwe_id="CWE-918",
            ),

            # Resource Management
            DefectRule(
                rule_id="RES-LEAK-001",
                name="Unclosed File or Resource Leak",
                category="resource_leak",
                severity="MEDIUM",
                description="Resource opened without using a context manager (`with` block) or explicit finally close.",
                languages=["python", "javascript", "typescript"],
                remediation_template="Wrap resource allocation in a `with` statement or ensure guaranteed cleanup in a `finally` block.",
                cwe_id="CWE-775",
            ),

            # Null Safety
            DefectRule(
                rule_id="NULL-DEREF-001",
                name="Potential Null / None Dereference",
                category="null_safety",
                severity="HIGH",
                description="Attribute or method accessed on a reference that can be None without preceding guard check.",
                languages=["python", "javascript", "typescript"],
                remediation_template="Add an explicit null guard (`if item is not None:`) or use optional chaining.",
                cwe_id="CWE-476",
            ),

            # Boundary Condition & Off-by-one
            DefectRule(
                rule_id="BOUND-OBO-001",
                name="Off-by-One Array Boundary Indexing",
                category="boundary_condition",
                severity="MEDIUM",
                description="Array or sequence accessed with `<=` length or index out of expected range bounds.",
                languages=["python", "javascript", "typescript"],
                remediation_template="Ensure index boundary uses `< len(collection)` or bounds-checked slicing.",
                cwe_id="CWE-193",
            ),

            # Exception Handling
            DefectRule(
                rule_id="EXC-BARE-001",
                name="Bare Except or Ignored Exception",
                category="unhandled_exception",
                severity="LOW",
                description="Catching generic `Exception` or bare `except:` without logging or handling hides fatal errors.",
                languages=["python"],
                remediation_template="Catch specific exception types and log error trace.",
                cwe_id="CWE-391",
            ),

            # Configuration & Insecure Defaults
            DefectRule(
                rule_id="CFG-DEBUG-001",
                name="Insecure Debug Mode Enabled in Production",
                category="configuration",
                severity="HIGH",
                description="Application framework configured with `debug=True` or wildcard CORS in production environment.",
                languages=["python", "javascript", "typescript", "all"],
                remediation_template="Ensure `debug` is driven by environment variable and defaults to False in production.",
                cwe_id="CWE-489",
            ),
        ]

        for rule in defaults:
            self._rules[rule.rule_id] = rule


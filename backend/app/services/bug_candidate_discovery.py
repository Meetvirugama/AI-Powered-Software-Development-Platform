"""Hybrid Candidate Discovery Service for Bug Detection.

Part of Phase 3: Hybrid Candidate Discovery & Rule Registry (task.md).
Coordinates inexpensive, deterministic analyzers (AST rules, taint analysis,
configuration checks, and change-risk heuristics) to produce normalized BugCandidates.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import UUID

from scanner.ast_rules import ASTBugAnalyzer
from scanner.rule_registry import DefectRule, RuleRegistry
from scanner.static_bug_scanner import StaticBugScanner
from scanner.taint_analyzer import TaintAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class BugCandidate:
    """Normalized defect candidate discovered during Stage B."""
    candidate_id: str
    rule_id: str
    file_path: str
    start_line: int
    end_line: int
    category: str  # "security", "null_safety", "resource_leak", "boundary_condition", "unhandled_exception", "configuration", "logic_error"
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"
    evidence: str
    source_type: str  # "STATIC", "TAINT", "CONFIG", "CHANGE_RISK"
    confidence: str = "high"
    remediation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rule_id": self.rule_id,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "category": self.category,
            "severity": self.severity,
            "evidence": self.evidence,
            "source_type": self.source_type,
            "confidence": self.confidence,
            "remediation": self.remediation,
            "metadata": self.metadata,
        }


class BugCandidateDiscoveryService:
    """Combines deterministic AST rules, taint analyzer, config checks, and change-risk analysis."""

    def __init__(
        self,
        static_scanner: StaticBugScanner | None = None,
        taint_analyzer: TaintAnalyzer | None = None,
        rule_registry: RuleRegistry | None = None,
    ) -> None:
        self.static_scanner = static_scanner or StaticBugScanner()
        self.taint_analyzer = taint_analyzer or TaintAnalyzer()
        self.rule_registry = rule_registry or RuleRegistry.get_instance()

    def discover_candidates(
        self,
        *,
        file_path: str,
        code_content: str,
        language: str = "python",
        scan_mode: str = "standard",  # "quick" | "standard" | "deep" | "change"
        changed_files: Sequence[str] | None = None,
        repository_id: UUID | None = None,
    ) -> list[BugCandidate]:
        """Run multi-detector discovery and normalize candidates."""
        if not code_content or not code_content.strip():
            return []

        candidates: list[BugCandidate] = []

        # 1. Deterministic AST Bug Scanning
        candidates.extend(self._discover_ast_candidates(code_content, file_path))

        # 2. Source-to-Sink Taint Analysis (Security)
        candidates.extend(self._discover_taint_candidates(code_content, file_path, language))

        # 3. Insecure Configuration & Secret Checks
        candidates.extend(self._discover_config_candidates(code_content, file_path))

        # 4. Change-risk and Regression Heuristics (for "change" or "deep" modes)
        if scan_mode in ("change", "deep") or changed_files:
            candidates.extend(
                self._discover_change_risk_candidates(
                    code_content=code_content,
                    file_path=file_path,
                    changed_files=changed_files or [],
                )
            )

        # 5. Deduplicate and normalize
        return self._deduplicate_candidates(candidates)

    def _discover_ast_candidates(self, code: str, file_path: str) -> list[BugCandidate]:
        """Extract and normalize candidates from AST rule scanner."""
        scan_res = self.static_scanner.scan_code(content=code, file_path=file_path)
        findings = scan_res.get("findings", [])
        candidates: list[BugCandidate] = []

        for i, f in enumerate(findings):
            rule_id = f.get("rule_id", f"AST-RULE-{i+1}")
            category = f.get("category", "logic_error")
            severity = (f.get("severity") or "MEDIUM").upper()
            start_l = f.get("line_number") or f.get("line", 1)
            end_l = f.get("end_line") or start_l

            reg_rule = self.rule_registry.get(rule_id)
            remediation = f.get("remediation") or (reg_rule.remediation_template if reg_rule else "")

            candidates.append(
                BugCandidate(
                    candidate_id=f"cand-ast-{i+1}-{start_l}",
                    rule_id=rule_id,
                    file_path=file_path,
                    start_line=start_l,
                    end_line=end_l,
                    category=category,
                    severity=severity,
                    evidence=f.get("evidence") or f.get("message") or f.get("title", ""),
                    source_type="STATIC",
                    confidence="high" if f.get("is_structural", True) else "medium",
                    remediation=remediation,
                    metadata={"enclosing_symbol": f.get("enclosing_symbol")},
                )
            )
        return candidates

    def _discover_taint_candidates(
        self,
        code: str,
        file_path: str,
        language: str,
    ) -> list[BugCandidate]:
        """Extract and normalize candidates from Taint Analyzer."""
        taint_results = self.taint_analyzer.analyze_source(code, file_path=file_path, language=language)
        candidates: list[BugCandidate] = []

        for i, t in enumerate(taint_results):
            # Only include high-confidence unsanitized flows as primary candidates
            # (sanitized flows are kept if severity is medium or higher)
            if t.is_sanitized and t.severity == "LOW":
                continue

            candidates.append(
                BugCandidate(
                    candidate_id=f"cand-taint-{i+1}-{t.start_line}",
                    rule_id=t.rule_id,
                    file_path=file_path,
                    start_line=t.start_line,
                    end_line=t.end_line,
                    category=t.category,
                    severity=t.severity,
                    evidence=t.evidence,
                    source_type="TAINT",
                    confidence=t.confidence,
                    remediation=t.remediation,
                    metadata={
                        "source": t.source.to_dict(),
                        "sink": t.sink.to_dict(),
                        "vulnerability_type": t.vulnerability_type,
                        "sanitizers_found": [s.name for s in t.sanitizers_found],
                    },
                )
            )
        return candidates

    def _discover_config_candidates(self, code: str, file_path: str) -> list[BugCandidate]:
        """Detect common insecure configuration patterns in configs/routers."""
        candidates: list[BugCandidate] = []
        lines = code.splitlines()

        debug_pattern = re.compile(r'^\s*(?:DEBUG|debug)\s*=\s*True\b')
        cors_pattern = re.compile(r'allow_origins\s*=\s*\[\s*["\']\*["\']\s*\]')

        for i, line in enumerate(lines, start=1):
            if debug_pattern.search(line):
                candidates.append(
                    BugCandidate(
                        candidate_id=f"cand-cfg-debug-{i}",
                        rule_id="CFG-DEBUG-001",
                        file_path=file_path,
                        start_line=i,
                        end_line=i,
                        category="configuration",
                        severity="HIGH",
                        evidence="Application has `debug=True` hardcoded.",
                        source_type="CONFIG",
                        confidence="high",
                        remediation="Drive debug flag via environment variable, defaulting to False in production.",
                    )
                )
            if cors_pattern.search(line):
                candidates.append(
                    BugCandidate(
                        candidate_id=f"cand-cfg-cors-{i}",
                        rule_id="CFG-CORS-001",
                        file_path=file_path,
                        start_line=i,
                        end_line=i,
                        category="security",
                        severity="MEDIUM",
                        evidence="Wildcard CORS origins `allow_origins=['*']` detected.",
                        source_type="CONFIG",
                        confidence="medium",
                        remediation="Restrict CORS allowed origins to specific trusted domains.",
                    )
                )

        return candidates

    def _discover_change_risk_candidates(
        self,
        code_content: str,
        file_path: str,
        changed_files: Sequence[str],
    ) -> list[BugCandidate]:
        """Analyze change risk heuristics on modified files."""
        candidates: list[BugCandidate] = []
        lines = code_content.splitlines()

        # Check for modified critical signatures or breaking interface alterations
        todo_fixme_pattern = re.compile(r'#\s*(?:TODO|FIXME|BUG|HACK):\s*(.+)', re.IGNORECASE)

        for i, line in enumerate(lines, start=1):
            match = todo_fixme_pattern.search(line)
            if match:
                comment = match.group(1).strip()
                if any(w in comment.lower() for w in ("bug", "broken", "temporary", "fixme", "crash")):
                    candidates.append(
                        BugCandidate(
                            candidate_id=f"cand-change-risk-{i}",
                            rule_id="RISK-UNRESOLVED-001",
                            file_path=file_path,
                            start_line=i,
                            end_line=i,
                            category="logic_error",
                            severity="LOW",
                            evidence=f"Unresolved defect comment ({match.group(0).strip()}): '{comment}'",
                            source_type="CHANGE_RISK",
                            confidence="medium",
                            remediation="Resolve and verify fix before committing changes.",
                        )
                    )

        return candidates

    def _deduplicate_candidates(self, candidates: list[BugCandidate]) -> list[BugCandidate]:
        """Deduplicate candidates on (file_path, start_line, category) keeping highest severity."""
        severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
        seen: dict[tuple[str, int, str], BugCandidate] = {}

        for cand in candidates:
            key = (cand.file_path, cand.start_line, cand.category)
            if key not in seen:
                seen[key] = cand
            else:
                existing = seen[key]
                if severity_rank.get(cand.severity, 0) > severity_rank.get(existing.severity, 0):
                    seen[key] = cand

        return list(seen.values())

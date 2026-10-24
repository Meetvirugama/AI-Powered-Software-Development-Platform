"""Combine AST bug analysis with normalized static-review findings."""

from typing import Any

from scanner.ast_rules import ASTBugAnalyzer


class StaticBugScanner:
    """Run AST rules and return normalized findings."""

    def __init__(self, analyzer: ASTBugAnalyzer | None = None) -> None:
        self.analyzer = analyzer or ASTBugAnalyzer()

    def scan(
        self,
        *,
        repository_id: Any = None,
        file_path: str = "snippet.py",
        code_content: str = "",
        target: Any = None,
        repo_root: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Adapter method compatible with analysis orchestrator hooks."""
        if not code_content:
            return {
                "success": True,
                "file_path": file_path,
                "parse_status": "empty",
                "has_syntax_errors": False,
                "error_message": None,
                "findings": [],
                "rules_evaluated": 0,
            }
        return self.scan_code(
            content=code_content,
            file_path=file_path,
            repo_root=repo_root,
        )

    def scan_code(
        self,
        content: str,
        file_path: str,
        *,
        repo_root: str | None = None,
    ) -> dict[str, Any]:
        """Analyze source code and return findings plus parse status."""

        result = self.analyzer.analyze_code(
            content=content,
            file_path=file_path,
        )

        findings = self.analyzer.to_static_findings(result.findings)

        return {
            "success": result.success,
            "file_path": result.file_path,
            "parse_status": result.parse_status,
            "has_syntax_errors": result.has_syntax_errors,
            "error_message": result.error_message,
            "findings": findings,
            "rules_evaluated": result.rules_evaluated,
        }

    def scan_file(
        self,
        file_path: str,
        *,
        repo_root: str,
    ) -> dict[str, Any]:
        """Analyze a file under a repository root."""

        result = self.analyzer.analyze_file(
            file_path=file_path,
            repo_root=repo_root,
        )

        return {
            "success": result.success,
            "file_path": result.file_path,
            "parse_status": result.parse_status,
            "has_syntax_errors": result.has_syntax_errors,
            "error_message": result.error_message,
            "findings": self.analyzer.to_static_findings(result.findings),
            "rules_evaluated": result.rules_evaluated,
        }

"""Combine AST bug analysis with normalized static-review findings."""

import asyncio
import concurrent.futures
import logging
from typing import Any

from scanner.ast_rules import ASTBugAnalyzer

logger = logging.getLogger(__name__)


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

    def scan_files(
        self,
        file_paths: list[str],
        *,
        repo_root: str,
        parallel: bool = True,
    ) -> dict[str, Any]:
        """Analyze multiple files under a repository root, optionally in parallel."""
        findings: list[dict[str, Any]] = []
        file_results: list[dict[str, Any]] = []
        total_rules_evaluated = 0
        overall_success = True

        if not file_paths:
            return {
                "success": True,
                "findings": [],
                "file_results": [],
                "files_scanned": 0,
                "total_findings": 0,
                "rules_evaluated": 0,
            }

        if parallel and len(file_paths) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(file_paths), 8)) as executor:
                future_to_file = {
                    executor.submit(self.scan_file, fp, repo_root=repo_root): fp
                    for fp in file_paths
                }
                results_map: dict[str, dict[str, Any]] = {}
                for future in concurrent.futures.as_completed(future_to_file):
                    fp = future_to_file[future]
                    try:
                        results_map[fp] = future.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Error scanning file %s: %s", fp, exc)
                        results_map[fp] = {
                            "success": False,
                            "file_path": fp,
                            "parse_status": "error",
                            "has_syntax_errors": False,
                            "error_message": str(exc),
                            "findings": [],
                            "rules_evaluated": 0,
                        }
                ordered_results = [results_map[fp] for fp in file_paths]
        else:
            ordered_results = []
            for fp in file_paths:
                try:
                    ordered_results.append(self.scan_file(fp, repo_root=repo_root))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error scanning file %s: %s", fp, exc)
                    ordered_results.append({
                        "success": False,
                        "file_path": fp,
                        "parse_status": "error",
                        "has_syntax_errors": False,
                        "error_message": str(exc),
                        "findings": [],
                        "rules_evaluated": 0,
                    })

        for res in ordered_results:
            if not res.get("success", False):
                overall_success = False
            total_rules_evaluated += res.get("rules_evaluated", 0)
            findings.extend(res.get("findings", []))
            file_results.append(res)

        return {
            "success": overall_success,
            "findings": findings,
            "file_results": file_results,
            "files_scanned": len(file_paths),
            "total_findings": len(findings),
            "rules_evaluated": total_rules_evaluated,
        }

    async def scan_files_async(
        self,
        file_paths: list[str],
        *,
        repo_root: str,
    ) -> dict[str, Any]:
        """Asynchronously analyze multiple files under a repository root using threadpool."""
        return await asyncio.to_thread(
            self.scan_files, file_paths, repo_root=repo_root, parallel=True
        )

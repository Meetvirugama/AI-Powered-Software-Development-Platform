"""Structured Test Report Parsers for JUnit XML and Coverage Reports (F23).

Owner: Om Vaghela — Issue #204 Deliverable
Reference:
- Issue #204 (F23 Restricted Test Runner)
- Docs/week3.md §6 (F35 Test Runner and Bounded Repair Loop)
- Docs/architecture/08-testing-strategy.md

Key Capabilities:
1. JUnit XML Parsing:
   - Parses standard JUnit XML test reports produced by pytest (--junitxml), Jest (jest-junit), or Vitest.
   - Extracts structured test suites, test cases, execution times, status (passed, failed, error, skipped).
   - Extracts exact failure assertion messages, failure types, and stack tracebacks.
   - Eliminates fragile regex stdout scraping to provide high-precision failure diagnosis.
2. Coverage Report Parsing:
   - Parses coverage data from Python (pytest-cov / coverage.py JSON format) and JavaScript/TypeScript (Jest / Istanbul / c8 coverage-summary.json).
   - Extracts line coverage, branch coverage, statement coverage, function coverage, and total percentage.
   - Extracts per-file missing line numbers and executed line numbers.
   - Provides dependency data for framework-aware test generation (F13).
3. Resilient Error Handling:
   - Gracefully handles truncated, malformed, or missing XML/JSON reports without throwing exceptions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from app.schemas.workspace import (
    CoverageMetric,
    FileCoverageDetail,
    TestCaseResult,
    TestCoverageSummary,
    TestSuiteResult,
)

logger = logging.getLogger(__name__)


class JUnitReportParser:
    """Parser for JUnit XML test execution reports."""

    @classmethod
    def parse_file(cls, xml_path: Path | str) -> TestSuiteResult:
        """Parse JUnit XML from a file path."""
        path = Path(xml_path)
        if not path.is_file():
            logger.debug("junit_xml_not_found", extra={"path": str(path)})
            return TestSuiteResult(name="empty", raw_xml_path=str(path))
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            result = cls.parse_xml(content)
            result.raw_xml_path = str(path)
            return result
        except Exception as exc:
            logger.warning("junit_xml_file_read_error", extra={"path": str(path), "error": str(exc)})
            return TestSuiteResult(name="unreadable", raw_xml_path=str(path))

    @classmethod
    def parse_xml(cls, xml_content: str) -> TestSuiteResult:
        """Parse raw JUnit XML string into structured TestSuiteResult."""
        cleaned = xml_content.strip() if xml_content else ""
        if not cleaned:
            return TestSuiteResult(name="empty")

        try:
            root = ET.fromstring(cleaned)
        except ET.ParseError as exc:
            logger.warning("junit_xml_parse_error", extra={"error": str(exc)})
            return TestSuiteResult(name="malformed")

        # Handle root element: may be <testsuites> or <testsuite>
        suites: list[ET.Element] = []
        if root.tag == "testsuites":
            suites = root.findall("testsuite")
            if not suites:
                # Root itself might have cases if empty testsuites container
                suites = [root]
        elif root.tag == "testsuite":
            suites = [root]
        else:
            # Look for any testsuite inside root
            suites = root.findall(".//testsuite")
            if not suites:
                suites = [root]

        all_test_cases: list[TestCaseResult] = []
        total_tests = 0
        total_passed = 0
        total_failed = 0
        total_skipped = 0
        total_errors = 0
        total_time_s = 0.0
        suite_name = root.attrib.get("name")
        if not suite_name and suites:
            for s in suites:
                s_name = s.attrib.get("name")
                if s_name:
                    suite_name = s_name
                    break
        suite_name = suite_name or "test_suite"

        for suite in suites:
            # Parse test cases in this suite
            for tc in suite.findall(".//testcase"):
                name = tc.attrib.get("name", "unknown_test")
                classname = tc.attrib.get("classname")
                file_path = tc.attrib.get("file")
                time_val = 0.0
                try:
                    time_val = float(tc.attrib.get("time", "0.0") or 0.0)
                except ValueError:
                    time_val = 0.0

                failure_elem = tc.find("failure")
                error_elem = tc.find("error")
                skipped_elem = tc.find("skipped")

                status = "passed"
                failure_msg = None
                failure_type = None
                traceback_txt = None

                if failure_elem is not None:
                    status = "failed"
                    failure_msg = failure_elem.attrib.get("message")
                    failure_type = failure_elem.attrib.get("type")
                    traceback_txt = (failure_elem.text or "").strip() or failure_msg
                elif error_elem is not None:
                    status = "error"
                    failure_msg = error_elem.attrib.get("message")
                    failure_type = error_elem.attrib.get("type")
                    traceback_txt = (error_elem.text or "").strip() or failure_msg
                elif skipped_elem is not None:
                    status = "skipped"
                    failure_msg = skipped_elem.attrib.get("message")
                    traceback_txt = (skipped_elem.text or "").strip()

                case_result = TestCaseResult(
                    name=name,
                    classname=classname,
                    file=file_path,
                    time_s=time_val,
                    status=status,
                    failure_message=failure_msg,
                    failure_type=failure_type,
                    traceback=traceback_txt,
                )
                all_test_cases.append(case_result)

            # Accumulate time and counts from suite attributes if present
            try:
                total_time_s += float(suite.attrib.get("time", "0.0") or 0.0)
            except ValueError:
                pass

        # Compute summary counts from actual parsed test cases for maximum accuracy
        total_tests = len(all_test_cases)
        for tc in all_test_cases:
            if tc.status == "passed":
                total_passed += 1
            elif tc.status == "failed":
                total_failed += 1
            elif tc.status == "error":
                total_errors += 1
            elif tc.status == "skipped":
                total_skipped += 1

        # If time_s wasn't on the suite element, sum the individual test times
        if total_time_s == 0.0 and all_test_cases:
            total_time_s = sum(tc.time_s for tc in all_test_cases)

        return TestSuiteResult(
            name=suite_name,
            tests_total=total_tests,
            passed=total_passed,
            failed=total_failed,
            skipped=total_skipped,
            errors=total_errors,
            time_s=round(total_time_s, 4),
            test_cases=all_test_cases,
        )


class CoverageReportParser:
    """Parser for test coverage reports (pytest-cov JSON and Jest/Vitest summary JSON)."""

    @classmethod
    def parse_file(cls, report_path: Path | str, framework: str = "pytest") -> TestCoverageSummary:
        """Parse coverage summary from a JSON report file."""
        path = Path(report_path)
        if not path.is_file():
            logger.debug("coverage_report_not_found", extra={"path": str(path)})
            return TestCoverageSummary(raw_report_path=str(path))
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            result = cls.parse_json(content, framework=framework)
            result.raw_report_path = str(path)
            return result
        except Exception as exc:
            logger.warning("coverage_report_read_error", extra={"path": str(path), "error": str(exc)})
            return TestCoverageSummary(raw_report_path=str(path))

    @classmethod
    def parse_json(cls, json_content: str, framework: str = "pytest") -> TestCoverageSummary:
        """Parse raw coverage JSON into structured TestCoverageSummary."""
        cleaned = json_content.strip() if json_content else ""
        if not cleaned:
            return TestCoverageSummary()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("coverage_json_decode_error", extra={"error": str(exc)})
            return TestCoverageSummary()

        if not isinstance(data, dict):
            return TestCoverageSummary()

        # Check format: Python coverage.py (totals + files) vs Jest/Istanbul (total + files)
        if "totals" in data:
            return cls._parse_python_coverage(data)
        elif "total" in data:
            return cls._parse_jest_coverage(data)
        else:
            # Fallback heuristic
            if any(k.endswith(".py") for k in data.get("files", {}).keys()):
                return cls._parse_python_coverage(data)
            return cls._parse_jest_coverage(data)

    @classmethod
    def _parse_python_coverage(cls, data: dict[str, Any]) -> TestCoverageSummary:
        """Parse coverage.py / pytest-cov JSON output."""
        totals = data.get("totals", {})

        covered_lines = int(totals.get("covered_lines", 0))
        num_statements = int(totals.get("num_statements", 0))
        missing_lines = int(totals.get("missing_lines", 0))
        excluded_lines = int(totals.get("excluded_lines", 0))

        num_branches = int(totals.get("num_branches", 0))
        covered_branches = int(totals.get("covered_branches", 0))
        missing_branches = int(totals.get("missing_branches", 0))

        raw_percent = totals.get("percent_covered", 0.0)
        total_pct = round(float(raw_percent), 2) if raw_percent is not None else 0.0

        line_metric = CoverageMetric(
            total=num_statements,
            covered=covered_lines,
            skipped=excluded_lines,
            percent=round((covered_lines / num_statements * 100.0) if num_statements > 0 else 0.0, 2),
        )

        branch_metric = CoverageMetric(
            total=num_branches,
            covered=covered_branches,
            skipped=0,
            percent=round((covered_branches / num_branches * 100.0) if num_branches > 0 else 0.0, 2),
        )

        statement_metric = CoverageMetric(
            total=num_statements,
            covered=covered_lines,
            skipped=excluded_lines,
            percent=line_metric.percent,
        )

        # Parse per-file coverage
        files_map: dict[str, FileCoverageDetail] = {}
        for fpath, fobj in data.get("files", {}).items():
            if not isinstance(fobj, dict):
                continue
            summary = fobj.get("summary", {})
            f_covered_lines = int(summary.get("covered_lines", 0))
            f_statements = int(summary.get("num_statements", 0))
            f_missing_cnt = int(summary.get("missing_lines", 0))
            f_excluded = int(summary.get("excluded_lines", 0))

            f_branches = int(summary.get("num_branches", 0))
            f_cov_branches = int(summary.get("covered_branches", 0))

            f_missing_lines = [int(x) for x in fobj.get("missing_lines", []) if isinstance(x, (int, float))]
            f_executed_lines = [int(x) for x in fobj.get("executed_lines", []) if isinstance(x, (int, float))]

            f_line_pct = round((f_covered_lines / f_statements * 100.0) if f_statements > 0 else 0.0, 2)
            f_branch_pct = round((f_cov_branches / f_branches * 100.0) if f_branches > 0 else 0.0, 2)

            files_map[fpath] = FileCoverageDetail(
                file_path=fpath,
                lines=CoverageMetric(total=f_statements, covered=f_covered_lines, skipped=f_excluded, percent=f_line_pct),
                branches=CoverageMetric(total=f_branches, covered=f_cov_branches, percent=f_branch_pct),
                statements=CoverageMetric(total=f_statements, covered=f_covered_lines, skipped=f_excluded, percent=f_line_pct),
                missing_lines=f_missing_lines,
                executed_lines=f_executed_lines,
            )

        return TestCoverageSummary(
            lines=line_metric,
            branches=branch_metric,
            statements=statement_metric,
            functions=CoverageMetric(),
            files=files_map,
            total_percent=total_pct if total_pct > 0.0 else line_metric.percent,
        )

    @classmethod
    def _parse_jest_coverage(cls, data: dict[str, Any]) -> TestCoverageSummary:
        """Parse Jest / Istanbul coverage-summary.json format."""
        total_section = data.get("total", {})

        def _metric_from_dict(d: dict[str, Any]) -> CoverageMetric:
            if not isinstance(d, dict):
                return CoverageMetric()
            tot = int(d.get("total", 0))
            cov = int(d.get("covered", 0))
            skip = int(d.get("skipped", 0))
            pct = round(float(d.get("pct", 0.0)), 2)
            return CoverageMetric(total=tot, covered=cov, skipped=skip, percent=pct)

        lines_metric = _metric_from_dict(total_section.get("lines", {}))
        statements_metric = _metric_from_dict(total_section.get("statements", {}))
        functions_metric = _metric_from_dict(total_section.get("functions", {}))
        branches_metric = _metric_from_dict(total_section.get("branches", {}))

        # Overall percent is usually statements or lines pct
        total_percent = statements_metric.percent or lines_metric.percent

        files_map: dict[str, FileCoverageDetail] = {}
        for fpath, fobj in data.items():
            if fpath == "total" or not isinstance(fobj, dict):
                continue
            f_lines = _metric_from_dict(fobj.get("lines", {}))
            f_stmts = _metric_from_dict(fobj.get("statements", {}))
            f_funcs = _metric_from_dict(fobj.get("functions", {}))
            f_branches = _metric_from_dict(fobj.get("branches", {}))

            files_map[fpath] = FileCoverageDetail(
                file_path=fpath,
                lines=f_lines,
                branches=f_branches,
                statements=f_stmts,
                functions=f_funcs,
            )

        return TestCoverageSummary(
            lines=lines_metric,
            branches=branches_metric,
            statements=statements_metric,
            functions=functions_metric,
            files=files_map,
            total_percent=total_percent,
        )

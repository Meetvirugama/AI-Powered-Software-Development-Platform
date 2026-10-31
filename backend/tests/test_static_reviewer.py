
import subprocess
import unittest
from unittest.mock import patch

from review.static_reviewer import StaticReviewer


class TestStaticReviewer(unittest.TestCase):
    def setUp(self):
        self.reviewer = StaticReviewer()

    def test_normalizes_common_finding_fields(self):
        result = self.reviewer.normalize_finding(
            {
                "code": "B101",
                "message": "Use of assert detected",
                "filename": "app.py",
                "line": 12,
                "severity": "high",
            },
            scanner="bandit",
        )

        self.assertEqual(result.rule_id, "B101")
        self.assertEqual(result.file_path, "app.py")
        self.assertEqual(result.line_number, 12)
        self.assertEqual(result.severity, "high")
        self.assertEqual(result.scanner, "bandit")

    def test_unknown_severity_becomes_info(self):
        result = self.reviewer.normalize_finding(
            {"severity": "unexpected"},
            scanner="test",
        )
        self.assertEqual(result.severity, "info")

    def test_secret_fields_are_not_copied_to_metadata(self):
        result = self.reviewer.normalize_finding(
            {
                "rule_id": "SECRET001",
                "message": "Possible hardcoded secret",
                "secret_value": "do-not-leak-this",
                "api_key": "do-not-leak-this-either",
                "extra": "safe metadata",
            },
            scanner="test",
        )

        self.assertNotIn("secret_value", result.metadata or {})
        self.assertNotIn("api_key", result.metadata or {})
        self.assertEqual(result.metadata, {"extra": "safe metadata"})

    def test_review_returns_dictionary_findings(self):
        results = self.reviewer.review(
            [{"rule_id": "R1", "message": "Example", "file_path": "a.py"}],
            scanner="ruff",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["scanner"], "ruff")
        self.assertEqual(results[0]["rule_id"], "R1")

    def test_unsupported_scanner_is_rejected(self):
        with self.assertRaises(ValueError):
            self.reviewer.run_scanner("unknown", ".")

    @patch("review.static_reviewer.subprocess.run")
    def test_missing_scanner_reports_clear_error(self, mock_run):
        mock_run.side_effect = FileNotFoundError("scanner unavailable")
        with self.assertRaisesRegex(RuntimeError, "could not complete"):
            self.reviewer.run_scanner("ruff", ".")

    @patch("review.static_reviewer.subprocess.run")
    def test_scanner_timeout_reports_clear_error(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("ruff", 60)
        with self.assertRaisesRegex(RuntimeError, "could not complete"):
            self.reviewer.run_scanner("ruff", ".")

    @patch("review.static_reviewer.subprocess.run")
    def test_ruff_json_output_is_normalized(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ruff"],
            returncode=1,
            stdout=(
                '[{"code":"F401","message":"Unused import",'
                '"filename":"app.py","location":{"row":4}}]'
            ),
            stderr="",
        )

        results = self.reviewer.run_scanner("ruff", "app.py")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["rule_id"], "F401")
        self.assertEqual(results[0]["file_path"], "app.py")
        self.assertEqual(results[0]["line_number"], 4)
        self.assertEqual(results[0]["scanner"], "ruff")

    @patch("review.static_reviewer.subprocess.run")
    def test_invalid_scanner_json_reports_error(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ruff"],
            returncode=0,
            stdout="not valid JSON",
            stderr="",
        )

        with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
            self.reviewer.run_scanner("ruff", "app.py")

    @patch.object(StaticReviewer, "run_scanner")
    def test_review_modified_files_combines_static_and_ai_findings(
        self, mock_run_scanner
    ):
        mock_run_scanner.return_value = [
            {
                "rule_id": "F401",
                "severity": "low",
                "message": "Unused import",
                "file_path": "app.py",
                "line_number": 1,
                "scanner": "ruff",
                "metadata": None,
            }
        ]
        ai_findings = [
            {"rule_id": "AI001", "message": "Possible bug", "source_type": "AI"}
        ]

        result = self.reviewer.review_modified_files(
            ["app.py"], ai_findings, scanners=("ruff",)
        )

        self.assertEqual(result["static_findings_count"], 1)
        self.assertEqual(result["ai_findings_count"], 1)
        self.assertEqual(result["total_findings"], 2)
        self.assertEqual(len(result["findings"]), 2)
        mock_run_scanner.assert_called_once_with("ruff", "app.py")

    @patch.object(StaticReviewer, "run_scanner")
    def test_review_modified_files_handles_multiple_files(
        self, mock_run_scanner
    ):
        mock_run_scanner.side_effect = [
            [{"rule_id": "R1", "file_path": "a.py"}],
            [{"rule_id": "R2", "file_path": "b.py"}],
        ]

        result = self.reviewer.review_modified_files(
            ["a.py", "b.py"], scanners=("ruff",)
        )

        self.assertEqual(result["static_findings_count"], 2)
        self.assertEqual(result["ai_findings_count"], 0)
        self.assertEqual(result["total_findings"], 2)
        self.assertEqual(mock_run_scanner.call_count, 2)

if __name__ == "__main__":
    unittest.main()

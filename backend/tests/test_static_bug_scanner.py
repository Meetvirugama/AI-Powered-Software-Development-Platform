
import unittest
from unittest.mock import MagicMock

from scanner.static_bug_scanner import StaticBugScanner


class TestStaticBugScanner(unittest.TestCase):
    def setUp(self):
        self.scanner = StaticBugScanner()

    def test_scan_code_returns_normalized_result(self):
        result = self.scanner.scan_code(
            "def example():\n    return 1\n",
            "example.py",
        )

        self.assertIn("success", result)
        self.assertIn("findings", result)
        self.assertIn("parse_status", result)
        self.assertIsInstance(result["findings"], list)

    def test_scan_code_reports_syntax_error(self):
        result = self.scanner.scan_code(
            "def broken(:\n    pass\n",
            "broken.py",
        )

        self.assertTrue(result["has_syntax_errors"])
        self.assertEqual(result["parse_status"], "SYNTAX_WARNING")
        self.assertTrue(
            any(
                finding["rule_id"] == "AST-SYNTAX-ERROR"
                for finding in result["findings"]
            )
        )

    def test_scan_file_rejects_path_outside_repo(self):
        result = self.scanner.scan_file(
            "../outside.py",
            repo_root=".",
        )

        self.assertFalse(result["success"])
        self.assertIn("Path traversal", result["error_message"])

    def test_scan_code_exports_ast_findings(self):
        fake_analyzer = MagicMock()
        fake_analyzer.analyze_code.return_value = MagicMock(
            success=True,
            file_path="example.py",
            parse_status="OK",
            has_syntax_errors=False,
            error_message=None,
            findings=["fake-finding"],
            rules_evaluated=3,
        )
        fake_analyzer.to_static_findings.return_value = [
            {
                "rule_id": "AST001",
                "severity": "medium",
                "message": "Example finding",
                "file_path": "example.py",
                "line_number": 1,
            }
        ]

        scanner = StaticBugScanner(analyzer=fake_analyzer)
        result = scanner.scan_code("example code", "example.py")

        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["rule_id"], "AST001")
        fake_analyzer.to_static_findings.assert_called_once_with(
            ["fake-finding"]
        )


if __name__ == "__main__":
    unittest.main()

"""Comprehensive Test Suite for Security Analysis and Bug Detection Expansion.

Part of Issue #191: Broaden Security Analysis and Bug Detection Findings.
Tests:
- Semgrep CE integration & sandboxing
- Multi-language security rules (JS, TS, Go, Java)
- OSV-Scanner software composition analysis (SCA)
- Gitleaks secret detection & non-negotiable redaction guarantees
- Finding normalization into AnalysisFinding & BugFinding schemas
- Candidate discovery and priority scoring
- Repository-specific taint specifications
- Benchmark reproducibility and per-CWE / per-language metrics
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.analysis_finding import AnalysisFinding
from app.schemas.analysis import AnalysisSourceReference, BugFinding
from app.services.bug_candidate_discovery import BugCandidate, BugCandidateDiscoveryService
from app.services.bug_priority_service import BugPriorityService
from app.services.bug_validation_service import BugValidationService
from scanner.gitleaks_runner import GitleaksFinding, GitleaksRunner
from scanner.multilang_security_scanner import MultiLangSecurityScanner
from scanner.osv_runner import OSVScannerRunner
from scanner.semgrep_runner import SemgrepFinding, SemgrepRunner
from scanner.taint_specs import RepositoryTaintSpec, TaintSpecEntry
from scripts.benchmark_quality_suite import run_expanded_security_benchmark


# ===========================================================================
# 1. Semgrep CE Integration Tests
# ===========================================================================

def test_semgrep_missing_executable_handles_gracefully(tmp_path: Path):
    """When semgrep executable is absent, scanner degrades gracefully without error."""
    runner = SemgrepRunner(executable_path=str(tmp_path / "nonexistent_semgrep"))
    assert runner.is_available() is False

    res = runner.scan_path(target_path=tmp_path / "test.py", workspace_root=tmp_path)
    assert res.success is True
    assert res.is_available is False
    assert len(res.findings) == 0
    assert any("not installed" in d for d in res.diagnostics)


def test_semgrep_parse_valid_json_output(tmp_path: Path):
    """Semgrep valid JSON output is parsed and normalized into SemgrepFindings."""
    runner = SemgrepRunner(executable_path="semgrep")
    mock_json = json.dumps(
        {
            "results": [
                {
                    "check_id": "js-sqli-template-literal",
                    "path": str(tmp_path / "app.js"),
                    "start": {"line": 15, "col": 5},
                    "end": {"line": 15, "col": 45},
                    "extra": {
                        "message": "Potential SQL injection via template string",
                        "severity": "ERROR",
                        "metadata": {"cwe": ["CWE-89"], "owasp": ["A03:2021"], "category": "security"},
                        "lines": "db.query(`SELECT * FROM users WHERE id = ${id}`);",
                        "fix": "Use parameterized query",
                    },
                }
            ]
        }
    )

    res = runner.parse_json_output(mock_json, workspace_root=tmp_path)
    assert res.success is True
    assert len(res.findings) == 1

    f = res.findings[0]
    assert f.rule_id == "js-sqli-template-literal"
    assert f.severity == "HIGH"  # ERROR -> HIGH
    assert f.start_line == 15
    assert f.end_line == 15
    assert f.cwe == ["CWE-89"]
    assert "db.query" in f.evidence


def test_semgrep_parse_malformed_json_output():
    """Semgrep invalid non-JSON output returns failure without throwing an unhandled exception."""
    runner = SemgrepRunner(executable_path="semgrep")
    res = runner.parse_json_output("Fatal: syntax error on line 4 [Not JSON]")
    assert res.success is False
    assert "Invalid JSON" in (res.error_message or "")
    assert len(res.findings) == 0


def test_semgrep_sandbox_boundary_rejection(tmp_path: Path):
    """Semgrep rejects scanning targets that escape the workspace root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1")

    runner = SemgrepRunner(executable_path="semgrep")
    with patch.object(runner, "is_available", return_value=True):
        res = runner.scan_path(target_path=outside, workspace_root=workspace)
        assert res.success is False
        assert "escapes workspace root" in (res.error_message or "")


def test_semgrep_rule_yaml_configuration_valid():
    """The default semgrep_rules.yaml rule file exists and contains valid license metadata."""
    from scanner.semgrep_runner import DEFAULT_RULES_PATH
    assert DEFAULT_RULES_PATH.is_file()
    text = DEFAULT_RULES_PATH.read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "rules:" in text
    assert "py-sqli-format-string" in text
    assert "js-exec-command-injection" in text
    assert "go-cmd-injection-exec" in text
    assert "java-cmd-injection-runtime-exec" in text


# ===========================================================================
# 2. Multi-Language Security Scanner Tests
# ===========================================================================

def test_multilang_javascript_vulnerabilities():
    """JavaScript rules detect Command Injection, SQLi, XSS, Weak Crypto, and Eval."""
    scanner = MultiLangSecurityScanner()

    # Command Injection
    cmdi_code = "const { exec } = require('child_process');\nexec(`rm -rf ${userInput}`);"
    findings = scanner.scan_code(cmdi_code, "server.js", "javascript")
    assert any(f.cwe == "CWE-78" for f in findings)

    # SQL Injection
    sqli_code = "function get(id) { db.query(`SELECT * FROM users WHERE id = ${id}`); }"
    findings = scanner.scan_code(sqli_code, "db.js", "javascript")
    assert any(f.cwe == "CWE-89" for f in findings)

    # XSS
    xss_code = "document.getElementById('root').innerHTML = userInput;"
    findings = scanner.scan_code(xss_code, "app.js", "javascript")
    assert any(f.cwe == "CWE-79" for f in findings)

    # Weak Crypto
    crypto_code = "const hash = crypto.createHash('md5');"
    findings = scanner.scan_code(crypto_code, "crypto.js", "javascript")
    assert any(f.cwe == "CWE-327" for f in findings)

    # Eval
    eval_code = "eval(untrustedInput);"
    findings = scanner.scan_code(eval_code, "eval.js", "javascript")
    assert any(f.cwe == "CWE-95" for f in findings)


def test_multilang_typescript_vulnerabilities():
    """TypeScript rules detect SQL injection and SSRF."""
    scanner = MultiLangSecurityScanner()

    ts_code = "export async function get(id: string) {\n  return pool.query('SELECT * FROM data WHERE id = ' + id);\n}"
    findings = scanner.scan_code(ts_code, "repo.ts", "typescript")
    assert any(f.cwe == "CWE-89" for f in findings)

    ssrf_code = "export async function fetchUrl(targetUrl: string) {\n  return await axios.get(targetUrl);\n}"
    findings = scanner.scan_code(ssrf_code, "fetcher.ts", "typescript")
    assert any(f.cwe == "CWE-918" for f in findings)


def test_multilang_go_vulnerabilities():
    """Go rules detect Command Injection, SQLi, and Insecure TLS."""
    scanner = MultiLangSecurityScanner()

    go_cmdi = 'package main\nimport "os/exec"\nimport "fmt"\nfunc r(c string) { exec.Command("sh", "-c", fmt.Sprintf("ls %s", c)).Run() }'
    findings = scanner.scan_code(go_cmdi, "main.go", "go")
    assert any(f.cwe == "CWE-78" for f in findings)

    go_sqli = 'package main\nimport "fmt"\nfunc q(db DB, uid string) { db.Query(fmt.Sprintf("SELECT * FROM u WHERE id = %s", uid)) }'
    findings = scanner.scan_code(go_sqli, "db.go", "go")
    assert any(f.cwe == "CWE-89" for f in findings)

    go_tls = 'package main\nimport "crypto/tls"\nfunc c() { cfg := &tls.Config{InsecureSkipVerify: true} }'
    findings = scanner.scan_code(go_tls, "net.go", "go")
    assert any(f.cwe == "CWE-295" for f in findings)


def test_multilang_java_vulnerabilities():
    """Java rules detect Command Injection, SQLi, Insecure Deserialization, and XXE."""
    scanner = MultiLangSecurityScanner()

    java_cmdi = 'public class R { public void e(String s) throws Exception { Runtime.getRuntime().exec("sh " + s); } }'
    findings = scanner.scan_code(java_cmdi, "Runner.java", "java")
    assert any(f.cwe == "CWE-78" for f in findings)

    java_sqli = 'public class D { public void q(Statement stmt, String u) throws Exception { stmt.executeQuery("SELECT * FROM u WHERE id = " + u); } }'
    findings = scanner.scan_code(java_sqli, "Dao.java", "java")
    assert any(f.cwe == "CWE-89" for f in findings)

    java_deser = 'public class S { public Object r(InputStream is) throws Exception { return new ObjectInputStream(is).readObject(); } }'
    findings = scanner.scan_code(java_deser, "Ser.java", "java")
    assert any(f.cwe == "CWE-502" for f in findings)

    java_xxe = 'public class X { public void p() throws Exception { DocumentBuilderFactory.newInstance(); } }'
    findings = scanner.scan_code(java_xxe, "Xml.java", "java")
    assert any(f.cwe == "CWE-611" for f in findings)


def test_multilang_vendor_and_node_modules_excluded():
    """Files within vendor or node_modules directories are ignored."""
    scanner = MultiLangSecurityScanner()
    code = "eval(untrusted);"
    assert len(scanner.scan_code(code, "node_modules/pkg/index.js", "javascript")) == 0
    assert len(scanner.scan_code(code, "vendor/bundle/run.js", "javascript")) == 0
    assert len(scanner.scan_code(code, "dist/bundle.js", "javascript")) == 0


# ===========================================================================
# 3. OSV-Scanner Software Composition Analysis Tests
# ===========================================================================

def test_osv_scanner_detects_vulnerable_package_lock():
    """OSV-Scanner detects vulnerable npm packages in package-lock.json."""
    runner = OSVScannerRunner()
    lockfile_content = json.dumps(
        {
            "name": "sample-app",
            "version": "1.0.0",
            "dependencies": {
                "lodash": {"version": "4.17.15"},
                "express": {"version": "4.18.2"},
            },
        }
    )

    findings = runner.scan_lockfile_content("package-lock.json", lockfile_content)
    assert len(findings) >= 1
    f = findings[0]
    assert f.package_name == "lodash"
    assert f.installed_version == "4.17.15"
    assert f.vulnerability_id == "GHSA-35jh-r3h4-6jhm"
    assert f.cve == "CVE-2021-23337"
    assert f.fixed_version == "4.17.21"


def test_osv_scanner_detects_vulnerable_requirements_txt():
    """OSV-Scanner detects vulnerable PyPI packages in requirements.txt."""
    runner = OSVScannerRunner()
    req_content = "requests==2.20.0\nurllib3==2.0.6\nfastapi==0.110.0\n"

    findings = runner.scan_lockfile_content("requirements.txt", req_content)
    assert len(findings) >= 2
    packages = {f.package_name: f for f in findings}
    assert "requests" in packages
    assert packages["requests"].cve == "CVE-2018-18074"
    assert "urllib3" in packages


def test_osv_scanner_detects_vulnerable_pom_xml():
    """OSV-Scanner detects vulnerable Log4j in pom.xml."""
    runner = OSVScannerRunner()
    pom_content = """<project>
      <dependencies>
        <dependency>
          <groupId>org.apache.logging.log4j</groupId>
          <artifactId>log4j-core</artifactId>
          <version>2.14.1</version>
        </dependency>
      </dependencies>
    </project>"""

    findings = runner.scan_lockfile_content("pom.xml", pom_content)
    assert len(findings) == 1
    assert findings[0].package_name == "org.apache.logging.log4j:log4j-core"
    assert findings[0].cve == "CVE-2021-44228"
    assert findings[0].severity == "CRITICAL"


def test_osv_scanner_clean_lockfile_produces_no_findings():
    """A lockfile with patched / non-vulnerable versions produces 0 findings."""
    runner = OSVScannerRunner()
    clean_lock = json.dumps(
        {
            "dependencies": {
                "lodash": {"version": "4.17.21"},
                "axios": {"version": "1.6.8"},
            }
        }
    )
    findings = runner.scan_lockfile_content("package-lock.json", clean_lock)
    assert len(findings) == 0


def test_osv_scanner_malformed_lockfile_handles_gracefully():
    """Malformed JSON/XML lockfiles return empty findings without crashing."""
    runner = OSVScannerRunner()
    assert len(runner.scan_lockfile_content("package-lock.json", "{ malformed json ]")) == 0
    assert len(runner.scan_lockfile_content("pom.xml", "<unclosed xml tag")) == 0


# ===========================================================================
# 4. Gitleaks Secret Detection & Strict Redaction Tests
# ===========================================================================

def test_gitleaks_detects_secrets():
    """Gitleaks detects synthetic OpenAI, GitHub, and AWS credentials."""
    runner = GitleaksRunner()

    text = """
    OPENAI_API_KEY = "sk-proj-abcdef12345678901234567890"
    GH_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    AWS_ID = "AKIA1111222233334444"
    """
    findings = runner.scan_text(text, file_path="settings.py")
    assert len(findings) >= 3
    rule_ids = {f.rule_id for f in findings}
    assert "OPENAI-API-KEY" in rule_ids
    assert "GITHUB-PAT" in rule_ids
    assert "AWS-ACCESS-KEY" in rule_ids


def test_gitleaks_zero_secret_leakage_guarantee():
    """CRITICAL SECURITY GUARANTEE: Raw secret values are NEVER present in finding evidence."""
    runner = GitleaksRunner()
    raw_secret = "ghp_SECRETSECRETSECRETSECRETSECRET1234"
    code = f'GITHUB_PAT = "{raw_secret}"'

    findings = runner.scan_text(code, file_path="config.py")
    assert len(findings) == 1
    f = findings[0]

    # Verify that the raw secret does NOT appear anywhere in the finding object
    finding_dict = f.to_dict()
    finding_json = json.dumps(finding_dict)
    assert raw_secret not in finding_json
    assert raw_secret not in f.evidence
    assert "***REDACTED***" in f.evidence or "[REDACTED]" in f.evidence


def test_gitleaks_ignores_placeholder_and_env_vars():
    """Placeholder secrets and environment variable loaders produce 0 false positives."""
    runner = GitleaksRunner()
    text = """
    key = os.environ.get("OPENAI_API_KEY")
    placeholder = "sk-proj-[REDACTED]"
    example = "<YOUR_GITHUB_TOKEN>"
    test_val = "AKIA...placeholder..."
    """
    findings = runner.scan_text(text, file_path="example.py")
    assert len(findings) == 0


# ===========================================================================
# 5. Finding Normalization & Architecture Integration Tests
# ===========================================================================

def test_candidate_discovery_integrates_all_scanners():
    """BugCandidateDiscoveryService discovers candidates across AST, multi-language, SCA, and secrets."""
    discovery_svc = BugCandidateDiscoveryService()

    # JS code with command injection and secret
    code = """
    const { exec } = require('child_process');
    function test(cmd) {
        exec('sh -c ' + cmd);
        const token = 'ghp_abcdef1234567890abcdef1234567890';
    }
    """
    candidates = discovery_svc.discover_candidates(
        file_path="service.js",
        code_content=code,
        language="javascript",
    )

    assert len(candidates) >= 2
    categories = {c.category for c in candidates}
    assert "security" in categories
    assert "secrets" in categories

    # Verify candidate dictionary conversion
    for c in candidates:
        d = c.to_dict()
        assert d["file_path"] == "service.js"
        assert d["start_line"] > 0
        assert d["source_type"] == "STATIC"


def test_finding_normalization_to_analysis_finding():
    """All scanner candidates normalize cleanly into the AnalysisFinding SQLAlchemy model."""
    from uuid import uuid4

    run_id = uuid4()
    repo_id = uuid4()

    finding = AnalysisFinding(
        analysis_run_id=run_id,
        repository_id=repo_id,
        category="supply_chain",
        severity="HIGH",
        title="Vulnerable dependency: lodash@4.17.15 (GHSA-35jh-r3h4-6jhm)",
        description="Prototype pollution vulnerability",
        file_path="package-lock.json",
        start_line=1,
        end_line=1,
        evidence="Package lodash resolved to 4.17.15",
        suggested_fix="Upgrade to 4.17.21",
        confidence="high",
        source_type="STATIC",
        rule_id="SCA-OSV-GHSA-35jh-r3h4-6jhm",
    )

    d = finding.to_dict()
    assert d["category"] == "supply_chain"
    assert d["severity"] == "HIGH"
    assert d["rule_id"] == "SCA-OSV-GHSA-35jh-r3h4-6jhm"
    assert d["source_reference"]["file_path"] == "package-lock.json"


def test_bug_priority_service_handles_expanded_categories():
    """BugPriorityService accurately calculates priority scores for security and supply chain findings."""
    priority_svc = BugPriorityService()

    # Critical security defect
    p_sec = priority_svc.calculate_priority(
        severity="CRITICAL",
        confidence="high",
        is_security=True,
        has_callers=True,
    )
    assert p_sec.priority_score >= 80

    # High supply chain defect
    p_sca = priority_svc.calculate_priority(
        severity="HIGH",
        confidence="STRONG",
        is_security=False,
    )
    assert p_sca.priority_score >= 60


# ===========================================================================
# 6. Repository-Specific Taint Specifications (Phase 7) Tests
# ===========================================================================

def test_repository_taint_specification_validation():
    """RepositoryTaintSpec validates identifiers and rejects unsafe command injection."""
    valid_spec = RepositoryTaintSpec(
        sources=[TaintSpecEntry(name="req.getCustomParam", category="source")],
        sinks=[TaintSpecEntry(name="execCustomSink", category="cmd_sink")],
        sanitizers=[TaintSpecEntry(name="sanitizeCustom", category="sanitizer")],
    )
    assert valid_spec.validate_specification_safety() is True

    # Rejects control characters
    with pytest.raises(ValueError):
        TaintSpecEntry(name="untrusted; rm -rf /", category="source")

    with pytest.raises(ValueError):
        TaintSpecEntry(name="newline\ninjection", category="source")


# ===========================================================================
# 7. Expanded Benchmark Suite Tests
# ===========================================================================

def test_expanded_security_benchmark_suite():
    """Expanded benchmark meets SLA thresholds: precision >= 85%, recall >= 85%, FPR <= 5%."""
    res = run_expanded_security_benchmark()

    assert res["target_precision_met"] is True
    assert res["target_recall_met"] is True
    assert res["target_fpr_met"] is True
    assert res["precision"] >= 0.85
    assert res["recall"] >= 0.85
    assert res["false_positive_rate"] <= 0.05
    assert res["false_positives"] == 0, "Clean control cases must produce 0 false positives"

    # Per-CWE metrics coverage
    cwes = res["per_cwe_metrics"]
    for cwe_id in ("CWE-78", "CWE-89", "CWE-327", "CWE-798", "CWE-1395"):
        assert cwe_id in cwes
        assert cwes[cwe_id]["true_positives"] >= 1
        assert cwes[cwe_id]["precision"] >= 0.85

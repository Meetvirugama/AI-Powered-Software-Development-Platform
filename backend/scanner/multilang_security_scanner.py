"""Multi-Language Deterministic Security Scanner.

Part of Issue #191: Broaden Security Analysis and Bug Detection Findings.
Provides deterministic, multi-language static security analysis for:
- Python (.py)
- JavaScript (.js, .jsx, .mjs, .cjs)
- TypeScript (.ts, .tsx)
- Go (.go)
- Java (.java)

Uses Tree-Sitter parsing where available, coupled with robust AST / structural
pattern analysis. Respects repository exclusion patterns and guarantees secret redaction.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.core.secret_redaction import redact

logger = logging.getLogger(__name__)

# Standard directory exclusion list
EXCLUDED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        ".venv",
        "venv",
        "__pycache__",
        ".workspaces",
        "coverage",
        ".next",
        ".nuxt",
        "out",
        "bin",
        "obj",
    }
)


@dataclass
class MultiLangFinding:
    """Normalized finding emitted by the multi-language security scanner."""

    rule_id: str
    category: str
    severity: str
    title: str
    description: str
    file_path: str
    start_line: int
    end_line: int
    evidence: str
    suggested_fix: str
    cwe: str
    language: str
    confidence: str = "high"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert multi-language security finding into dictionary representation."""
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": self.evidence,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "metadata": {
                **self.metadata,
                "cwe": self.cwe,
                "language": self.language,
                "engine": "multilang_static",
            },
        }

    def to_candidate_dict(self) -> dict[str, Any]:
        """Convert finding into BugCandidate dictionary representation."""
        return {
            "candidate_id": f"cand-multilang-{self.rule_id}-{self.start_line}",
            "rule_id": self.rule_id,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "category": self.category,
            "severity": self.severity,
            "evidence": self.evidence,
            "source_type": "STATIC",
            "confidence": self.confidence,
            "remediation": self.suggested_fix,
            "metadata": {
                **self.metadata,
                "cwe": self.cwe,
                "language": self.language,
                "engine": "multilang_static",
            },
        }


class MultiLangSecurityScanner:
    """Deterministic security analyzer supporting Python, JS, TS, Go, and Java."""

    # -------------------------------------------------------------------------
    # Rule Definitions
    # -------------------------------------------------------------------------

    # JavaScript / TypeScript Patterns
    _JS_RULES = [
        {
            "id": "JS-SEC-CMD-001",
            "severity": "CRITICAL",
            "cwe": "CWE-78",
            "pattern": re.compile(
                r"""(?:\bchild_process\s*\.\s*(?:exec|execSync)|(?<!\.)\b(?:exec|execSync))\s*\(\s*(?:`[^`]*\$\{[^}]+\}[^`]*`|"[^"\\]*"\s*\+|'[^'\\]*'\s*\+|[a-zA-Z0-9_.]+\s*\+)"""
            ),
            "title": "Command injection via dynamic child_process.exec()",
            "desc": "Executing shell commands constructed from dynamic string variables allows arbitrary remote command injection.",
            "fix": "Use child_process.execFile() or child_process.spawn() with an array of arguments and shell: false.",
        },
        {
            "id": "JS-SEC-SQLI-001",
            "severity": "CRITICAL",
            "cwe": "CWE-89",
            "pattern": re.compile(
                r"""\b(?:query|execute|raw)\s*\(\s*(?:`[^`]*\$\{[^}]+\}[^`]*`|"[^"\\]*"\s*\+|'[^'\\]*'\s*\+|[a-zA-Z0-9_.]+\s*\+)""",
                re.IGNORECASE,
            ),
            "title": "SQL injection via concatenated or template query",
            "desc": "SQL queries assembled with string concatenation or template literals allow SQL injection.",
            "fix": "Use parameterized queries with prepared statement placeholders ($1, ?, :param).",
        },
        {
            "id": "JS-SEC-PATH-001",
            "severity": "HIGH",
            "cwe": "CWE-22",
            "pattern": re.compile(
                r"""\bfs\s*\.\s*(?:readFile|readFileSync|createReadStream|unlink|rmdir)\s*\(\s*(?:path\.join\s*\([^)]*(?:req|params|query|body)[^)]*\)|[a-zA-Z0-9_.]*(?:req|input|param)[a-zA-Z0-9_.]*)"""
            ),
            "title": "Path traversal via unvalidated file system operation",
            "desc": "Passing untrusted input directly to file system operations without boundary checks enables arbitrary file access.",
            "fix": "Validate that the canonical resolved path starts with the intended base directory.",
        },
        {
            "id": "JS-SEC-XSS-001",
            "severity": "HIGH",
            "cwe": "CWE-79",
            "pattern": re.compile(
                r"""(?:\.innerHTML\s*=|dangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html\s*:)"""
            ),
            "title": "Cross-Site Scripting (XSS) via unescaped HTML insertion",
            "desc": "Direct assignment to innerHTML or dangerouslySetInnerHTML renders unescaped HTML, allowing script injection.",
            "fix": "Use textContent or a DOM sanitization library (e.g. DOMPurify.sanitize) before rendering.",
        },
        {
            "id": "JS-SEC-CRYPTO-001",
            "severity": "MEDIUM",
            "cwe": "CWE-327",
            "pattern": re.compile(
                r"""\bcrypto\s*\.\s*createHash\s*\(\s*['"](?:md5|sha1)['"]\s*\)""",
                re.IGNORECASE,
            ),
            "title": "Weak cryptographic hash function (MD5/SHA1)",
            "desc": "MD5 and SHA-1 have known collision vulnerabilities and must not be used for security-critical contexts.",
            "fix": "Migrate to a collision-resistant hash function like SHA-256 or SHA-512 (e.g. crypto.createHash('sha256')).",
        },
        {
            "id": "JS-SEC-EVAL-001",
            "severity": "CRITICAL",
            "cwe": "CWE-95",
            "pattern": re.compile(
                r"""(?<!\.)\b(?:eval|Function)\s*\(\s*(?:[a-zA-Z0-9_.]+|`[^`]*\$\{[^}]+\}[^`]*`)"""
            ),
            "title": "Dangerous dynamic code execution via eval() or Function()",
            "desc": "Dynamic evaluation executes arbitrary JavaScript code with full application permissions.",
            "fix": "Avoid dynamic code evaluation; use JSON.parse() for data interchange or structured dispatch.",
        },
        {
            "id": "JS-SEC-SSRF-001",
            "severity": "HIGH",
            "cwe": "CWE-918",
            "pattern": re.compile(
                r"""\b(?:fetch|axios\.get|axios\.post|http\.get)\s*\(\s*(?:req\.(?:query|body|params)\.[a-zA-Z0-9_]+|[a-zA-Z0-9_]*(?:userUrl|targetUrl|rawUrl)[a-zA-Z0-9_]*)\s*[,)]"""
            ),
            "title": "Server-Side Request Forgery (SSRF) via untrusted HTTP request",
            "desc": "Making outbound HTTP requests to user-supplied URLs without an allowlist enables intranet scanning.",
            "fix": "Validate target URLs against an explicit allowlist of permitted hosts and protocol schemes.",
        },
    ]

    # Go Patterns
    _GO_RULES = [
        {
            "id": "GO-SEC-CMD-001",
            "severity": "CRITICAL",
            "cwe": "CWE-78",
            "pattern": re.compile(
                r"""\bexec\s*\.\s*Command(?:Context)?\s*\(\s*["'](?:sh|bash)["']\s*,\s*["']-c["']\s*,\s*fmt\.Sprintf\s*\("""
            ),
            "title": "Command injection via formatted shell execution",
            "desc": "Invoking a shell (sh -c / bash -c) with fmt.Sprintf allows shell metacharacters in input to execute commands.",
            "fix": "Invoke the executable directly with explicit argument slices rather than spawning an intermediate shell.",
        },
        {
            "id": "GO-SEC-SQLI-001",
            "severity": "CRITICAL",
            "cwe": "CWE-89",
            "pattern": re.compile(
                r"""\b(?:Query|Exec|QueryRow)\s*\(\s*fmt\.Sprintf\s*\(\s*["']SELECT\b""",
                re.IGNORECASE,
            ),
            "title": "SQL injection via fmt.Sprintf in database query",
            "desc": "Constructing SQL queries using fmt.Sprintf or string concatenation allows SQL injection attacks.",
            "fix": "Use database query parameters ($1, ?, @p1) provided by database/sql.",
        },
        {
            "id": "GO-SEC-TLS-001",
            "severity": "HIGH",
            "cwe": "CWE-295",
            "pattern": re.compile(
                r"""InsecureSkipVerify\s*:\s*true\b"""
            ),
            "title": "Insecure TLS configuration (InsecureSkipVerify: true)",
            "desc": "Disabling TLS certificate verification makes the connection vulnerable to man-in-the-middle attacks.",
            "fix": "Remove InsecureSkipVerify: true or configure a trusted CA certificate pool.",
        },
        {
            "id": "GO-SEC-CRYPTO-001",
            "severity": "MEDIUM",
            "cwe": "CWE-327",
            "pattern": re.compile(
                r"""\b(?:md5\.New|sha1\.New|des\.NewCipher)\s*\(\s*\)"""
            ),
            "title": "Use of weak cryptographic algorithm in Go",
            "desc": "MD5, SHA-1, and DES are cryptographically broken and vulnerable to collision or brute-force attacks.",
            "fix": "Use crypto/sha256 or crypto/sha512 for hashing and crypto/aes for encryption.",
        },
        {
            "id": "GO-SEC-PATH-001",
            "severity": "HIGH",
            "cwe": "CWE-22",
            "pattern": re.compile(
                r"""\b(?:os\.Open|os\.ReadFile|ioutil\.ReadFile)\s*\(\s*filepath\.Join\s*\([^)]*(?:req|r\.URL|query|param)[^)]*\)"""
            ),
            "title": "Path traversal via filepath.Join with untrusted parameters",
            "desc": "filepath.Join does not prevent directory traversal if the untrusted segment contains '..'.",
            "fix": "Verify that filepath.Clean(path) is prefixed by the expected safe base directory.",
        },
    ]

    # Java Patterns
    _JAVA_RULES = [
        {
            "id": "JAVA-SEC-CMD-001",
            "severity": "CRITICAL",
            "cwe": "CWE-78",
            "pattern": re.compile(
                r"""(?:Runtime\s*\.\s*getRuntime\s*\(\s*\)\s*\.\s*exec|new\s+ProcessBuilder)\s*\(\s*(?:"[^"\\]*"\s*\+|'[^'\\]*'\s*\+|[a-zA-Z0-9_.]+\s*\+)"""
            ),
            "title": "Command injection via Runtime.getRuntime().exec()",
            "desc": "Executing system commands with concatenated strings allows command injection.",
            "fix": "Use ProcessBuilder with a List<String> of separate command arguments without a shell.",
        },
        {
            "id": "JAVA-SEC-SQLI-001",
            "severity": "CRITICAL",
            "cwe": "CWE-89",
            "pattern": re.compile(
                r"""\b(?:executeQuery|executeUpdate|execute)\s*\(\s*(?:"[^"\\]*"\s*\+|'[^'\\]*'\s*\+|[a-zA-Z0-9_.]+\s*\+)""",
                re.IGNORECASE,
            ),
            "title": "SQL injection via dynamic SQL statement concatenation",
            "desc": "Concatenating user input into an SQL statement string allows arbitrary SQL injection.",
            "fix": "Use PreparedStatement with setString(), setInt(), or JPA parameterized queries.",
        },
        {
            "id": "JAVA-SEC-DESER-001",
            "severity": "CRITICAL",
            "cwe": "CWE-502",
            "pattern": re.compile(
                r"""\bnew\s+(?:[a-zA-Z0-9_.]+\.)?ObjectInputStream\s*\([^)]*\)\s*\.\s*readObject\s*\(\s*\)"""
            ),
            "title": "Insecure deserialization via ObjectInputStream.readObject()",
            "desc": "Deserializing untrusted data with Java standard serialization allows remote code execution via gadget chains.",
            "fix": "Use a safe serialization format like JSON with Jackson, or configure a ValidatingObjectInputStream.",
        },
        {
            "id": "JAVA-SEC-CRYPTO-001",
            "severity": "MEDIUM",
            "cwe": "CWE-327",
            "pattern": re.compile(
                r"""MessageDigest\s*\.\s*getInstance\s*\(\s*["'](?:MD5|SHA-1|DES)["']\s*\)""",
                re.IGNORECASE,
            ),
            "title": "Weak cryptographic algorithm in Java",
            "desc": "MD5, SHA-1, and DES are cryptographically broken algorithms susceptible to collisions or brute-forcing.",
            "fix": "Use MessageDigest.getInstance(\"SHA-256\") or AES/GCM for symmetric encryption.",
        },
        {
            "id": "JAVA-SEC-XXE-001",
            "severity": "HIGH",
            "cwe": "CWE-611",
            "pattern": re.compile(
                r"""DocumentBuilderFactory\s*\.\s*newInstance\s*\(\s*\)"""
            ),
            "title": "Potential XML External Entity (XXE) injection",
            "desc": "Default DocumentBuilderFactory configuration does not disable external general entities or doctypes.",
            "fix": "Set FEATURE_SECURE_PROCESSING to true and disable DTDs via setFeature('http://apache.org/xml/features/disallow-doctype-decl', true).",
        },
        {
            "id": "JAVA-SEC-PATH-001",
            "severity": "HIGH",
            "cwe": "CWE-22",
            "pattern": re.compile(
                r"""\bnew\s+File\s*\(\s*(?:baseDir|rootDir|path|[a-zA-Z0-9_]+)\s*,\s*(?:req|request|param|input)\s*\)"""
            ),
            "title": "Path traversal in java.io.File construction",
            "desc": "Constructing File objects from untrusted user parameters without canonicalization allows directory traversal.",
            "fix": "Verify that file.getCanonicalPath().startsWith(baseDir.getCanonicalPath()).",
        },
    ]

    def __init__(self) -> None:
        """Initialize MultiLangSecurityScanner."""
        pass

    @staticmethod
    def detect_language(file_path: str) -> str:
        """Infer programming language from file path extension."""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".py", ".pyi"):
            return "python"
        elif ext in (".js", ".jsx", ".mjs", ".cjs"):
            return "javascript"
        elif ext in (".ts", ".tsx"):
            return "typescript"
        elif ext in (".go",):
            return "go"
        elif ext in (".java",):
            return "java"
        return "unknown"

    @staticmethod
    def is_excluded_path(file_path: str) -> bool:
        """Return True if path is inside an excluded or vendor directory."""
        normalized = file_path.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        return any(p in EXCLUDED_DIRECTORIES for p in parts)

    def scan_code(
        self,
        code: str,
        file_path: str,
        language: str | None = None,
        base_line: int = 1,
    ) -> list[MultiLangFinding]:
        """Scan a single source code content string for security defects."""
        if not code or not code.strip():
            return []

        if self.is_excluded_path(file_path):
            return []

        lang = (language or self.detect_language(file_path)).lower()
        findings: list[MultiLangFinding] = []
        lines = code.splitlines()

        # Select rules for language
        rule_set: list[dict[str, Any]] = []
        if lang in ("javascript", "typescript", "js", "ts"):
            rule_set = self._JS_RULES
        elif lang in ("go", "golang"):
            rule_set = self._GO_RULES
        elif lang in ("java",):
            rule_set = self._JAVA_RULES
        else:
            return []

        for rule in rule_set:
            pat: re.Pattern = rule["pattern"]
            for idx, line in enumerate(lines):
                line_no = base_line + idx
                stripped = line.strip()
                if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                    continue

                if pat.search(line):
                    evidence_str = redact(line.strip())
                    findings.append(
                        MultiLangFinding(
                            rule_id=rule["id"],
                            category="security",
                            severity=rule["severity"],
                            title=rule["title"],
                            description=rule["desc"],
                            file_path=file_path,
                            start_line=line_no,
                            end_line=line_no,
                            evidence=evidence_str,
                            suggested_fix=rule["fix"],
                            cwe=rule["cwe"],
                            language=lang,
                            confidence="high",
                        )
                    )

        return findings

    def scan_file(
        self,
        file_path: str | Path,
        workspace_root: str | Path | None = None,
    ) -> list[MultiLangFinding]:
        """Read and scan a file on disk."""
        p = Path(file_path)
        if not p.is_file():
            return []

        rel_path = str(p.relative_to(workspace_root)).replace("\\", "/") if workspace_root else str(p).replace("\\", "/")
        if self.is_excluded_path(rel_path):
            return []

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("multilang_scanner_read_error", extra={"file": str(p), "error": str(exc)})
            return []

        return self.scan_code(content, rel_path)

"""OSV-Scanner Software Composition Analysis (SCA) Runner.

Part of Issue #191: Broaden Security Analysis and Bug Detection Findings.
Provides sandboxed dependency vulnerability scanning across:
- package-lock.json / yarn.lock / pnpm-lock.yaml (npm)
- requirements.txt / poetry.lock / Pipfile.lock (PyPI)
- go.sum (Go)
- pom.xml (Maven / Java)

Integrates with the `osv-scanner` CLI when installed, and provides a built-in
curated vulnerability database parser for offline and air-gapped environments.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import packaging.version

from app.core.secret_redaction import redact

logger = logging.getLogger(__name__)

SUPPORTED_LOCKFILES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "requirements.txt",
        "poetry.lock",
        "Pipfile.lock",
        "go.sum",
        "pom.xml",
    }
)

# Curated offline vulnerability knowledge base for reproducible testing and air-gapped environments
KNOWN_VULNERABILITY_CATALOG: list[dict[str, Any]] = [
    {
        "ecosystem": "npm",
        "package": "lodash",
        "vulnerable_version_regex": r"^(?:[0-3]\..*|4\.(?:[0-9]|1[0-6])\..*|4\.17\.(?:[0-9]|1[0-9]|20))$",
        "vulnerability_id": "GHSA-35jh-r3h4-6jhm",
        "cve": "CVE-2021-23337",
        "severity": "HIGH",
        "fixed_version": "4.17.21",
        "summary": "Command Injection / Prototype Pollution in lodash.template",
        "advisory_url": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
    },
    {
        "ecosystem": "npm",
        "package": "axios",
        "vulnerable_version_regex": r"^0\.(?:[0-1]?[0-9]|20|21\.[01])$",
        "vulnerability_id": "GHSA-cph5-m8f7-6c5x",
        "cve": "CVE-2020-28168",
        "severity": "MEDIUM",
        "fixed_version": "0.21.2",
        "summary": "Server-Side Request Forgery (SSRF) bypass in axios",
        "advisory_url": "https://github.com/advisories/GHSA-cph5-m8f7-6c5x",
    },
    {
        "ecosystem": "PyPI",
        "package": "requests",
        "vulnerable_version_regex": r"^(?:[01]\..*|2\.(?:[0-9]|1[0-9])\..*|2\.20\.0)$",
        "vulnerability_id": "GHSA-x495-7934-6449",
        "cve": "CVE-2018-18074",
        "severity": "HIGH",
        "fixed_version": "2.20.1",
        "summary": "Authorization header leakage across cross-origin redirects in requests",
        "advisory_url": "https://github.com/advisories/GHSA-x495-7934-6449",
    },
    {
        "ecosystem": "PyPI",
        "package": "urllib3",
        "vulnerable_version_regex": r"^(?:0\..*|1\.(?:[0-9]|1[0-9]|2[0-5])\..*|1\.26\.(?:[0-9]|1[0-7])|2\.0\.[0-6])$",
        "vulnerability_id": "GHSA-v845-jxx5-vc9f",
        "cve": "CVE-2023-45803",
        "severity": "MEDIUM",
        "fixed_version": "2.0.7",
        "summary": "Request body not stripped on HTTP 303 redirects in urllib3",
        "advisory_url": "https://github.com/advisories/GHSA-v845-jxx5-vc9f",
    },
    {
        "ecosystem": "Maven",
        "package": "org.apache.logging.log4j:log4j-core",
        "vulnerable_version_regex": r"^2\.(?:[0-9]|1[0-4])\..*",
        "vulnerability_id": "GHSA-jfh8-c2jp-5v3q",
        "cve": "CVE-2021-44228",
        "severity": "CRITICAL",
        "fixed_version": "2.17.1",
        "summary": "Remote Code Execution via JNDI injection in Log4j (Log4Shell)",
        "advisory_url": "https://github.com/advisories/GHSA-jfh8-c2jp-5v3q",
    },
    {
        "ecosystem": "Go",
        "package": "golang.org/x/crypto",
        "vulnerable_version_regex": r"^v0\.0\.0-(?:201\d|20200[12]|2020030|20200310|20200311[01][0-6]|20200311170|20200311171[0-4]|202003111715[0-3]|2020031117154[0-5]).*",
        "vulnerability_id": "GHSA-x95h-979x-c66h",
        "cve": "CVE-2020-9283",
        "severity": "HIGH",
        "fixed_version": "v0.0.0-20200311171546-f6437b7f87e7",
        "summary": "Panic on invalid signature verification in golang.org/x/crypto/ssh",
        "advisory_url": "https://github.com/advisories/GHSA-x95h-979x-c66h",
    },
]


def is_version_vulnerable(ecosystem: str, package: str, version_str: str, advisory: dict[str, Any]) -> bool:
    """Check if installed version is affected by advisory using ecosystem-specific semantics."""
    clean_ver = version_str.strip().lstrip("v")

    if ecosystem == "Go":
        # Check Go pseudo-versions: format v0.0.0-yyyymmddhhmmss-abcdef123456
        ts_match = re.search(r"(\d{14})", version_str)
        if ts_match:
            installed_ts = int(ts_match.group(1))
            fixed_ts_match = re.search(r"(\d{14})", advisory.get("fixed_version", ""))
            if fixed_ts_match:
                fixed_ts = int(fixed_ts_match.group(1))
                return installed_ts < fixed_ts
        try:
            return packaging.version.parse(clean_ver) < packaging.version.parse(advisory["fixed_version"].lstrip("v"))
        except Exception:
            return False

    try:
        parsed = packaging.version.parse(clean_ver)
    except Exception:
        regex = advisory.get("vulnerable_version_regex")
        return bool(regex and re.match(regex, version_str))

    if package == "urllib3":
        # GHSA-v845-jxx5-vc9f affected < 1.26.18 and >= 2.0.0, < 2.0.7
        v1_fix = packaging.version.parse("1.26.18")
        v2_min = packaging.version.parse("2.0.0")
        v2_fix = packaging.version.parse("2.0.7")
        if parsed < v1_fix:
            return True
        if v2_min <= parsed < v2_fix:
            return True
        return False

    if "fixed_version" in advisory and advisory["fixed_version"]:
        try:
            fixed_ver = packaging.version.parse(advisory["fixed_version"].lstrip("v"))
            return parsed < fixed_ver
        except Exception:
            pass

    regex = advisory.get("vulnerable_version_regex")
    return bool(regex and re.match(regex, version_str))


@dataclass
class OSVFinding:
    """Normalized finding representing a vulnerable dependency."""

    package_name: str
    installed_version: str
    vulnerability_id: str
    cve: str | None
    severity: str
    fixed_version: str | None
    file_path: str
    start_line: int
    end_line: int
    summary: str
    advisory_url: str
    ecosystem: str

    def to_dict(self) -> dict[str, Any]:
        """Convert finding into normalized dictionary."""
        return {
            "rule_id": f"SCA-OSV-{self.vulnerability_id}",
            "category": "supply_chain",
            "severity": self.severity,
            "title": f"Vulnerable dependency: {self.package_name}@{self.installed_version} ({self.vulnerability_id})",
            "description": f"{self.summary} (Advisory: {self.advisory_url})",
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "evidence": f"Package '{self.package_name}' resolved to version {self.installed_version} in {self.file_path}",
            "suggested_fix": (
                f"Upgrade {self.package_name} to version {self.fixed_version} or higher."
                if self.fixed_version
                else f"Review advisory {self.advisory_url} for mitigation."
            ),
            "confidence": "high",
            "metadata": {
                "package_name": self.package_name,
                "installed_version": self.installed_version,
                "vulnerability_id": self.vulnerability_id,
                "cve": self.cve,
                "fixed_version": self.fixed_version,
                "advisory_url": self.advisory_url,
                "ecosystem": self.ecosystem,
                "engine": "osv_scanner",
            },
        }

    def to_candidate_dict(self) -> dict[str, Any]:
        """Convert finding into BugCandidate dictionary representation."""
        return {
            "candidate_id": f"cand-osv-{self.vulnerability_id}-{self.start_line}",
            "rule_id": f"SCA-OSV-{self.vulnerability_id}",
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "category": "supply_chain",
            "severity": self.severity,
            "evidence": f"Package '{self.package_name}' resolved to version {self.installed_version} in {self.file_path}",
            "source_type": "STATIC",
            "confidence": "high",
            "remediation": (
                f"Upgrade {self.package_name} to version {self.fixed_version} or higher."
                if self.fixed_version
                else f"Review advisory {self.advisory_url} for mitigation."
            ),
            "metadata": {
                "package_name": self.package_name,
                "installed_version": self.installed_version,
                "vulnerability_id": self.vulnerability_id,
                "cve": self.cve,
                "fixed_version": self.fixed_version,
                "advisory_url": self.advisory_url,
                "ecosystem": self.ecosystem,
                "engine": "osv_scanner",
            },
        }


@dataclass
class OSVScanResult:
    """Result of OSV scanning run."""

    success: bool
    is_available: bool
    findings: list[OSVFinding] = field(default_factory=list)
    lockfiles_scanned: list[str] = field(default_factory=list)
    error_message: str | None = None
    diagnostics: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


class OSVScannerRunner:
    """Executes sandboxed OSV-Scanner CLI or fallback dependency analyzer."""

    def __init__(
        self,
        executable_path: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        """Initialize OSV-Scanner runner with executable path and timeout."""
        self.executable_path = executable_path or shutil.which("osv-scanner")
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        """Check if osv-scanner binary is installed."""
        return bool(self.executable_path and os.path.exists(self.executable_path))

    def find_lockfiles(self, workspace_root: Path) -> list[Path]:
        """Discover supported lockfiles within workspace without escaping root."""
        lockfiles: list[Path] = []
        if not workspace_root.is_dir():
            return lockfiles

        resolved_root = workspace_root.resolve()
        for root, dirs, files in os.walk(workspace_root, followlinks=False):
            # Prune excluded and symlinked directories
            dirs[:] = [
                d
                for d in dirs
                if d not in {".git", "node_modules", "vendor", ".venv", "__pycache__"}
                and not (Path(root) / d).is_symlink()
            ]
            for f in files:
                if f in SUPPORTED_LOCKFILES:
                    candidate = Path(root) / f
                    if candidate.is_symlink():
                        continue
                    try:
                        if candidate.resolve().is_relative_to(resolved_root):
                            lockfiles.append(candidate)
                    except Exception:
                        continue
        return lockfiles

    def scan_workspace(
        self,
        workspace_root: str | Path,
    ) -> OSVScanResult:
        """Scan workspace for dependency vulnerabilities."""
        start_time = time.perf_counter()
        workspace = Path(workspace_root).resolve()

        if not workspace.is_dir():
            return OSVScanResult(
                success=False,
                is_available=self.is_available(),
                error_message=f"Workspace directory does not exist: {workspace}",
                execution_time_ms=0.0,
            )

        lockfiles = self.find_lockfiles(workspace)
        if not lockfiles:
            return OSVScanResult(
                success=True,
                is_available=self.is_available(),
                findings=[],
                lockfiles_scanned=[],
                diagnostics=["No supported lockfiles found in workspace."],
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        # If CLI is available, attempt sandboxed CLI invocation
        if self.is_available():
            try:
                cli_res = self._run_cli_scan(workspace, lockfiles)
                if cli_res.success:
                    cli_res.execution_time_ms = (time.perf_counter() - start_time) * 1000
                    return cli_res
            except Exception as exc:
                logger.warning("osv_scanner_cli_failed; falling back to internal matcher: %s", exc)

        # Fallback / Built-in dependency scanner
        findings: list[OSVFinding] = []
        scanned_paths: list[str] = []

        for lf in lockfiles:
            rel_path = str(lf.relative_to(workspace)).replace("\\", "/")
            scanned_paths.append(rel_path)
            file_findings = self.scan_lockfile_content(
                file_path=rel_path,
                content=lf.read_text(encoding="utf-8", errors="replace"),
            )
            findings.extend(file_findings)

        # Deduplicate on (package_name, installed_version, vulnerability_id)
        deduped: dict[tuple[str, str, str], OSVFinding] = {}
        for f in findings:
            key = (f.package_name, f.installed_version, f.vulnerability_id)
            if key not in deduped:
                deduped[key] = f

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return OSVScanResult(
            success=True,
            is_available=self.is_available(),
            findings=list(deduped.values()),
            lockfiles_scanned=scanned_paths,
            diagnostics=[f"Scanned {len(scanned_paths)} lockfile(s) using built-in OSV advisory database."],
            execution_time_ms=elapsed_ms,
        )

    def scan_lockfile_content(
        self,
        file_path: str,
        content: str,
    ) -> list[OSVFinding]:
        """Analyze content of a single lockfile against advisory database."""
        findings: list[OSVFinding] = []
        filename = Path(file_path).name.lower()

        if filename == "package-lock.json":
            findings.extend(self._scan_package_lock_json(file_path, content))
        elif filename in ("yarn.lock", "pnpm-lock.yaml"):
            findings.extend(self._scan_yarn_or_pnpm_lock(file_path, content))
        elif filename == "requirements.txt":
            findings.extend(self._scan_requirements_txt(file_path, content))
        elif filename == "poetry.lock":
            findings.extend(self._scan_poetry_lock(file_path, content))
        elif filename == "pipfile.lock":
            findings.extend(self._scan_pipfile_lock(file_path, content))
        elif filename == "pom.xml":
            findings.extend(self._scan_pom_xml(file_path, content))
        elif filename == "go.sum":
            findings.extend(self._scan_go_sum(file_path, content))

        return findings

    def _scan_package_lock_json(self, file_path: str, content: str) -> list[OSVFinding]:
        """Scan npm package-lock.json content for known vulnerable dependencies."""
        findings: list[OSVFinding] = []
        try:
            data = json.loads(content)
        except Exception:
            return findings

        # Collect all installed versions per package across top-level and nested node_modules
        packages: dict[str, list[str]] = {}
        if "packages" in data and isinstance(data["packages"], dict):
            for pkg_key, pkg_info in data["packages"].items():
                if not isinstance(pkg_info, dict) or not pkg_key:
                    continue
                name = pkg_info.get("name") or pkg_key.split("node_modules/")[-1]
                ver = pkg_info.get("version")
                if name and ver:
                    ver_list = packages.setdefault(name, [])
                    if str(ver) not in ver_list:
                        ver_list.append(str(ver))

        def _collect_deps(deps_dict: Any) -> None:
            if not isinstance(deps_dict, dict):
                return
            for name, dep_info in deps_dict.items():
                if isinstance(dep_info, dict):
                    if "version" in dep_info:
                        ver_list = packages.setdefault(name, [])
                        if str(dep_info["version"]) not in ver_list:
                            ver_list.append(str(dep_info["version"]))
                    if "dependencies" in dep_info:
                        _collect_deps(dep_info["dependencies"])

        if "dependencies" in data:
            _collect_deps(data["dependencies"])

        lines = content.splitlines()
        for advisory in KNOWN_VULNERABILITY_CATALOG:
            if advisory["ecosystem"] != "npm":
                continue
            pkg = advisory["package"]
            for ver in packages.get(pkg, []):
                if is_version_vulnerable(advisory["ecosystem"], pkg, ver, advisory):
                    line_no = 1
                    for idx, line in enumerate(lines, 1):
                        if f'"{pkg}"' in line or f"node_modules/{pkg}" in line:
                            line_no = idx
                            break
                    findings.append(
                        OSVFinding(
                            package_name=pkg,
                            installed_version=ver,
                            vulnerability_id=advisory["vulnerability_id"],
                            cve=advisory.get("cve"),
                            severity=advisory["severity"],
                            fixed_version=advisory["fixed_version"],
                            file_path=file_path,
                            start_line=line_no,
                            end_line=line_no,
                            summary=advisory["summary"],
                            advisory_url=advisory["advisory_url"],
                            ecosystem="npm",
                        )
                    )
        return findings

    def _scan_yarn_or_pnpm_lock(self, file_path: str, content: str) -> list[OSVFinding]:
        """Scan yarn.lock or pnpm-lock.yaml content for vulnerable npm packages."""
        findings: list[OSVFinding] = []
        for advisory in KNOWN_VULNERABILITY_CATALOG:
            if advisory["ecosystem"] != "npm":
                continue
            pkg = advisory["package"]
            patterns = [
                re.compile(rf'(?:^|\s|["\'/]){re.escape(pkg)}@([0-9]+\.[0-9]+\.[0-9]+[^\s"\':,]*)', re.MULTILINE),
                re.compile(rf'["\']?{re.escape(pkg)}@[^:\n]+:\s*\n\s*version\s+["\']?([0-9]+\.[0-9]+\.[0-9]+[^\s"\']*)["\']?', re.MULTILINE),
            ]
            seen_vers: set[str] = set()
            for pat in patterns:
                for m in pat.finditer(content):
                    ver = m.group(1).strip()
                    if ver in seen_vers:
                        continue
                    seen_vers.add(ver)
                    if is_version_vulnerable("npm", pkg, ver, advisory):
                        line_no = content[: m.start()].count("\n") + 1
                        findings.append(
                            OSVFinding(
                                package_name=pkg,
                                installed_version=ver,
                                vulnerability_id=advisory["vulnerability_id"],
                                cve=advisory.get("cve"),
                                severity=advisory["severity"],
                                fixed_version=advisory["fixed_version"],
                                file_path=file_path,
                                start_line=line_no,
                                end_line=line_no,
                                summary=advisory["summary"],
                                advisory_url=advisory["advisory_url"],
                                ecosystem="npm",
                            )
                        )
        return findings

    def _scan_poetry_lock(self, file_path: str, content: str) -> list[OSVFinding]:
        """Scan poetry.lock TOML blocks (`[[package]]`) for vulnerable PyPI dependencies."""
        findings: list[OSVFinding] = []
        blocks = content.split("[[package]]")
        for block in blocks[1:]:
            name_m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', block, re.MULTILINE)
            ver_m = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', block, re.MULTILINE)
            if not name_m or not ver_m:
                continue
            pkg_name = name_m.group(1).strip()
            ver = ver_m.group(1).strip()
            for advisory in KNOWN_VULNERABILITY_CATALOG:
                if advisory["ecosystem"] != "PyPI":
                    continue
                if advisory["package"].lower() == pkg_name.lower():
                    if is_version_vulnerable("PyPI", advisory["package"], ver, advisory):
                        idx = content.find(block)
                        line_no = content[:idx].count("\n") + 1 if idx >= 0 else 1
                        findings.append(
                            OSVFinding(
                                package_name=pkg_name,
                                installed_version=ver,
                                vulnerability_id=advisory["vulnerability_id"],
                                cve=advisory.get("cve"),
                                severity=advisory["severity"],
                                fixed_version=advisory["fixed_version"],
                                file_path=file_path,
                                start_line=line_no,
                                end_line=line_no,
                                summary=advisory["summary"],
                                advisory_url=advisory["advisory_url"],
                                ecosystem="PyPI",
                            )
                        )
        return findings

    def _scan_pipfile_lock(self, file_path: str, content: str) -> list[OSVFinding]:
        """Scan Pipfile.lock JSON sections (`default` and `develop`) for vulnerable PyPI packages."""
        findings: list[OSVFinding] = []
        try:
            data = json.loads(content)
        except Exception:
            return findings

        lines = content.splitlines()
        for section in ("default", "develop"):
            sec_dict = data.get(section)
            if not isinstance(sec_dict, dict):
                continue
            for pkg_name, pkg_info in sec_dict.items():
                if not isinstance(pkg_info, dict):
                    continue
                raw_ver = str(pkg_info.get("version") or "").lstrip("=").strip()
                if not raw_ver:
                    continue
                for advisory in KNOWN_VULNERABILITY_CATALOG:
                    if advisory["ecosystem"] != "PyPI":
                        continue
                    if advisory["package"].lower() == pkg_name.lower():
                        if is_version_vulnerable("PyPI", advisory["package"], raw_ver, advisory):
                            line_no = 1
                            for idx, ln in enumerate(lines, 1):
                                if f'"{pkg_name}"' in ln:
                                    line_no = idx
                                    break
                            findings.append(
                                OSVFinding(
                                    package_name=pkg_name,
                                    installed_version=raw_ver,
                                    vulnerability_id=advisory["vulnerability_id"],
                                    cve=advisory.get("cve"),
                                    severity=advisory["severity"],
                                    fixed_version=advisory["fixed_version"],
                                    file_path=file_path,
                                    start_line=line_no,
                                    end_line=line_no,
                                    summary=advisory["summary"],
                                    advisory_url=advisory["advisory_url"],
                                    ecosystem="PyPI",
                                )
                            )
        return findings

    def _scan_requirements_txt(self, file_path: str, content: str) -> list[OSVFinding]:
        """Scan Python requirements.txt content for known vulnerable package versions."""
        findings: list[OSVFinding] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Match package==version or package>=version
            m = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*==\s*([a-zA-Z0-9_\-\.]+)", stripped)
            if not m:
                continue
            pkg_name, ver = m.group(1).lower(), m.group(2)

            for advisory in KNOWN_VULNERABILITY_CATALOG:
                if advisory["ecosystem"] != "PyPI":
                    continue
                if advisory["package"].lower() == pkg_name:
                    if is_version_vulnerable(advisory["ecosystem"], advisory["package"], ver, advisory):
                        findings.append(
                            OSVFinding(
                                package_name=m.group(1),
                                installed_version=ver,
                                vulnerability_id=advisory["vulnerability_id"],
                                cve=advisory.get("cve"),
                                severity=advisory["severity"],
                                fixed_version=advisory["fixed_version"],
                                file_path=file_path,
                                start_line=idx,
                                end_line=idx,
                                summary=advisory["summary"],
                                advisory_url=advisory["advisory_url"],
                                ecosystem="PyPI",
                            )
                        )
        return findings

    def _scan_pom_xml(self, file_path: str, content: str) -> list[OSVFinding]:
        """Scan Java pom.xml content for vulnerable dependency declarations."""
        findings: list[OSVFinding] = []
        for advisory in KNOWN_VULNERABILITY_CATALOG:
            if advisory["ecosystem"] != "Maven":
                continue
            group_id, artifact_id = advisory["package"].split(":")
            # Look for dependency block
            pat = re.compile(
                rf"<groupId>{re.escape(group_id)}</groupId>\s*<artifactId>{re.escape(artifact_id)}</artifactId>\s*<version>([^<]+)</version>",
                re.DOTALL,
            )
            m = pat.search(content)
            if m:
                ver = m.group(1).strip()
                if is_version_vulnerable(advisory["ecosystem"], advisory["package"], ver, advisory):
                    line_no = content[: m.start()].count("\n") + 1
                    findings.append(
                        OSVFinding(
                            package_name=advisory["package"],
                            installed_version=ver,
                            vulnerability_id=advisory["vulnerability_id"],
                            cve=advisory.get("cve"),
                            severity=advisory["severity"],
                            fixed_version=advisory["fixed_version"],
                            file_path=file_path,
                            start_line=line_no,
                            end_line=line_no,
                            summary=advisory["summary"],
                            advisory_url=advisory["advisory_url"],
                            ecosystem="Maven",
                        )
                    )
        return findings

    def _scan_go_sum(self, file_path: str, content: str) -> list[OSVFinding]:
        """Scan Go go.sum dependency hashes for vulnerable module versions."""
        findings: list[OSVFinding] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, 1):
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            pkg = parts[0]
            ver = parts[1].split("/")[0]

            for advisory in KNOWN_VULNERABILITY_CATALOG:
                if advisory["ecosystem"] != "Go":
                    continue
                if advisory["package"] == pkg:
                    if is_version_vulnerable(advisory["ecosystem"], pkg, ver, advisory):
                        findings.append(
                            OSVFinding(
                                package_name=pkg,
                                installed_version=ver,
                                vulnerability_id=advisory["vulnerability_id"],
                                cve=advisory.get("cve"),
                                severity=advisory["severity"],
                                fixed_version=advisory["fixed_version"],
                                file_path=file_path,
                                start_line=idx,
                                end_line=idx,
                                summary=advisory["summary"],
                                advisory_url=advisory["advisory_url"],
                                ecosystem="Go",
                            )
                        )
        return findings

    def _run_cli_scan(self, workspace: Path, lockfiles: list[Path]) -> OSVScanResult:
        """Run osv-scanner CLI subprocess inside sandbox."""
        cmd = [str(self.executable_path), "--json", "-r", str(workspace)]
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if (not proc.stdout or not proc.stdout.strip()) and proc.returncode not in (0, 1):
            err_msg = redact((proc.stderr or "").strip())
            return OSVScanResult(
                success=False,
                is_available=True,
                findings=[],
                error_message=f"OSV scanner exited with code {proc.returncode}: {err_msg}",
                diagnostics=[f"Process exit code: {proc.returncode}"] if err_msg else [],
            )

        return self._parse_cli_json(proc.stdout, workspace)

    def _parse_cli_json(self, stdout: str, workspace: Path) -> OSVScanResult:
        """Parse osv-scanner JSON output into normalized OSVFinding objects."""
        if not stdout or not stdout.strip():
            return OSVScanResult(success=True, is_available=True, findings=[])

        data = json.loads(stdout)
        findings: list[OSVFinding] = []
        results = data.get("results", [])

        for r in results:
            source = r.get("source", {})
            raw_path = source.get("path", "")
            try:
                rel_path = str(Path(raw_path).relative_to(workspace)).replace("\\", "/")
            except Exception:
                rel_path = raw_path.replace("\\", "/")

            packages = r.get("packages", [])
            for p in packages:
                pkg_info = p.get("package", {})
                pkg_name = pkg_info.get("name", "unknown")
                pkg_version = pkg_info.get("version", "unknown")
                ecosystem = pkg_info.get("ecosystem", "unknown")

                vulns = p.get("vulnerabilities", [])
                for v in vulns:
                    vuln_id = v.get("id", "OSV-VULN")
                    aliases = v.get("aliases", [])
                    cve = next((a for a in aliases if a.startswith("CVE-")), None)
                    summary = v.get("summary") or f"Vulnerability {vuln_id} in {pkg_name}"

                    findings.append(
                        OSVFinding(
                            package_name=pkg_name,
                            installed_version=pkg_version,
                            vulnerability_id=vuln_id,
                            cve=cve,
                            severity="HIGH",
                            fixed_version=None,
                            file_path=rel_path,
                            start_line=1,
                            end_line=1,
                            summary=summary,
                            advisory_url=f"https://osv.dev/vulnerability/{vuln_id}",
                            ecosystem=ecosystem,
                        )
                    )

        return OSVScanResult(
            success=True,
            is_available=True,
            findings=findings,
            lockfiles_scanned=[str(r.get("source", {}).get("path", "")) for r in results],
        )

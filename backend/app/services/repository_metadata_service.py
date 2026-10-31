"""
Repository Metadata Service.
Handles dependency manifest extraction and metadata analysis without depending on FastAPI Request/Response objects.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.repository_file import RepositoryFile
from app.schemas.repository import RepositoryDependencyResponse

logger = logging.getLogger(__name__)


def extract_repository_dependencies(repository_id: UUID, db: Session) -> list[RepositoryDependencyResponse]:
    """Parse top-level dependency manifests (package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml, Pipfile) indexed for this repository."""
    if not hasattr(db, "query"):
        return []

    try:
        manifest_files = (
            db.query(RepositoryFile)
            .filter(
                RepositoryFile.repository_id == repository_id,
                or_(
                    RepositoryFile.path.endswith("package.json"),
                    RepositoryFile.path.endswith("requirements.txt"),
                    RepositoryFile.path.endswith("Pipfile"),
                    RepositoryFile.path.endswith("pyproject.toml"),
                    RepositoryFile.path.endswith("go.mod"),
                    RepositoryFile.path.endswith("Cargo.toml"),
                ),
            )
            .all()
        )

        if not manifest_files:
            return []

        manifest_ids = [f.id for f in manifest_files]
        all_manifest_chunks = (
            db.query(CodeChunk.file_id, CodeChunk.content)
            .filter(
                CodeChunk.repository_id == repository_id,
                CodeChunk.file_id.in_(manifest_ids),
            )
            .order_by(CodeChunk.file_id, CodeChunk.start_line)
            .all()
        )
        chunks_by_file: dict[UUID, list[str]] = {}
        for f_id, c_text in all_manifest_chunks:
            if c_text:
                chunks_by_file.setdefault(f_id, []).append(c_text)

        dependencies: list[RepositoryDependencyResponse] = []
        for file in manifest_files:
            content = "\n".join(chunks_by_file.get(file.id, []))
            if file.path.endswith("package.json"):
                try:
                    data = json.loads(content)
                    deps = data.get("dependencies", {})
                    dev_deps = data.get("devDependencies", {})
                    for name, ver in deps.items():
                        dependencies.append(RepositoryDependencyResponse(name=name, version=str(ver), ecosystem="npm"))
                    for name, ver in dev_deps.items():
                        dependencies.append(RepositoryDependencyResponse(name=name, version=str(ver), ecosystem="npm"))
                except Exception:
                    pass
            elif file.path.endswith("requirements.txt"):
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith(("#", "-", "http://", "https://")):
                        continue
                    match = re.match(r"^([A-Za-z0-9_\-\.]+)(?:([<>=!~]+.*))?$", line)
                    if match:
                        name, ver = match.groups()
                        dependencies.append(
                            RepositoryDependencyResponse(
                                name=name,
                                version=ver.strip() if ver else "*",
                                ecosystem="pip",
                            )
                        )
            elif file.path.endswith("go.mod"):
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("require "):
                        parts = line.split()
                        if len(parts) >= 3:
                            dependencies.append(RepositoryDependencyResponse(name=parts[1], version=parts[2], ecosystem="gomod"))
                    elif not line.startswith("//") and len(line.split()) == 2:
                        parts = line.split()
                        if "." in parts[0] or "/" in parts[0]:
                            dependencies.append(RepositoryDependencyResponse(name=parts[0], version=parts[1], ecosystem="gomod"))
            elif file.path.endswith("Cargo.toml"):
                in_deps = False
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("[dependencies"):
                        in_deps = True
                        continue
                    elif line.startswith("["):
                        in_deps = False
                    if in_deps and "=" in line and not line.startswith("#"):
                        parts = line.split("=", 1)
                        name = parts[0].strip()
                        ver = parts[1].strip().strip('"').strip("'")
                        dependencies.append(RepositoryDependencyResponse(name=name, version=ver, ecosystem="cargo"))
            elif file.path.endswith("pyproject.toml"):
                try:
                    import tomllib

                    toml_data = tomllib.loads(content)
                    proj_deps = toml_data.get("project", {}).get("dependencies", [])
                    for spec in proj_deps:
                        m = re.match(r"^([A-Za-z0-9_\-\.]+)(?:\[[^\]]*\])?\s*(.*)$", str(spec).strip())
                        if m:
                            pkg_name, pkg_ver = m.groups()
                            dependencies.append(
                                RepositoryDependencyResponse(
                                    name=pkg_name,
                                    version=pkg_ver.strip() or "*",
                                    ecosystem="pip",
                                )
                            )
                    poetry_deps = toml_data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                    if isinstance(poetry_deps, dict):
                        for pkg_name, pkg_spec in poetry_deps.items():
                            if pkg_name.lower() == "python":
                                continue
                            ver_str = (
                                pkg_spec.get("version", "*")
                                if isinstance(pkg_spec, dict)
                                else str(pkg_spec)
                            )
                            dependencies.append(
                                RepositoryDependencyResponse(
                                    name=pkg_name,
                                    version=ver_str,
                                    ecosystem="pip",
                                )
                            )
                except Exception:
                    pass
            elif file.path.endswith("Pipfile"):
                section = ""
                for raw_ln in content.splitlines():
                    ln = raw_ln.strip()
                    if not ln or ln.startswith("#"):
                        continue
                    if ln.startswith("[") and ln.endswith("]"):
                        section = ln[1:-1].strip().lower()
                        continue
                    if section in ("packages", "dev-packages") and "=" in ln:
                        pkg_name, pkg_val = ln.split("=", 1)
                        pkg_name = pkg_name.strip().strip('"').strip("'")
                        pkg_val = pkg_val.strip().strip('"').strip("'")
                        dependencies.append(
                            RepositoryDependencyResponse(
                                name=pkg_name,
                                version=pkg_val or "*",
                                ecosystem="pip",
                            )
                        )
        return dependencies
    except Exception as exc:
        logger.warning("dependency_extraction_error: %s", exc)
        return []


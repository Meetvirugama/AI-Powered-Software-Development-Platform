"""Import tracking and mapping engine.

Owner: Prit — Repository Engine Lead (W2-07)
Fulfills Week 2 Day 1: AST symbol range resolution & import mapping.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Set

from .symbols import FileInfo

logger = logging.getLogger(__name__)

# Known Python standard library modules (for fast categorization)
PYTHON_STDLIB: Set[str] = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "collections",
    "concurrent", "contextlib", "copy", "csv", "dataclasses", "datetime",
    "decimal", "difflib", "dis", "doctest", "email", "enum", "errno",
    "fnmatch", "fractions", "functools", "gc", "glob", "gzip", "hashlib",
    "heapq", "hmac", "html", "http", "importlib", "inspect", "io", "itertools",
    "json", "keyword", "linecache", "locale", "logging", "math", "mimetypes",
    "multiprocessing", "operator", "os", "pathlib", "pickle", "platform",
    "pprint", "queue", "random", "re", "shutil", "signal", "site", "smtplib",
    "socket", "sqlite3", "ssl", "stat", "string", "struct", "subprocess",
    "sys", "tempfile", "textwrap", "threading", "time", "token", "tokenize",
    "traceback", "types", "typing", "unittest", "urllib", "uuid", "venv",
    "warnings", "weakref", "zipfile", "zlib",
}

# Known Node.js standard library modules
NODE_STDLIB: Set[str] = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "dns", "domain", "events", "fs", "http",
    "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks",
    "process", "punycode", "querystring", "readline", "repl", "stream",
    "string_decoder", "timers", "tls", "trace_events", "tty", "url", "util",
    "v8", "vm", "wasi", "worker_threads", "zlib",
}


@dataclass
class ImportedSymbol:
    """Represents an imported symbol, its source module, alias, and resolved location."""

    name: str  # Identifier imported into namespace (e.g. "User", "FastAPI", "*")
    module: str  # Declared origin module (e.g. ".models", "fastapi", "./types")
    alias: Optional[str] = None  # Local alias if imported as e.g. "as UserModel"
    is_relative: bool = False  # True if relative import (e.g. starts with . or ./)
    level: int = 0  # Relative level in Python (1 for '.', 2 for '..', etc.)
    line: int = 1  # 1-indexed line number in source
    raw_statement: str = ""  # Full text of import statement
    is_standard_library: bool = False
    is_third_party: bool = False
    resolved_path: Optional[str] = None  # Local repository path if successfully resolved

    @property
    def local_name(self) -> str:
        """The identifier name available in the file's local scope."""
        return self.alias or self.name

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "module": self.module,
            "alias": self.alias,
            "local_name": self.local_name,
            "is_relative": self.is_relative,
            "level": self.level,
            "line": self.line,
            "raw_statement": self.raw_statement,
            "is_standard_library": self.is_standard_library,
            "is_third_party": self.is_third_party,
            "resolved_path": self.resolved_path,
        }


@dataclass
class FileImportMap:
    """Index of all imports in a file with categorized dependencies."""

    file_path: str
    language: str
    imports: List[ImportedSymbol] = field(default_factory=list)
    by_name: Dict[str, ImportedSymbol] = field(default_factory=dict)
    local_dependencies: List[str] = field(default_factory=list)
    external_dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "language": self.language,
            "imports": [i.to_dict() for i in self.imports],
            "by_name": {k: v.to_dict() for k, v in self.by_name.items()},
            "local_dependencies": self.local_dependencies,
            "external_dependencies": self.external_dependencies,
        }


class ImportTracker:
    """Extracts, categorizes, and tracks imports across Python, TypeScript,

    and JavaScript source files. Resolves local dependencies against workspace files.
    """

    def parse_imports(
        self,
        file_info: FileInfo,
        content: str,
        known_files: Optional[Sequence[str]] = None,
    ) -> FileImportMap:
        """Parse all import statements in a file and resolve local file dependencies."""
        imports: List[ImportedSymbol] = []
        lang = file_info.language

        if lang == "Python":
            imports = self._parse_python_imports(content)
        elif lang in ("TypeScript", "JavaScript"):
            imports = self._parse_js_ts_imports(content)
        else:
            imports = self._parse_generic_imports(content)

        # Normalize known files for fast matching
        norm_known: Set[str] = set()
        if known_files:
            norm_known = {f.replace("\\", "/") for f in known_files}

        current_dir = os.path.dirname(file_info.path.replace("\\", "/"))

        # Resolve local paths & categorize
        by_name: Dict[str, ImportedSymbol] = {}
        local_deps: Set[str] = set()
        external_deps: Set[str] = set()

        for imp in imports:
            by_name[imp.local_name] = imp

            # Categorize module
            root_mod = imp.module.lstrip(".").split(".")[0] if imp.module else ""
            if lang == "Python":
                if imp.is_relative:
                    imp.is_third_party = False
                    imp.is_standard_library = False
                elif root_mod in PYTHON_STDLIB:
                    imp.is_standard_library = True
                    imp.is_third_party = False
                else:
                    imp.is_third_party = True
            elif lang in ("TypeScript", "JavaScript"):
                if imp.is_relative:
                    imp.is_third_party = False
                    imp.is_standard_library = False
                elif imp.module in NODE_STDLIB or imp.module.startswith("node:"):
                    imp.is_standard_library = True
                    imp.is_third_party = False
                else:
                    imp.is_third_party = True

            # Attempt local resolution
            if imp.is_relative or norm_known:
                resolved = self._resolve_local_path(
                    imp, file_info.path, lang, norm_known
                )
                if resolved:
                    imp.resolved_path = resolved
                    imp.is_third_party = False
                    local_deps.add(resolved)
                elif imp.is_third_party:
                    external_deps.add(imp.module.split("/")[0])
            elif imp.is_third_party:
                external_deps.add(imp.module.split("/")[0])

        return FileImportMap(
            file_path=file_info.path.replace("\\", "/"),
            language=lang,
            imports=imports,
            by_name=by_name,
            local_dependencies=sorted(list(local_deps)),
            external_dependencies=sorted(list(external_deps)),
        )

    def _parse_python_imports(self, content: str) -> List[ImportedSymbol]:
        """Extract Python imports using standard library AST with line numbers."""
        import ast

        imports: List[ImportedSymbol] = []
        lines = content.splitlines()

        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    raw = lines[node.lineno - 1].strip() if 1 <= node.lineno <= len(lines) else ""
                    for alias in node.names:
                        imports.append(
                            ImportedSymbol(
                                name=alias.name,
                                module=alias.name,
                                alias=alias.asname,
                                is_relative=False,
                                level=0,
                                line=node.lineno,
                                raw_statement=raw,
                            )
                        )
                elif isinstance(node, ast.ImportFrom):
                    raw = lines[node.lineno - 1].strip() if 1 <= node.lineno <= len(lines) else ""
                    mod = node.module or ""
                    level = node.level or 0
                    is_rel = level > 0

                    prefix = "." * level
                    full_mod = f"{prefix}{mod}" if is_rel else mod

                    for alias in node.names:
                        imports.append(
                            ImportedSymbol(
                                name=alias.name,
                                module=full_mod,
                                alias=alias.asname,
                                is_relative=is_rel,
                                level=level,
                                line=node.lineno,
                                raw_statement=raw,
                            )
                        )
        except Exception:
            # Fallback to regex parsing if file has syntax errors
            imports = self._regex_parse_python(content)

        return imports

    def _regex_parse_python(self, content: str) -> List[ImportedSymbol]:
        """Regex fallback for Python files with syntax errors."""
        imports: List[ImportedSymbol] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            # from X import Y as Z
            m_from = re.match(r"^from\s+([.\w]+)\s+import\s+(.+)$", s)
            if m_from:
                mod = m_from.group(1)
                is_rel = mod.startswith(".")
                level = len(re.match(r"^\.*", mod).group(0)) if is_rel else 0
                items_str = m_from.group(2).split("#")[0]
                for item in items_str.split(","):
                    item = item.strip()
                    if not item:
                        continue
                    m_as = re.match(r"^([a-zA-Z_]\w*)(?:\s+as\s+([a-zA-Z_]\w*))?$", item)
                    if m_as:
                        name, alias = m_as.group(1), m_as.group(2)
                        imports.append(
                            ImportedSymbol(
                                name=name,
                                module=mod,
                                alias=alias,
                                is_relative=is_rel,
                                level=level,
                                line=idx,
                                raw_statement=s,
                            )
                        )
                continue

            # import X as Y, Z
            m_imp = re.match(r"^import\s+(.+)$", s)
            if m_imp:
                items_str = m_imp.group(1).split("#")[0]
                for item in items_str.split(","):
                    item = item.strip()
                    if not item:
                        continue
                    m_as = re.match(r"^([a-zA-Z_][\w.]*)(?:\s+as\s+([a-zA-Z_]\w*))?$", item)
                    if m_as:
                        mod, alias = m_as.group(1), m_as.group(2)
                        imports.append(
                            ImportedSymbol(
                                name=mod,
                                module=mod,
                                alias=alias,
                                is_relative=False,
                                level=0,
                                line=idx,
                                raw_statement=s,
                            )
                        )

        return imports

    def _parse_js_ts_imports(self, content: str) -> List[ImportedSymbol]:
        """Parse JavaScript and TypeScript ES6 import and CommonJS require statements."""
        imports: List[ImportedSymbol] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            s = line.strip()

            # 1. import { a, b as c } from './mod'
            m_named = re.search(r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]", s)
            if m_named:
                mod = m_named.group(2)
                is_rel = mod.startswith(".")
                for item in m_named.group(1).split(","):
                    item = item.strip()
                    if not item:
                        continue
                    parts = re.split(r"\s+as\s+", item)
                    name = parts[0].strip()
                    alias = parts[1].strip() if len(parts) > 1 else None
                    imports.append(
                        ImportedSymbol(
                            name=name,
                            module=mod,
                            alias=alias,
                            is_relative=is_rel,
                            line=idx,
                            raw_statement=s,
                        )
                    )
                continue

            # 2. import * as Name from './mod'
            m_ns = re.search(r"import\s*\*\s*as\s+([a-zA-Z_]\w*)\s+from\s*['\"]([^'\"]+)['\"]", s)
            if m_ns:
                alias = m_ns.group(1)
                mod = m_ns.group(2)
                imports.append(
                    ImportedSymbol(
                        name="*",
                        module=mod,
                        alias=alias,
                        is_relative=mod.startswith("."),
                        line=idx,
                        raw_statement=s,
                    )
                )
                continue

            # 3. import DefaultExport from './mod'
            m_def = re.search(r"import\s+([a-zA-Z_]\w*)\s+from\s*['\"]([^'\"]+)['\"]", s)
            if m_def:
                name = m_def.group(1)
                mod = m_def.group(2)
                imports.append(
                    ImportedSymbol(
                        name=name,
                        module=mod,
                        alias=None,
                        is_relative=mod.startswith("."),
                        line=idx,
                        raw_statement=s,
                    )
                )
                continue

            # 4. CommonJS const { a, b } = require('./mod')
            m_req_destruct = re.search(r"(?:const|let|var)\s*\{([^}]+)\}\s*=\s*require\(['\"]([^'\"]+)['\"]\)", s)
            if m_req_destruct:
                mod = m_req_destruct.group(2)
                is_rel = mod.startswith(".")
                for item in m_req_destruct.group(1).split(","):
                    item = item.strip()
                    if not item:
                        continue
                    parts = re.split(r"\s*:\s*", item)
                    name = parts[0].strip()
                    alias = parts[1].strip() if len(parts) > 1 else None
                    imports.append(
                        ImportedSymbol(
                            name=name,
                            module=mod,
                            alias=alias,
                            is_relative=is_rel,
                            line=idx,
                            raw_statement=s,
                        )
                    )
                continue

            # 5. CommonJS const X = require('./mod')
            m_req = re.search(r"(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*require\(['\"]([^'\"]+)['\"]\)", s)
            if m_req:
                name = m_req.group(1)
                mod = m_req.group(2)
                imports.append(
                    ImportedSymbol(
                        name=name,
                        module=mod,
                        alias=None,
                        is_relative=mod.startswith("."),
                        line=idx,
                        raw_statement=s,
                    )
                )
                continue

        return imports

    def _parse_generic_imports(self, content: str) -> List[ImportedSymbol]:
        """Generic fallback extractor for Java / Go / Rust imports."""
        imports: List[ImportedSymbol] = []
        for idx, line in enumerate(content.splitlines(), start=1):
            s = line.strip()
            # Java: import java.util.List;
            if s.startswith("import "):
                clean = s.rstrip(";").replace("import ", "").strip()
                imports.append(
                    ImportedSymbol(
                        name=clean.split(".")[-1],
                        module=clean,
                        line=idx,
                        raw_statement=s,
                    )
                )
        return imports

    def _resolve_local_path(
        self,
        imp: ImportedSymbol,
        current_file: str,
        language: str,
        known_files: Set[str],
    ) -> Optional[str]:
        """Resolve an import statement to a relative file path in the known workspace."""
        current_norm = current_file.replace("\\", "/")
        file_dir = os.path.dirname(current_norm)

        candidates: List[str] = []

        if language == "Python":
            # Relative import: .models -> same dir/models.py
            if imp.is_relative:
                # Count level
                level = imp.level
                base_dir = file_dir
                for _ in range(max(0, level - 1)):
                    base_dir = os.path.dirname(base_dir)

                sub_path = imp.module.lstrip(".")
                rel_base = f"{base_dir}/{sub_path}".strip("/").replace("//", "/")
                candidates.extend([
                    f"{rel_base}.py",
                    f"{rel_base}/__init__.py",
                ])
            else:
                # Absolute python import e.g. "app.models" or "backend.scanner.symbols"
                mod_path = imp.module.replace(".", "/")
                candidates.extend([
                    f"{mod_path}.py",
                    f"{mod_path}/__init__.py",
                ])

        elif language in ("TypeScript", "JavaScript"):
            if imp.is_relative:
                clean_mod = imp.module.replace("\\", "/")
                joined = os.path.normpath(os.path.join(file_dir, clean_mod)).replace("\\", "/")
                candidates.extend([
                    f"{joined}.ts",
                    f"{joined}.tsx",
                    f"{joined}.js",
                    f"{joined}.jsx",
                    f"{joined}/index.ts",
                    f"{joined}/index.tsx",
                    f"{joined}/index.js",
                ])

        # Test candidates against known files
        for cand in candidates:
            cand_norm = os.path.normpath(cand).replace("\\", "/")
            if cand_norm in known_files:
                return cand_norm
            # Suffix match
            for k in known_files:
                if k == cand_norm or k.endswith("/" + cand_norm):
                    return k

        return None

    def track_repository_imports(
        self,
        files: Sequence[FileInfo],
        file_contents: Mapping[str, str],
    ) -> Dict[str, FileImportMap]:
        """Index imports and build an import map across all repository files."""
        known_paths = [f.path.replace("\\", "/") for f in files]
        maps: Dict[str, FileImportMap] = {}

        for f in files:
            content = file_contents.get(f.path, "")
            im_map = self.parse_imports(f, content, known_files=known_paths)
            maps[f.path.replace("\\", "/")] = im_map

        return maps

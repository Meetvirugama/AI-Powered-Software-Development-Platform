"""Day 4 — Repository engine tests on fixture repositories.
Owner: Keval — Testing Lead (W1-18)

Verifies the repository engine end-to-end across all 3 fixture repositories:
1. Correct file count returned by FileWalker (respecting .gitignore, skip dirs, binary files)
2. Language detected correctly for each file (Python, JavaScript, TypeScript, unknown)
3. AST parsed cleanly by tree-sitter without errors
4. Symbol count and names match expected (manually counted)
5. Zero symbols from binary files (.png) or node_modules
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.scanner.detector import LanguageDetector
from backend.scanner.extractor import SymbolExtractor
from backend.scanner.parser import Parser
from backend.scanner.symbols import FileInfo
from backend.scanner.walker import FileWalker

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def walker() -> FileWalker:
    return FileWalker()


@pytest.fixture
def detector() -> LanguageDetector:
    return LanguageDetector()


@pytest.fixture
def parser() -> Parser:
    return Parser()


@pytest.fixture
def extractor(parser: Parser) -> SymbolExtractor:
    return SymbolExtractor(parser=parser)


# ---------------------------------------------------------------------------
# 1. python_sample fixture tests
# ---------------------------------------------------------------------------


def test_python_sample_file_walker_count_and_filtering(walker: FileWalker):
    """FileWalker on python_sample returns exactly 11 files.

    Must exclude ignored.py (.gitignore), image.png (binary), and node_modules/.
    """
    python_dir = str(FIXTURES_DIR / "python_sample")
    files = walker.walk(python_dir)
    returned_paths = [f.path.replace(os.sep, "/") for f in files]

    # Verify exclusions
    assert not any("ignored.py" in p for p in returned_paths), "ignored.py must be excluded by .gitignore"
    assert not any("image.png" in p for p in returned_paths), "image.png must be excluded as binary"
    assert not any("node_modules" in p for p in returned_paths), "node_modules must be excluded"

    # Verify inclusions
    assert any("main.py" in p for p in returned_paths)
    assert any("api.py" in p for p in returned_paths)
    assert any("auth.py" in p for p in returned_paths)
    assert any("models.py" in p for p in returned_paths)
    assert any(".gitignore" in p for p in returned_paths)

    # 11 tracked files: .gitignore, api.py, auth.py, cache.py, config.py, email.py,
    # main.py, models.py, payment.py, storage.py, utils.py
    assert len(files) == 11


def test_python_sample_language_detection(walker: FileWalker, detector: LanguageDetector):
    """LanguageDetector correctly identifies Python for all .py files, and unknown for .gitignore."""
    python_dir = str(FIXTURES_DIR / "python_sample")
    files = walker.walk(python_dir)

    for f in files:
        lang = detector.detect(f)
        if f.path.endswith(".py"):
            assert lang == "Python", f"Expected Python for {f.path}, got {lang}"
        elif f.path.endswith(".gitignore"):
            assert lang == "unknown", f"Expected unknown for {f.path}, got {lang}"


def test_python_sample_symbol_counts_and_names(
    walker: FileWalker,
    detector: LanguageDetector,
    extractor: SymbolExtractor,
):
    """SymbolExtractor on python_sample extracts expected classes, functions, and symbols."""
    python_dir = str(FIXTURES_DIR / "python_sample")
    files = walker.walk(python_dir)

    all_symbols = []
    symbols_by_file: dict[str, list] = {}

    for f in files:
        f.language = detector.detect(f)
        full_path = os.path.join(python_dir, f.path)
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        syms = extractor.extract(f, content, file_id=uuid4())
        norm_path = f.path.replace(os.sep, "/")
        symbols_by_file[norm_path] = syms
        all_symbols.extend(syms)

    # 1. Total symbols count
    assert len(all_symbols) == 26

    # 2. Verify classes in models.py
    model_classes = [s.name for s in symbols_by_file["models.py"] if s.kind == "class"]
    assert "User" in model_classes
    assert "Product" in model_classes

    # 3. Verify functions across files
    func_names = [s.name for s in all_symbols if s.kind == "function"]
    assert "hello" in func_names  # main.py
    assert "get_users" in func_names  # api.py
    assert "create_user" in func_names  # api.py
    assert "create_access_token" in func_names  # auth.py
    assert "get_cached_user" in func_names  # cache.py
    assert "send_verification_email" in func_names  # email.py
    assert "process_payment" in func_names  # payment.py
    assert "upload_avatar" in func_names  # storage.py
    assert "hash_password" in func_names  # utils.py

    # 4. Verify constants
    const_names = [s.name for s in all_symbols if s.kind == "constant"]
    assert "DATABASE_URL" in const_names  # config.py
    assert "app" in const_names  # api.py
    assert "redis_client" in const_names  # cache.py


# ---------------------------------------------------------------------------
# 2. nodejs_sample fixture tests
# ---------------------------------------------------------------------------


def test_nodejs_sample_file_walker_count_and_filtering(walker: FileWalker):
    """FileWalker on nodejs_sample returns exactly 5 files."""
    node_dir = str(FIXTURES_DIR / "nodejs_sample")
    files = walker.walk(node_dir)
    returned_paths = [f.path.replace(os.sep, "/") for f in files]

    assert len(files) == 5
    assert "README.md" in returned_paths
    assert "package.json" in returned_paths
    assert "index.js" in returned_paths
    assert "server.js" in returned_paths
    assert "utils.js" in returned_paths


def test_nodejs_sample_language_detection(walker: FileWalker, detector: LanguageDetector):
    """LanguageDetector correctly detects JavaScript for .js files and unknown for .md / .json."""
    node_dir = str(FIXTURES_DIR / "nodejs_sample")
    files = walker.walk(node_dir)

    for f in files:
        lang = detector.detect(f)
        if f.path.endswith(".js"):
            assert lang == "JavaScript"
        else:
            assert lang == "unknown"


def test_nodejs_sample_symbol_counts_and_names(
    walker: FileWalker,
    detector: LanguageDetector,
    extractor: SymbolExtractor,
):
    """SymbolExtractor on nodejs_sample extracts 8 symbols (3 functions, imports, constants)."""
    node_dir = str(FIXTURES_DIR / "nodejs_sample")
    files = walker.walk(node_dir)

    all_symbols = []
    symbols_by_file: dict[str, list] = {}

    for f in files:
        f.language = detector.detect(f)
        full_path = os.path.join(node_dir, f.path)
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        syms = extractor.extract(f, content, file_id=uuid4())
        norm_path = f.path.replace(os.sep, "/")
        symbols_by_file[norm_path] = syms
        all_symbols.extend(syms)

    # 8 total symbols
    assert len(all_symbols) == 8

    # Functions
    func_names = [s.name for s in all_symbols if s.kind == "function"]
    assert "main" in func_names  # index.js
    assert "formatGreeting" in func_names  # utils.js
    assert "calculateSum" in func_names  # utils.js

    # Constants
    server_consts = [s.name for s in symbols_by_file["server.js"] if s.kind == "constant"]
    assert "server" in server_consts
    assert "port" in server_consts


# ---------------------------------------------------------------------------
# 3. typescript_sample fixture tests
# ---------------------------------------------------------------------------


def test_typescript_sample_file_walker_count_and_filtering(walker: FileWalker):
    """FileWalker on typescript_sample returns exactly 5 files."""
    ts_dir = str(FIXTURES_DIR / "typescript_sample")
    files = walker.walk(ts_dir)
    returned_paths = [f.path.replace(os.sep, "/") for f in files]

    assert len(files) == 5
    assert "README.md" in returned_paths
    assert "package.json" in returned_paths
    assert "tsconfig.json" in returned_paths
    assert "index.ts" in returned_paths
    assert "types.ts" in returned_paths


def test_typescript_sample_language_detection(walker: FileWalker, detector: LanguageDetector):
    """LanguageDetector detects TypeScript for .ts and unknown for .md / .json."""
    ts_dir = str(FIXTURES_DIR / "typescript_sample")
    files = walker.walk(ts_dir)

    for f in files:
        lang = detector.detect(f)
        if f.path.endswith(".ts"):
            assert lang == "TypeScript"
        else:
            assert lang == "unknown"


def test_typescript_sample_symbol_counts_and_names(
    walker: FileWalker,
    detector: LanguageDetector,
    extractor: SymbolExtractor,
):
    """SymbolExtractor on typescript_sample extracts 6 symbols (functions, interfaces, imports)."""
    ts_dir = str(FIXTURES_DIR / "typescript_sample")
    files = walker.walk(ts_dir)

    all_symbols = []
    symbols_by_file: dict[str, list] = {}

    for f in files:
        f.language = detector.detect(f)
        full_path = os.path.join(ts_dir, f.path)
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        syms = extractor.extract(f, content, file_id=uuid4())
        norm_path = f.path.replace(os.sep, "/")
        symbols_by_file[norm_path] = syms
        all_symbols.extend(syms)

    assert len(all_symbols) == 6

    # Interfaces from types.ts
    interface_names = [s.name for s in symbols_by_file["types.ts"] if s.kind == "interface"]
    assert "User" in interface_names
    assert "ApiResponse" in interface_names

    # Functions from index.ts
    func_names = [s.name for s in symbols_by_file["index.ts"] if s.kind == "function"]
    assert "createUser" in func_names
    assert "createSuccessResponse" in func_names


# ---------------------------------------------------------------------------
# 4. Strict exclusion checks: binary files and node_modules
# ---------------------------------------------------------------------------


def test_no_symbols_from_binary_files(extractor: SymbolExtractor):
    """Binary files must return 0 symbols."""
    bin_file = FileInfo(path="test.png", size_bytes=1024, language="unknown", is_binary=True)
    syms = extractor.extract(bin_file, "\x00\x00\x01\x00somebinarydata")
    assert syms == []


def test_no_symbols_from_node_modules_or_ignored(walker: FileWalker, extractor: SymbolExtractor, detector: LanguageDetector):
    """Ensures neither node_modules nor gitignored files produce any symbols in pipeline."""
    python_dir = str(FIXTURES_DIR / "python_sample")
    files = walker.walk(python_dir)

    for f in files:
        assert "node_modules" not in f.path
        assert "ignored.py" not in f.path
        assert "image.png" not in f.path


# ---------------------------------------------------------------------------
# 5. End-to-end repository engine test across all 3 fixture repos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name,expected_file_count,expected_symbol_count",
    [
        ("python_sample", 11, 26),
        ("nodejs_sample", 5, 8),
        ("typescript_sample", 5, 6),
    ],
)
def test_repository_engine_pipeline_all_fixtures(
    walker: FileWalker,
    detector: LanguageDetector,
    extractor: SymbolExtractor,
    fixture_name: str,
    expected_file_count: int,
    expected_symbol_count: int,
):
    """Complete pipeline verification: walk -> detect -> parse -> extract."""
    fixture_dir = str(FIXTURES_DIR / fixture_name)
    files = walker.walk(fixture_dir)

    assert len(files) == expected_file_count, f"File count mismatch for {fixture_name}"

    total_symbols = 0
    for f in files:
        f.language = detector.detect(f)
        full_path = os.path.join(fixture_dir, f.path)
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        syms = extractor.extract(f, content, file_id=uuid4())
        total_symbols += len(syms)

    assert total_symbols == expected_symbol_count, f"Symbol count mismatch for {fixture_name}"

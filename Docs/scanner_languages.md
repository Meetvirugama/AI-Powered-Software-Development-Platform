# Scanner Architecture & Supported Languages Specification

**Owner:** Prit — Repository Engine Lead  
**Task:** W2-07 — AST Symbol Range Resolution & Import Tracking  
**Milestone:** Week 2 — Developer Intelligence Suite Foundation  

---

## 1. Executive Summary

The **Repository Scanner** (`backend/scanner/`) is the foundational syntax analysis and code-intelligence layer of the platform. It is responsible for parsing raw source code into concrete syntax trees (ASTs), extracting structural code symbols (classes, functions, methods, interfaces, imports, constants), mapping exact 1-indexed source line ranges, tracking import dependencies, and mapping test-to-source relationships.

During Week 2, the scanner is extended with:
1. **Source Location Resolution (`SourceLocationResolver`)**: Accurate 1-indexed inclusive line range mapping and enclosing scope detection for downstream Developer Intelligence features (Code Explanation, Bug Detection, Test Generation, and AI Code Review).
2. **Import Tracking & Mapping (`ImportTracker`)**: Deep import analysis across Python, TypeScript, and JavaScript, categorizing dependencies into standard library, third-party packages, and resolved local workspace files.
3. **Explicit Error Handling & Status Tracking (`ParseResult`, `ResolutionResult`)**: Bounded, non-crashing parsing that handles syntax errors and malformed files gracefully without failing repository scans.

---

## 2. Supported Languages Matrix

The platform integrates tree-sitter grammars with Python standard library `ast` fallbacks to ensure deterministic, zero-crash parsing across diverse environments:

| Language | Primary Parser Engine | Fallback Engine | Symbol Types Extracted | Line Range Fidelity | Status |
|---|---|---|---|---|---|
| **Python** | `tree-sitter-python` (v0.25+) | Python standard library `ast` | Class, Function, Method, Import, Constant | Exact (1-indexed inclusive) | 🟢 Production Ready |
| **TypeScript** | `tree-sitter-typescript` (v0.23+) | RegEx / Heuristic Tokenizer | Class, Function, Method, Interface, Import, Constant | Exact (1-indexed inclusive) | 🟢 Production Ready |
| **JavaScript** | `tree-sitter-javascript` (v0.25+) | RegEx / Heuristic Tokenizer | Class, Function, Method, Import, Constant | Exact (1-indexed inclusive) | 🟢 Production Ready |
| **Java** | `tree_sitter_languages` (`java`) | Generic Import / Structural Extractor | Class, Interface, Method, Import | Exact (1-indexed inclusive) | 🟡 Supported |
| **Go** | `tree_sitter_languages` (`go`) | Generic Import / Structural Extractor | Function, Method, Struct/Type, Import | Exact (1-indexed inclusive) | 🟡 Supported |
| **Rust** | `tree_sitter_languages` (`rust`) | Generic Import / Structural Extractor | Struct, Impl, Function, Import | Exact (1-indexed inclusive) | 🟡 Supported |
| **C** | `tree_sitter_languages` (`c`) | Generic Import / Structural Extractor | Function, Struct, Macro/Constant | Exact (1-indexed inclusive) | 🟡 Supported |
| **C++** | `tree_sitter_languages` (`cpp`) | Generic Import / Structural Extractor | Class, Struct, Function, Method, Include | Exact (1-indexed inclusive) | 🟡 Supported |

---

## 3. AST Symbol Schema and Line Range Semantics

### 3.1 Symbol Data Model

The published symbol contract consumed by indexing (`backend/indexer/chunker.py`) and developer intelligence context (`backend/ai/context/builder.py`):

```python
@dataclass
class Symbol:
    id: UUID
    name: str              # Identifier name (e.g. "calculate_tax", "AccountManager")
    kind: str              # "class" | "function" | "method" | "import" | "constant" | "interface"
    file_id: UUID          # Foreign key to repository_files
    start_line: int        # 1-indexed starting line
    end_line: int          # 1-indexed ending line (inclusive)
    signature: str         # First declaration line / signature
    parent_id: UUID | None # Enclosing container ID (e.g. class ID for a method)
```

### 3.2 Line Number Invariants

1. **1-Indexed Inclusive Bounds**:
   - `start_line >= 1`
   - `end_line >= start_line`
   - `start_line` corresponds to the first line of the declaration or signature.
   - `end_line` encompasses the full body of the function, class, or method, including closing brackets/indented blocks.
2. **Container Hierarchy**:
   - For a method `m` inside class `c`: `c.start_line <= m.start_line <= m.end_line <= c.end_line` holds strictly.
   - `m.parent_id == c.id`.

---

## 4. Source Location Utilities (`SourceLocationResolver`)

`backend/scanner/source_location.py` provides high-level target resolution for Week 2 Developer Intelligence services:

### 4.1 Target Resolution Capabilities

- **`resolve_symbol_range(symbols, symbol_name, file_content, file_path)`**:
  - Resolves simple symbol names (e.g. `"calculate_tax"`) or qualified names (e.g. `"AccountManager.update_role"`).
  - Returns `SourceRange` containing exact `start_line`, `end_line`, and extracted `content`.
- **`find_enclosing_symbol(symbols, line)`**:
  - Locates the tightest enclosing scope for any line number.
  - Inside a nested method, returns the method rather than the enclosing class.
- **`find_enclosing_scope(symbols, line)`**:
  - Returns the full scope hierarchy from outermost container (`class`) to innermost callable (`method`).
- **`extract_snippet(content, start_line, end_line)`**:
  - Safely extracts source text lines with boundary clamping, guarding against index out-of-range errors on EOF.
- **`resolve_target(file_path, content, ...)`**:
  - Universal target resolver producing a typed `ResolutionResult`.
  - Supports resolution via explicit `symbol_name`, line ranges (`start_line`, `end_line`), or point-in-file cursor lines.

### 4.2 Target Selection & Disambiguation Engine (`TargetSelector`)

`backend/scanner/target_selector.py` integrates AST utilities into user-facing target selection:
- **`select_target(file_path, content, target_type, symbol_name, start_line, end_line, cursor_line, language)`**:
  - Resolves `'file'`, `'symbol'`, and `'range'` targets into a verified `TargetSelectionResult`.
  - Resolves functions, classes, and member methods to exact line bounds.
  - Generates `child_symbols` for classes and `enclosing_symbol` for methods.
- **Ambiguous Symbol Disambiguation**:
  - Detects duplicate symbol names across different scopes (`is_ambiguous=True`).
  - Disambiguates using qualified names (`Class.method`), cursor line proximity, or scope hierarchy defaults.
  - Attaches an informative `ambiguity_note` and full candidate list for transparency.
- **Direct Bridge to Developer Intelligence**:
  - `result.to_target_snippet(language)` produces a `TargetSnippet` directly consumed by Meet's `IntelligenceContext` and Dev's `CodeExplanationService`.

---

## 5. Import Tracking & Mapping (`ImportTracker`)

`backend/scanner/import_tracker.py` extracts and categorizes all external and local dependencies:

### 5.1 Python Import Tracking

- **Forms Supported**:
  - `import os, sys`
  - `import numpy as np` (with alias tracking)
  - `from typing import List, Dict`
  - `from .models import User` (relative same-directory import, `level=1`)
  - `from ..core.config import get_settings` (relative parent-directory import, `level=2`)
- **Categorization**:
  - **Standard Library**: Checked against Python's built-in standard library set (`os`, `sys`, `json`, `pathlib`, `typing`, etc.).
  - **Third-Party**: External PyPI packages (`fastapi`, `pydantic`, `sqlalchemy`, etc.).
  - **Local Workspace**: Resolved to repository file paths (`models.py`, `backend/app/core/config.py`).

### 5.2 TypeScript & JavaScript Import Tracking

- **Forms Supported**:
  - ES6 Named: `import { UserProfile, validateProfile } from './types'`
  - ES6 Default: `import express from 'express'`
  - ES6 Namespace: `import * as React from 'react'`
  - CommonJS: `const path = require('path')`, `const { Helper } = require('./helper')`
- **Resolution**:
  - Relative module paths (`./`, `../`) are automatically matched against workspace file candidate extensions (`.ts`, `.tsx`, `.js`, `.jsx`, `/index.ts`, `/index.js`).

---

## 6. Unsupported Syntax and Known Limitations

To guarantee predictable behavior across edge cases, the scanner defines strict boundaries for unsupported syntax:

### 6.1 Unsupported Syntax Patterns

| Pattern / Syntax | Behavior / Outcome | Mitigation / Handling |
|---|---|---|
| **Dynamic `eval()` / `exec()`** | Dynamically created functions/classes are not extracted into static symbol tables. | Static symbols before and after are preserved. |
| **Computed `require()` in JS** | Dynamic paths such as `require(computePath())` cannot be resolved to a static local file. | Marked as `is_relative=False` without crashing. |
| **Complex C/C++ Macros** | Heavy macro-metaprogramming generating synthetic declarations may not yield named function nodes. | Outer function headers are parsed; macros are extracted as constants where recognized. |
| **Jinja2 / Template Interpolation** | Files with embedded template tags (`{% if %}`) in non-HTML/markup files produce syntax errors in strict AST parsers. | Treated with error-resilient parsing; valid surrounding blocks are parsed. |
| **Minified / Bundle Files** | Single-line files > 1MB. | Excluded by `FileWalker` size limit (max 1MB) and binary heuristics. |

### 6.2 Explicit Result Contract for Unsupported Code

When an unsupported language or unparseable input is provided:
- **Never raises an unhandled exception**: All parser and extractor exceptions are caught and logged.
- **Explicit `is_supported=False`**: `Parser.parse_with_status` and `SourceLocationResolver.resolve_target` explicitly set `is_supported=False` and supply an informative `error_code` (`UNSUPPORTED_LANGUAGE`).
- **Syntax Error Detection**: Files containing partial syntax errors (e.g. unclosed blocks) are flagged with `has_syntax_errors=True` while extracting all cleanly formed symbols surrounding the defect.

---

## 7. AST Rule Integration & Structural Bug Analysis (`ASTBugAnalyzer`)

**Owner:** Prit — Repository Engine Lead  
**Task:** W2-Day3 — AST Rule Integration  
**Milestone:** Week 2 — Dedicated Bug Detection Foundation  

`backend/scanner/ast_rules.py` provides high-precision structural defect detection directly on syntax trees without requiring external dependencies or executing untrusted code:

### 7.1 Built-in Rule Catalog

| Rule ID | Category | Severity | Target Pattern | Suggested Remediation |
|---|---|---|---|---|
| **`AST-RES-001`** | `resource_leak` | High | `open()` or `socket()` assigned without a `with` context manager | Wrap allocation in `with open(...) as ...:` or close in `finally`. |
| **`AST-EXC-001`** | `unhandled_exception` | High / Med | Bare `except:` or `except Exception:` swallowed with `pass` / empty body | Specify explicit exception classes and log or re-raise errors. |
| **`AST-ARG-001`** | `logic_error` | Medium | Mutable default argument (`items=[]`, `config={}`) in function signatures | Default to `None` and initialize the container inside the function body. |
| **`AST-NULL-001`** | `null_dereference` | Crit / Low | PEP 8 equality check `== None` or accessing `.attr` inside `if x is None:` block | Use `is None` / `is not None` and guard dereferences. |
| **`AST-ITER-001`** | `off_by_one` | High | Mutating a collection (`.remove()`, `.append()`, `del`) while actively iterating over it | Iterate over a copy (`list(items)`) or use list comprehensions. |
| **`AST-LOGIC-001`** | `logic_error` | Medium | Structurally identical if/else branches or duplicate elif condition checks | Provide distinct branch logic or eliminate redundant condition checks. |
| **`AST-DEAD-001`** | `logic_error` | Low | Unreachable code statements following unconditional `return`, `raise`, `break`, or `continue` | Remove or relocate dead statements. |
| **`AST-SEC-001`** | `security` | Critical | Dynamic execution via `eval()`, `exec()`, or `__import__()` | Replace with safe parsers like `ast.literal_eval()` or structured validation. |
| **`AST-LOGIC-002`** | `logic_error` | Medium / Low | Redundant self-assignment (`x = x`) or tautological comparison (`x == x`) | Remove self-assignment or correct comparator variable name. |
| **`AST-BOUND-001`** | `off_by_one` | High | Directly indexing an array with `items[len(items)]` causing `IndexError` | Use `items[-1]` for the last element or `range(len(items))`. |
| **`AST-SYNTAX-ERROR`** | `syntax_error` | Critical | Malformed syntax caught during parsing (exact line and column preserved) | Fix syntax error so the file can be cleanly parsed. |

### 7.2 Multi-Language Tree-sitter Checking

In addition to Python standard library AST traversal, `ASTBugAnalyzer` evaluates Tree-sitter concrete syntax trees for JavaScript and TypeScript:
- **`eval()` Detection**: Identifies call expressions targeting `eval()` in `.js` and `.ts` files.
- **Empty Catch Blocks**: Identifies catch clauses with 0 statement children that swallow exceptions without handling or logging.

### 7.3 Integration with Static Analysis and API Pipelines

- **Devu's Static Findings Pipeline**: `analyzer.to_static_findings(findings)` maps `ASTBugFinding` into normalized `StaticFinding` dictionaries (`scanner="ast_rules"`), allowing Devu's `StaticReviewer` to merge AST and linter findings without schema friction.
- **Target Range Scoping**: When a user selects a symbol or range in Dhramraj's UI, `analyze_code(content, target_symbol="my_func")` filters findings to the exact target boundaries `[start_line, end_line]`.
- **Zero-Crash & Path Traversal Guards**: Parsing failures return structured results with `parse_status="SYNTAX_WARNING"` or `"PARSE_ERROR"`. `analyze_file` strictly validates repository root boundaries, blocking path traversal attempts.

---

## 8. Framework and Convention Detector (`FrameworkDetector`)

**Owner:** Prit — Repository Engine Lead  
**Task:** W2-Day4 — Framework and Convention Detector  
**Milestone:** Week 2 — Framework-Aware Test Generation Foundation  

`backend/scanner/framework_detector.py` provides repository test runner introspection, convention discovery, fixture extraction, and test path generation:

### 8.1 Supported Frameworks

| Framework | Language | Primary Manifests & Indicators | Configured Command | Status |
|---|---|---|---|---|
| **`pytest`** | Python | `pytest.ini`, `pyproject.toml` (`[tool.pytest]`), `setup.cfg`, `requirements.txt` | `pytest` | 🟢 Supported |
| **`unittest`** | Python | Standard library fallback, `unittest.TestCase` in test files | `python -m unittest` | 🟢 Supported |
| **`jest`** | TypeScript / JavaScript | `package.json` (`scripts.test`, `devDependencies`), `jest.config.*` | `npm test` | 🟢 Supported |
| **`vitest`** | TypeScript / JavaScript | `package.json` (`vitest` in dependencies), `vitest.config.*` | `vitest run` | 🟡 Detected (Unsupported) |
| **`mocha`** | JavaScript | `package.json` (`mocha` in dependencies), `.mocharc.*` | `mocha` | 🟡 Detected (Unsupported) |
| **`go test`** | Go | `go.mod`, `*_test.go` | `go test ./...` | 🟡 Detected (Unsupported) |
| **`junit`** | Java | `pom.xml`, `build.gradle` | `mvn test` | 🟡 Detected (Unsupported) |

### 8.2 Convention and Fixture Introspection

- **Test Directory Resolution**: Auto-detects configured `testpaths` from `pytest.ini` or discovers directories in order: `backend/tests`, `tests`, `test`, `__tests__`, `src/__tests__`.
- **Naming Pattern Recognition**: Identifies whether the project follows `prefix:test_` (standard Python), `suffix:_test`, or `suffix:.test.ts` / `suffix:.spec.ts` (TypeScript/JavaScript).
- **AST Fixture Extraction**: Automatically parses `conftest.py` files using Python AST to identify all `@pytest.fixture` functions, extracting fixture names, line numbers, scopes (`function`, `module`, `session`), `autouse` flags, and docstrings.
- **Test Path Proposal (`propose_test_path`)**: Computes the matching test path for any source file (e.g. `backend/scanner/parser.py` -> `backend/tests/scanner/test_parser.py`, `src/components/Button.tsx` -> `src/components/__tests__/Button.test.tsx`).
- **Ambiguity & Conflict Handling**: When multiple runners exist (e.g. `jest` and `vitest` in `package.json`), sets `is_ambiguous=True`, `status="AMBIGUOUS"`, and provides full candidate list and explanation.

---

## 9. Review Source Mapping (`ReviewSourceMapper`)

**Owner:** Prit — Repository Engine Lead  
**Task:** W2-Day5 — Review Source Mapping  
**Milestone:** Week 2 — Standalone AI Code Review Foundation  

`backend/scanner/source_mapper.py` implements the review source mapping engine that bridges raw git diffs, commits, and patches with AST-level semantic understanding for the Standalone AI Code Review suite (`backend/ai/review/`).

### 9.1 Core Architectural Responsibilities

1. **Diff Parsing & Hunk Extraction**:
   - Parses unified git diffs (`diff --git`, `--- a/file`, `+++ b/file`, `@@ -old_start,old_count +new_start,new_count @@`).
   - Tracks modified, added, deleted, and renamed files while preserving old and new paths.
   - Extracts modified/added line numbers per hunk using standard 1-indexed line math.
   - Integrates with commit changes (e.g. Parth's `CommitFileChange` dictionaries with `filename`, `patch`, and `status`).

2. **AST Symbol Resolution**:
   - Maps changed lines to enclosing functions, methods, classes, and scopes.
   - Computes tightest enclosing symbol (`enclosing_symbol`), scope hierarchy (`enclosing_scopes`), and qualified name (e.g. `AccountManager.update_role`).
   - Extracts child and sibling symbols intersecting the hunk range.
   - Generates typed `SymbolSummary` records with 1-indexed inclusive bounds (`start_line`, `end_line`), `kind`, and declaration `signature`.

3. **Structural AST Context & Bug Rule Scoping**:
   - Generates `HunkASTContext` containing detected syntactic node types, scope hierarchy, and syntax validation status.
   - Evaluates Prit's `ASTBugAnalyzer` structural rules against the file content, strictly scoping findings to the changed line ranges `[start_line, end_line]`.
   - Enables the code review engine to identify immediate AST-level defects (e.g. resource leaks, bare exceptions, mutable defaults) introduced in the diff before running LLM evaluation.

4. **Preservation of File and Revision Identity**:
   - Preserves 1-indexed inclusive line bounds across all hunks and symbol summaries.
   - Preserves file identity through additions, modifications, renames, and deletions.
   - Carries git revision metadata (`base_revision`, `head_revision`, `commit_sha`) through the mapping lifecycle.
   - Provides seamless conversion to downstream contracts:
     - `to_source_references()`: Generates `AnalysisSourceReference` objects for Dev's review findings pipeline.
     - `to_modified_files()`: Generates Meet's `ModifiedFile` dataclass objects with `file_path`, `change_type`, and `modified_line_ranges`.

5. **Explicit Mapping Limitation Reporting**:
   - When precision cannot be achieved, the mapper reports explicit `MappingLimitation` records rather than failing, hallucinating lines, or silently skipping files.
   - **Supported Limitation Categories**:
     - `UNSUPPORTED_LANGUAGE`: File format does not have an active AST parser (e.g. Markdown, YAML, Shell).
     - `MODULE_LEVEL_CODE`: Changed lines reside at top-level module scope outside any function or class declaration.
     - `DELETED_FILE`: Target file was removed in the diff; AST parsing cannot be performed on the new revision.
     - `BINARY_FILE`: Binary asset modified; AST parsing is bypassed.
     - `LINE_OUT_OF_BOUNDS`: Hunk line numbers exceed the total lines in the provided source file.
     - `SYNTAX_ERROR`: File has fatal syntax errors preventing full symbol resolution (reports exact syntax error location).

### 9.2 Data Contracts

```python
@dataclass
class SymbolSummary:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str = ""
    qualified_name: str = ""

@dataclass
class HunkASTContext:
    node_types: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    syntax_valid: bool = True
    structural_bug_findings: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

@dataclass
class MappingLimitation:
    limitation_type: str  # "UNSUPPORTED_LANGUAGE" | "MODULE_LEVEL_CODE" | "DELETED_FILE" | ...
    file_path: str
    hunk_index: int | None = None
    line_number: int | None = None
    reason: str = ""

@dataclass
class HunkMapping:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    modified_line_ranges: list[tuple[int, int]]
    added_lines: list[int]
    enclosing_symbol: SymbolSummary | None = None
    enclosing_scopes: list[str] = field(default_factory=list)
    intersecting_symbols: list[SymbolSummary] = field(default_factory=list)
    ast_context: HunkASTContext | None = None
    limitations: list[MappingLimitation] = field(default_factory=list)
    hunk_text: str = ""

@dataclass
class FileSourceMapping:
    file_path: str
    old_path: str | None = None
    change_type: str = "modified"  # "modified" | "added" | "deleted" | "renamed"
    language: str = "unknown"
    is_supported: bool = True
    hunks: list[HunkMapping] = field(default_factory=list)
    all_symbols: list[SymbolSummary] = field(default_factory=list)
    limitations: list[MappingLimitation] = field(default_factory=list)
    revision: str | None = None

@dataclass
class ReviewSourceMapResult:
    files: list[FileSourceMapping] = field(default_factory=list)
    total_files: int = 0
    total_hunks: int = 0
    limitations: list[MappingLimitation] = field(default_factory=list)
    commit_sha: str | None = None
    base_revision: str | None = None
    head_revision: str | None = None
    success: bool = True
    error: str | None = None
```

---

## 10. Verification & Acceptance Gate

The AST, source location, rules, framework detector, and review source mapping foundation is verified by **111 automated tests** with 100% pass rate:
- `backend/tests/test_parser_reliability.py`: 24 unit and integration tests verifying multi-language source range fidelity across all sample fixtures, class/method extraction across Python, TypeScript, and JavaScript, framework detection and POSIX test path proposals, zero-crash resilience on malformed syntax and unsupported languages, empty file handling, and cross-component line indexing agreement. Published deliverable: `Docs/parser_and_framework_test_report.md`.
- `backend/tests/test_source_mapper.py`: 21 unit and integration tests verifying diff header parsing, hunk boundary math, symbol mapping (functions, classes, methods), multi-language AST context (Python, TypeScript), scoped AST defect rule evaluation, file additions, renames, deletions, boundary out-of-bounds, syntax error resilience, module-level limitation tracking, commit changes helper, dictionary serialization, and conversions to `AnalysisSourceReference` and `ModifiedFile`.
- `backend/tests/test_framework_detector.py`: 15 unit and integration tests verifying pytest options, conftest fixture AST extraction, unittest detection, Jest detection, Vitest/ambiguous handling, test path proposals, and dictionary serialization.
- `backend/tests/test_ast_rules.py`: 22 unit and integration tests verifying all 10 structural rules, clean fixture zero findings, syntax error resilience, symbol/range scoping, path traversal guards, and static findings adapters.
- `backend/tests/test_target_selector.py`: 14 tests verifying target selection across files, symbols, qualified methods, ambiguous names, and TargetSnippet conversion.
- `backend/tests/test_source_location.py`: 15 tests verifying exact range extraction, scope resolution, import tracking, and syntax error tolerance.
- `backend/tests/test_detector.py`, `backend/tests/test_test_mapper.py`, `backend/tests/test_walker.py`: Baseline scanner regression suites.




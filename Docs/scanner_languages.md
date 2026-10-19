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

## 7. Verification & Acceptance Gate

The AST and source location foundation is verified by automated test suites:
- `backend/tests/test_source_location.py`: 15 unit and integration tests verifying exact range extraction, scope resolution, import tracking, and syntax error tolerance.
- `backend/tests/test_repository_engine.py`: 14 end-to-end scanner tests verifying file counts, language detection, and symbol counts across all 3 standard fixtures (`python_sample`, `nodejs_sample`, `typescript_sample`).
- `backend/tests/test_detector.py` & `backend/tests/test_test_mapper.py`: Language detection and test mapping suites.

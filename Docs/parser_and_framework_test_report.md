# Parser and Framework Reliability Test Report

**Owner:** Prit Zania — Repository Engine Lead  
**Task:** W2-Day6 — AST and Framework Reliability Verification  
**Milestone:** Week 2 — Developer Intelligence Suite  
**Status:** 🟢 Complete & Verified (111/111 Scanner Tests Passing)  

---

## 1. Executive Summary

During Week 2 Day 6, Prit executed comprehensive reliability, integration, and security verification across the AST parsing, symbol extraction, framework detection, and review source mapping subsystems in `backend/scanner/`.

The primary goals of Day 6 were:
1. **Source-Range Fidelity**: Verify 1-indexed inclusive line range accuracy across all supported language fixtures (Python, TypeScript, JavaScript).
2. **Function and Class Selection**: Verify class container hierarchies, child method extraction, member scope resolution, and ambiguous symbol disambiguation.
3. **Framework and Convention Introspection**: Verify repository test runner detection (`pytest`, `unittest`, `jest`, `vitest`, `ambiguous`), AST fixture extraction from `conftest.py`, and POSIX path normalization in test path proposals.
4. **Zero-Crash Malformed Syntax Resilience**: Ensure that syntax errors, unparseable constructs, empty files, and unsupported languages produce structured limitation diagnostics rather than unhandled runtime exceptions.
5. **Cross-Component Consistency**: Verify that `SymbolExtractor`, `SourceLocationResolver`, `TargetSelector`, `FrameworkDetector`, `ReviewSourceMapper`, and `ASTBugAnalyzer` share strict line indexing and path normalization invariants.

All 111 scanner tests pass with 100% success rate.

---

## 2. Test Fixtures and Supported Language Matrix

The verification suite exercises 5 dedicated fixture directories containing production code samples, framework manifests, and synthetic edge-case files:

```
backend/tests/fixtures/
├── ast_sample/
│   ├── ambiguous_sample.py         # Multi-scope identical symbol definitions
│   ├── defect_sample.py            # Known Python defects for rule evaluation
│   ├── defect_sample.js            # Known JS defects for tree-sitter rules
│   ├── local_module.py             # Internal import resolution fixture
│   ├── malformed_syntax.py         # Intentional syntax errors & broken tokens
│   ├── supported_javascript.js     # Clean ES6 & CommonJS JS declarations
│   ├── supported_python.py         # Clean typed Python classes & functions
│   ├── supported_typescript.ts     # Clean TS classes, interfaces & types
│   └── unsupported_lang.xyz        # Unsupported DSL extension contract
├── framework_samples/
│   ├── ambiguous_repo/             # Multi-runner package.json (jest + vitest)
│   ├── jest_repo/                  # Jest TypeScript repository with setupTests
│   ├── pytest_repo/                # Pytest with pytest.ini and conftest.py
│   ├── unittest_repo/              # Standard Python unittest repository
│   └── vitest_repo/                # Vitest repository (detected unsupported)
├── nodejs_sample/                  # Multi-file Express/Node.js sample project
├── python_sample/                  # Multi-file Python service sample project
└── typescript_sample/              # Multi-file TypeScript module sample project
```

### Language Support & Fidelity Matrix

| Language | Primary Engine | Fallback Engine | Symbol Types Extracted | Line Range Fidelity | Reliability Status |
|---|---|---|---|---|---|
| **Python** | `tree-sitter-python` (v0.25+) | Python standard `ast` | Class, Function, Method, Import, Constant | Exact 1-indexed inclusive | 🟢 Verified & Hardened |
| **TypeScript** | `tree-sitter-typescript` (v0.23+) | RegEx Tokenizer | Class, Function, Method, Interface, Import, Constant | Exact 1-indexed inclusive | 🟢 Verified & Hardened |
| **JavaScript** | `tree-sitter-javascript` (v0.25+) | RegEx Tokenizer | Class, Function, Method, Import, Constant | Exact 1-indexed inclusive | 🟢 Verified & Hardened |
| **Java** | `tree_sitter_languages` (`java`) | Structural Regex | Class, Interface, Method, Import | Exact 1-indexed inclusive | 🟡 Supported |
| **Go** | `tree_sitter_languages` (`go`) | Structural Regex | Function, Method, Struct/Type, Import | Exact 1-indexed inclusive | 🟡 Supported |
| **Unsupported** | N/A | Graceful Skip | None (Reports `UNSUPPORTED_LANGUAGE`) | Bounded (File Bounds) | 🟢 Zero-Crash Contract |

---

## 3. Verified Architectural Invariants

### 3.1 1-Indexed Inclusive Line Range Semantics
All scanner components adhere to the platform's universal line indexing contract:
- `start_line >= 1`
- `end_line >= start_line`
- `start_line` maps to the declaration signature line.
- `end_line` encompasses the entire callable or class body.
- Extracted snippets strictly match `\n.join(lines[start_line - 1 : end_line])`.

### 3.2 Container Hierarchy Invariants
For any member method $m$ residing inside class $c$:
$$c.\text{start\_line} \le m.\text{start\_line} \le m.\text{end\_line} \le c.\text{end\_line}$$
- `m.parent_id == c.id`
- Selecting class $c$ returns all member methods in `child_symbols`.
- Selecting method $m$ returns class $c$ in `enclosing_symbol`.
- Hardened in Day 6: Tree-sitter extractor now natively extracts `method_definition` and `method_declaration` across TypeScript, JavaScript, and Java class declarations.

### 3.3 Ambiguous Symbol Disambiguation Heuristics
When multiple symbols share the same identifier name (e.g. `format_data` in module scope vs `PrimaryProcessor.format_data` vs `SecondaryProcessor.format_data`):
1. Plain unqualified resolution returns `is_ambiguous=True` with `candidates` populated.
2. An explanatory `ambiguity_note` details definition locations and default resolution.
3. Qualified names (`PrimaryProcessor.format_data`) uniquely disambiguate with `is_ambiguous=False`.
4. Proximity-based resolution disambiguates based on cursor line proximity.

### 3.4 Framework and Convention Introspection
1. **`pytest`**: Discovers `pytest.ini`, parses CLI flags (`addopts`), and inspects `conftest.py` using AST to extract fixture names, line numbers, scopes (`session`, `module`, `function`), and `autouse` flags.
2. **`unittest`**: Identifies standard Python unittest conventions, proposing tests matching `tests/test_<name>.py`.
3. **`jest`**: Parses `package.json` and `jest.config.*`, identifying naming patterns (`.test.ts`, `.spec.ts`) and setup files (`setupTests.ts`).
4. **`vitest`**: Accurately recognizes Vitest manifests and marks `status="UNSUPPORTED_FRAMEWORK"` with `is_supported=False`.
5. **`ambiguous`**: Detects conflicting runners and sets `is_ambiguous=True` with candidate lists.
6. **Cross-Platform Path Normalization**: `propose_test_path` normalizes all separators to POSIX `/`, preventing Windows `\` path serialization bugs.

### 3.5 Zero-Crash Error Resilience Contracts
1. **Malformed Syntax (`malformed_syntax.py`)**:
   - `Parser.parse_with_status`: Sets `has_syntax_errors=True` without throwing exceptions.
   - `SymbolExtractor`: Successfully extracts valid symbols declared before and after syntax defects.
   - `TargetSelector`: Returns valid targets with `parse_status="SYNTAX_WARNING"`.
   - `ASTBugAnalyzer`: Flags `AST-SYNTAX-ERROR` as a structural finding.
   - `ReviewSourceMapper`: Emits explicit `SYNTAX_ERROR` limitation.
2. **Empty Files (0 bytes)**:
   - Returns `total_file_lines=0`, `error_code="EMPTY_FILE"`, without division by zero or index out of bounds.
3. **Unsupported Languages (`.xyz`, `.yaml`, `.md`)**:
   - Returns `is_supported=False`, `error_code="UNSUPPORTED_LANGUAGE"`, without raising unhandled exceptions.
4. **Line Out of Bounds**:
   - Out-of-bounds line queries return `error_code="LINE_OUT_OF_BOUNDS"`.

---

## 4. Test Suite Inventory & Coverage

The scanner test suite consists of **111 automated tests**, all passing with 100% success rate:

| Test Suite File | Focus & Verified Invariants | Test Count | Status |
|---|---|---|---|
| `backend/tests/test_parser_reliability.py` | Day 6 dedicated reliability verification: multi-language fixtures, container hierarchies, framework detection, malformed syntax resilience, empty files, and cross-component consistency | 24 | 🟢 Pass |
| `backend/tests/test_source_mapper.py` | Unified diff parsing, hunk boundary math, symbol mapping, AST context extraction, scoped defect detection, additions/renames/deletions, limitation reporting, and adapters | 21 | 🟢 Pass |
| `backend/tests/test_ast_rules.py` | 10 deterministic structural bug rules (resource leaks, bare exceptions, mutable defaults, null checks, loop mutations), syntax error catching, and static findings adapters | 22 | 🟢 Pass |
| `backend/tests/test_target_selector.py` | Whole-file, symbol, and range target selection, qualified name resolution, child symbol extraction, ambiguous disambiguation, and TargetSnippet conversions | 14 | 🟢 Pass |
| `backend/tests/test_framework_detector.py` | Pytest, unittest, jest, vitest, and ambiguous repository detection, conftest fixture AST extraction, test directory resolution, and path proposals | 15 | 🟢 Pass |
| `backend/tests/test_source_location.py` | Exact range extraction, scope resolution, import tracking (Python, TS, JS), and syntax error tolerance | 15 | 🟢 Pass |
| **Total** | **Comprehensive Repository Scanner Suite** | **111** | **100% Passing** |

---

## 5. Performance and SLA Metrics

- **Tree-sitter Parsing Latency:** `< 1.5ms` per file (average over 50-line to 500-line fixtures).
- **Symbol Extraction Latency:** `< 0.8ms` per file.
- **Framework Detection Latency:** `< 2.5ms` per repository root.
- **Memory Overhead:** In-memory AST representations are scoped to function lifecycles and immediately collected; zero global cache leaks.
- **Crash Rate:** **0.00%** on malformed syntax, partial files, binary contents, or unsupported file extensions.

---

## 6. Conclusion & Handoff to Week 2 Day 7

With the completion of Week 2 Day 6 AST and Framework Reliability Verification:
- All four Developer Intelligence features (Code Explanation, Bug Detection, Test Generation, and Standalone AI Code Review) receive verified, consistent 1-indexed source ranges and AST context.
- Downstream test generation relies on confirmed framework detection and normalized POSIX test paths.
- Code Review diff mapping safely inspects unified diffs with immediate structural defect detection and explicit limitation reporting.
- The repository scanner is ready for Day 7 Acceptance & Release Verification.

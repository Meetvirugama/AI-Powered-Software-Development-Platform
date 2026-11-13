import logging
import re
from typing import Any
from uuid import UUID, uuid4

try:
    import tree_sitter
except ImportError:
    tree_sitter = None

from .parser import (
    Parser,
    StructuralCSTNode,
    _find_matching_brace_line,
    _sanitize_source_text,
)
from .symbols import FileInfo, Symbol

logger = logging.getLogger(__name__)


class SymbolExtractor:
    """Extracts code symbols (classes, functions, methods, imports, constants, interfaces)

    from tree-sitter concrete syntax trees or resilient AST/structural fallbacks across
    Python, TypeScript, JavaScript, Go, Rust, Java, C, and C++.
    """

    def __init__(self, parser: Parser | None = None):
        self.parser = parser or Parser()

    def extract(
        self,
        file_info: FileInfo,
        content: str,
        file_id: UUID | None = None,
    ) -> list[Symbol]:
        """Extract all symbols from a file's content based on its detected language."""
        if file_info.is_binary:
            return []

        safe_content = _sanitize_source_text(content or "")
        if not safe_content.strip():
            return []

        file_id = file_id or uuid4()
        tree = self.parser.parse(file_info, safe_content)
        if tree is None:
            if file_info.language == "Python":
                return self._extract_python_ast(safe_content, file_id)
            if file_info.language in ("JavaScript", "TypeScript"):
                return self._extract_js_ts_fallback(safe_content, file_id)
            return []

        symbols: list[Symbol] = []
        lines = safe_content.splitlines()

        def get_sig(node: Any) -> str:
            start_row = node.start_point[0]
            if 0 <= start_row < len(lines):
                return lines[start_row].strip()
            return ""

        def get_text(node: Any) -> str:
            raw_txt = getattr(node, "text", b"")
            if isinstance(raw_txt, bytes):
                return raw_txt.decode("utf-8", errors="replace")
            return str(raw_txt or "")

        def extract_identifier_from_declarator(node: Any) -> str:
            if getattr(node, "type", "") in (
                "identifier",
                "field_identifier",
                "property_identifier",
                "type_identifier",
            ):
                return get_text(node)
            for ch in getattr(node, "children", []):
                found = extract_identifier_from_declarator(ch)
                if found:
                    return found
            return ""

        def walk(node: Any, parent_id: UUID | None = None):
            t = node.type

            if t in (
                "import_statement",
                "import_from_statement",
                "import_declaration",
                "use_declaration",
                "preproc_include",
            ):
                sig = get_sig(node)
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=sig,
                        kind="import",
                        file_id=file_id,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=sig,
                        parent_id=parent_id,
                    )
                )
                return

            if t in (
                "class_definition",
                "class_declaration",
                "struct_item",
                "enum_item",
                "enum_declaration",
                "struct_specifier",
                "class_specifier",
            ):
                # In native Tree-sitter C/C++, `struct_specifier` and `class_specifier` also appear
                # inside parameter/variable types (`const struct PacketHeader *hdr`) and forward
                # declarations that have no `field_declaration_list` body. Ignore those non-definitions.
                if t in ("struct_specifier", "class_specifier") and not isinstance(
                    node, StructuralCSTNode
                ):
                    has_body = any(
                        getattr(c, "type", "") == "field_declaration_list"
                        for c in getattr(node, "children", [])
                    )
                    if not has_body:
                        return

                name = ""
                for c in node.children:
                    if c.type in ("identifier", "type_identifier"):
                        name = get_text(c)
                        break
                if not name:
                    return
                sym_id = uuid4()
                sig = get_sig(node)
                symbols.append(
                    Symbol(
                        id=sym_id,
                        name=name,
                        kind="class",
                        file_id=file_id,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=sig,
                        parent_id=parent_id,
                    )
                )
                for c in node.children:
                    walk(c, sym_id)
                return

            if t == "impl_item":
                # Rust impl block: resolve existing struct symbol ID if declared in same file
                impl_name = ""
                for c in node.children:
                    if c.type in ("type_identifier", "identifier"):
                        impl_name = get_text(c)
                matching_parent = next(
                    (s.id for s in symbols if s.name == impl_name and s.kind in ("class", "interface")),
                    parent_id,
                )
                if matching_parent is None and impl_name:
                    matching_parent = uuid4()
                    symbols.append(
                        Symbol(
                            id=matching_parent,
                            name=impl_name,
                            kind="class",
                            file_id=file_id,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            signature=get_sig(node),
                            parent_id=None,
                        )
                    )
                for c in node.children:
                    walk(c, matching_parent)
                return

            if t == "type_declaration":
                # Go `type Foo struct` or `type Bar interface`
                for c in node.children:
                    if c.type == "type_spec":
                        t_name = ""
                        t_kind = "class"
                        for gc in c.children:
                            if gc.type in ("type_identifier", "identifier") and not t_name:
                                t_name = get_text(gc)
                            elif gc.type == "interface_type":
                                t_kind = "interface"
                        if t_name:
                            symbols.append(
                                Symbol(
                                    id=uuid4(),
                                    name=t_name,
                                    kind=t_kind,
                                    file_id=file_id,
                                    start_line=c.start_point[0] + 1,
                                    end_line=c.end_point[0] + 1,
                                    signature=get_sig(c),
                                    parent_id=parent_id,
                                )
                            )
                return

            if t in ("const_declaration", "var_declaration") and parent_id is None:
                # Go top-level const / var declarations (`const_spec` / `var_spec`)
                found_spec = False
                for c in node.children:
                    if c.type in ("const_spec", "var_spec"):
                        found_spec = True
                        cname = ""
                        for gc in c.children:
                            if gc.type == "identifier":
                                cname = get_text(gc)
                                break
                        if cname:
                            sig = get_sig(c)
                            symbols.append(
                                Symbol(
                                    id=uuid4(),
                                    name=cname,
                                    kind="constant",
                                    file_id=file_id,
                                    start_line=c.start_point[0] + 1,
                                    end_line=c.end_point[0] + 1,
                                    signature=sig,
                                    parent_id=parent_id,
                                )
                            )
                if found_spec:
                    return

            if t in ("field_declaration", "constant_declaration"):
                # Java `public static final int DEFAULT_TIMEOUT_MS = 5000;` or interface `constant_declaration`
                sig = get_sig(node)
                node_txt = get_text(node)
                is_java_const = t == "constant_declaration" or (
                    "static" in (sig or node_txt) and "final" in (sig or node_txt)
                )
                if is_java_const:
                    for c in node.children:
                        if c.type == "variable_declarator":
                            cname = extract_identifier_from_declarator(c)
                            if cname:
                                symbols.append(
                                    Symbol(
                                        id=uuid4(),
                                        name=cname,
                                        kind="constant",
                                        file_id=file_id,
                                        start_line=node.start_point[0] + 1,
                                        end_line=node.end_point[0] + 1,
                                        signature=sig,
                                        parent_id=parent_id,
                                    )
                                )
                                break
                return

            if t in (
                "function_definition",
                "function_declaration",
                "function_item",
                "method_definition",
                "method_declaration",
                "constructor_declaration",
            ):
                name = ""
                for c in node.children:
                    if c.type in ("identifier", "property_identifier", "field_identifier"):
                        name = get_text(c)
                        break
                    if c.type in ("function_declarator", "pointer_declarator"):
                        name = extract_identifier_from_declarator(c)
                        if name:
                            break
                if not name:
                    return
                kind = (
                    "method"
                    if (parent_id or t in ("method_definition", "method_declaration", "constructor_declaration"))
                    else "function"
                )
                sig = get_sig(node)
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=name,
                        kind=kind,
                        file_id=file_id,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=sig,
                        parent_id=parent_id,
                    )
                )
                return

            if t in ("interface_declaration", "trait_item"):
                name = ""
                for c in node.children:
                    if c.type in ("identifier", "type_identifier"):
                        name = get_text(c)
                        break
                sig = get_sig(node)
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=name,
                        kind="interface",
                        file_id=file_id,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=sig,
                        parent_id=parent_id,
                    )
                )
                return

            if t in ("lexical_declaration", "variable_declaration"):
                text = get_text(node)
                is_req = "require(" in text
                sig = get_sig(node)
                for c in node.children:
                    if c.type in ("variable_declarator",):
                        dname = ""
                        for gc in c.children:
                            if gc.type in ("identifier", "object_pattern"):
                                dname = get_text(gc)
                                break
                        symbols.append(
                            Symbol(
                                id=uuid4(),
                                name=dname or sig,
                                kind="import" if is_req else "constant",
                                file_id=file_id,
                                start_line=node.start_point[0] + 1,
                                end_line=node.end_point[0] + 1,
                                signature=sig,
                                parent_id=parent_id,
                            )
                        )
                        break
                return

            if t in ("assignment", "const_item", "static_item", "preproc_def") and parent_id is None:
                left = node.children[0] if node.children else None
                name = get_text(left) if left else ""
                if not name:
                    for c in node.children:
                        if c.type == "identifier":
                            name = get_text(c)
                            break
                sig = get_sig(node)
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=name or sig,
                        kind="constant",
                        file_id=file_id,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        signature=sig,
                        parent_id=parent_id,
                    )
                )
                return

            if t == "export_statement":
                for c in node.children:
                    walk(c, parent_id)
                return

            for c in node.children:
                walk(c, parent_id)

        walk(tree.root_node)
        if not symbols and file_info.language in ("JavaScript", "TypeScript"):
            return self._extract_js_ts_fallback(safe_content, file_id)
        return symbols

    def _extract_python_ast(self, content: str, file_id: UUID) -> list[Symbol]:
        """Fallback Python AST extractor with partial syntax-error recovery."""
        import ast

        symbols: list[Symbol] = []
        lines = content.splitlines()
        tree = None
        try:
            tree = ast.parse(content)
        except SyntaxError as syn_err:
            err_line = getattr(syn_err, "lineno", None)
            if err_line and err_line > 1:
                prefix = "\n".join(lines[: err_line - 1])
                try:
                    tree = ast.parse(prefix)
                except Exception:
                    tree = None
            if tree is None:
                return self._extract_python_regex_fallback(content, file_id)
        except Exception as e:
            logger.warning(f"Python fallback AST parse error: {e}")
            return self._extract_python_regex_fallback(content, file_id)

        def get_sig(lineno: int) -> str:
            if 1 <= lineno <= len(lines):
                return lines[lineno - 1].strip()
            return ""

        for node in tree.body:
            try:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    sig = get_sig(node.lineno)
                    symbols.append(
                        Symbol(
                            id=uuid4(),
                            name=sig,
                            kind="import",
                            file_id=file_id,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            signature=sig,
                            parent_id=None,
                        )
                    )
                elif isinstance(node, ast.ClassDef):
                    sym_id = uuid4()
                    sig = get_sig(node.lineno)
                    symbols.append(
                        Symbol(
                            id=sym_id,
                            name=node.name,
                            kind="class",
                            file_id=file_id,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            signature=sig,
                            parent_id=None,
                        )
                    )
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            item_sig = get_sig(item.lineno)
                            symbols.append(
                                Symbol(
                                    id=uuid4(),
                                    name=item.name,
                                    kind="method",
                                    file_id=file_id,
                                    start_line=item.lineno,
                                    end_line=getattr(item, "end_lineno", item.lineno),
                                    signature=item_sig,
                                    parent_id=sym_id,
                                )
                            )
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = get_sig(node.lineno)
                    symbols.append(
                        Symbol(
                            id=uuid4(),
                            name=node.name,
                            kind="function",
                            file_id=file_id,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            signature=sig,
                            parent_id=None,
                        )
                    )
                elif isinstance(node, ast.Assign):
                    sig = get_sig(node.lineno)
                    target_name = ""
                    if node.targets and isinstance(node.targets[0], ast.Name):
                        target_name = node.targets[0].id
                    symbols.append(
                        Symbol(
                            id=uuid4(),
                            name=target_name or sig,
                            kind="constant",
                            file_id=file_id,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            signature=sig,
                            parent_id=None,
                        )
                    )
            except Exception as e:
                logger.warning(f"Error extracting symbol node via fallback: {e}")
                continue

        if symbols:
            max_parsed_line = max(s.end_line for s in symbols)
            if max_parsed_line < len(lines):
                tail_syms = self._extract_python_regex_fallback(
                    content, file_id, min_line=max_parsed_line + 1
                )
                symbols.extend(tail_syms)

        return symbols

    def _extract_python_regex_fallback(
        self,
        content: str,
        file_id: UUID,
        min_line: int = 1,
    ) -> list[Symbol]:
        """Line-by-line Python symbol recovery when syntax errors prevent full AST compilation."""
        symbols: list[Symbol] = []
        lines = content.splitlines()
        current_class_id: UUID | None = None
        current_class_indent: int = 0

        for idx, raw_line in enumerate(lines):
            lineno = idx + 1
            if lineno < min_line:
                continue
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" \t"))
            if indent <= current_class_indent and not stripped.startswith("@"):
                current_class_id = None

            m_cls = re.match(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\b.*:", stripped)
            if m_cls:
                cls_id = uuid4()
                current_class_id = cls_id
                current_class_indent = indent
                symbols.append(
                    Symbol(
                        id=cls_id,
                        name=m_cls.group(1),
                        kind="class",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=lineno,
                        signature=stripped,
                        parent_id=None,
                    )
                )
                continue

            m_fn = re.match(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(.*\)\s*(?:->.*)?:", stripped)
            if m_fn:
                is_method = current_class_id is not None and indent > current_class_indent
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=m_fn.group(1),
                        kind="method" if is_method else "function",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=lineno,
                        signature=stripped,
                        parent_id=current_class_id if is_method else None,
                    )
                )

        return symbols

    def _extract_js_ts_fallback(self, content: str, file_id: UUID) -> list[Symbol]:
        """Structural symbol extractor for JS/TS when tree-sitter grammar is unavailable."""
        symbols: list[Symbol] = []
        lines = content.splitlines()
        total_lines = len(lines)
        i = 0
        while i < total_lines:
            lineno = i + 1
            raw_line = lines[i]
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*")):
                i += 1
                continue

            # 1. ES6 import or CommonJS require
            if stripped.startswith("import ") or re.match(
                r"^(?:const|let|var)\s+.+=\s*require\s*\(", stripped
            ):
                imp_name = stripped
                m_req_lhs = re.match(
                    r"^(?:const|let|var)\s+(\{[^}]+\}|[A-Za-z_$][\w$]*)\s*=\s*require\s*\(",
                    stripped,
                )
                if m_req_lhs:
                    imp_name = m_req_lhs.group(1).strip()
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=imp_name,
                        kind="import",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=lineno,
                        signature=stripped,
                        parent_id=None,
                    )
                )
                i += 1
                continue

            # 2. Interface declaration
            m_iface = re.match(
                r"^(?:export\s+)?(?:default\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)",
                stripped,
            )
            if m_iface:
                end_idx, _ = _find_matching_brace_line(lines, i)
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=m_iface.group(1),
                        kind="interface",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=end_idx + 1,
                        signature=stripped,
                        parent_id=None,
                    )
                )
                i = end_idx + 1
                continue

            # 3. Class declaration + inner methods
            m_cls = re.match(
                r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)",
                stripped,
            )
            if m_cls:
                cls_id = uuid4()
                end_idx, _ = _find_matching_brace_line(lines, i)
                symbols.append(
                    Symbol(
                        id=cls_id,
                        name=m_cls.group(1),
                        kind="class",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=end_idx + 1,
                        signature=stripped,
                        parent_id=None,
                    )
                )
                k = i + 1
                while k < end_idx:
                    k_strip = lines[k].strip()
                    if not k_strip or k_strip.startswith(("//", "/*", "*", "@")):
                        k += 1
                        continue
                    m_meth = re.match(
                        r"^(?:public\s+|protected\s+|private\s+|readonly\s+|static\s+|async\s+|override\s+|abstract\s+)*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\([^;]*\)\s*(?::\s*[^{=;]+)?\{",
                        k_strip,
                    )
                    if m_meth and m_meth.group(1) not in (
                        "if",
                        "for",
                        "while",
                        "switch",
                        "catch",
                        "function",
                    ):
                        m_end, _ = _find_matching_brace_line(lines, k)
                        m_end = min(m_end, end_idx)
                        symbols.append(
                            Symbol(
                                id=uuid4(),
                                name=m_meth.group(1),
                                kind="method",
                                file_id=file_id,
                                start_line=k + 1,
                                end_line=m_end + 1,
                                signature=k_strip,
                                parent_id=cls_id,
                            )
                        )
                        k = m_end + 1
                        continue
                    k += 1
                i = end_idx + 1
                continue

            # 4. Top-level function declaration
            m_fn = re.match(
                r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>]*>)?\s*\(",
                stripped,
            )
            if m_fn:
                end_idx, _ = _find_matching_brace_line(lines, i)
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=m_fn.group(1),
                        kind="function",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=end_idx + 1,
                        signature=stripped,
                        parent_id=None,
                    )
                )
                i = end_idx + 1
                continue

            # 5. Top-level const / let / var constant assignment
            m_const = re.match(
                r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?!require\s*\()",
                stripped,
            )
            if m_const and not stripped.startswith("module.exports"):
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=m_const.group(1),
                        kind="constant",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=lineno,
                        signature=stripped,
                        parent_id=None,
                    )
                )

            i += 1
        return symbols

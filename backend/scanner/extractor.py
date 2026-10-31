import logging
import re
from typing import Any, List, Optional
from uuid import UUID, uuid4

try:
    import tree_sitter
except ImportError:
    tree_sitter = None

from .parser import Parser, _sanitize_source_text
from .symbols import FileInfo, Symbol


logger = logging.getLogger(__name__)


class SymbolExtractor:
    """Extracts code symbols (classes, functions, methods, imports, constants, interfaces)

    from tree-sitter concrete syntax trees or resilient AST/regex fallbacks.
    """

    def __init__(self, parser: Optional[Parser] = None):
        self.parser = parser or Parser()

    def extract(
        self,
        file_info: FileInfo,
        content: str,
        file_id: Optional[UUID] = None,
    ) -> List[Symbol]:
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

        symbols: List[Symbol] = []
        lines = safe_content.splitlines()

        def get_sig(node: Any) -> str:
            start_row = node.start_point[0]
            if start_row < len(lines):
                return lines[start_row].strip()
            return ""

        def get_text(node: Any) -> str:
            return node.text.decode("utf-8", errors="replace")

        def walk(node: Any, parent_id: Optional[UUID] = None):
            t = node.type

            if t in ("import_statement", "import_from_statement"):
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

            if t in ("class_definition", "class_declaration"):
                name = ""
                for c in node.children:
                    if c.type in ("identifier", "type_identifier"):
                        name = get_text(c)
                        break
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

            if t in (
                "function_definition",
                "function_declaration",
                "method_definition",
                "method_declaration",
            ):
                name = ""
                for c in node.children:
                    if c.type in ("identifier", "property_identifier", "field_identifier"):
                        name = get_text(c)
                        break
                kind = "method" if (parent_id or t in ("method_definition", "method_declaration")) else "function"
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

            if t == "interface_declaration":
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

            if t == "assignment" and parent_id is None:
                left = node.children[0] if node.children else None
                name = get_text(left) if left else ""
                sig = get_sig(node)
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=name,
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
        return symbols

    def _extract_python_ast(self, content: str, file_id: UUID) -> List[Symbol]:
        """Fallback Python AST extractor with partial syntax-error recovery."""
        import ast

        symbols: List[Symbol] = []
        lines = content.splitlines()
        tree = None
        try:
            tree = ast.parse(content)
        except SyntaxError as syn_err:
            # Attempt partial recovery by masking broken lines or parsing prefix before syntax error
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

        # If a syntax error truncated AST parsing midway through the file, recover remaining top-level defs
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
    ) -> List[Symbol]:
        """Line-by-line Python symbol recovery when syntax errors prevent full AST compilation."""
        symbols: List[Symbol] = []
        lines = content.splitlines()
        current_class_id: Optional[UUID] = None
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

    def _extract_js_ts_fallback(self, content: str, file_id: UUID) -> List[Symbol]:
        """Regex/structural symbol extractor for JS/TS when tree-sitter grammar is unavailable."""
        symbols: List[Symbol] = []
        lines = content.splitlines()
        for idx, raw_line in enumerate(lines):
            lineno = idx + 1
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            m_imp = re.match(r"^import\s+.*", stripped)
            if m_imp:
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=stripped,
                        kind="import",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=lineno,
                        signature=stripped,
                        parent_id=None,
                    )
                )
                continue
            m_cls = re.match(r"^(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)", stripped)
            if m_cls:
                symbols.append(
                    Symbol(
                        id=uuid4(),
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
            m_iface = re.match(r"^(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)", stripped)
            if m_iface:
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=m_iface.group(1),
                        kind="interface",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=lineno,
                        signature=stripped,
                        parent_id=None,
                    )
                )
                continue
            m_fn = re.match(
                r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
                stripped,
            )
            if m_fn:
                symbols.append(
                    Symbol(
                        id=uuid4(),
                        name=m_fn.group(1),
                        kind="function",
                        file_id=file_id,
                        start_line=lineno,
                        end_line=lineno,
                        signature=stripped,
                        parent_id=None,
                    )
                )
        return symbols

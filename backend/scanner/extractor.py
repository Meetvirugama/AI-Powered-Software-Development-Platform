import logging
from typing import Any, List, Optional
from uuid import UUID, uuid4

try:
    import tree_sitter
except ImportError:
    tree_sitter = None

from .parser import Parser
from .symbols import FileInfo, Symbol


logger = logging.getLogger(__name__)


class SymbolExtractor:
    """Extracts code symbols (classes, functions, methods, imports, constants, interfaces)

    from tree-sitter concrete syntax trees.
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

        file_id = file_id or uuid4()
        tree = self.parser.parse(file_info, content)
        if tree is None:
            if file_info.language == "Python":
                return self._extract_python_ast(content, file_id)
            return []

        symbols: List[Symbol] = []
        lines = content.splitlines()


        def get_sig(node: Any) -> str:
            start_row = node.start_point[0]
            if start_row < len(lines):
                return lines[start_row].strip()
            return ""

        def get_text(node: Any) -> str:
            return node.text.decode("utf-8")

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
                    if c.type in ("identifier", "property_identifier"):
                        name = get_text(c)
                        break
                kind = "method" if parent_id else "function"
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
        """Fallback Python AST extractor using python's built-in ast module."""
        import ast

        symbols: List[Symbol] = []
        lines = content.splitlines()
        try:
            tree = ast.parse(content)
        except Exception as e:
            logger.warning(f"Python fallback AST parse error: {e}")
            return []

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

        return symbols


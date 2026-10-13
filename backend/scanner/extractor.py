import logging
from typing import List, Optional
from uuid import UUID, uuid4

import tree_sitter

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
            return []

        symbols: List[Symbol] = []
        lines = content.splitlines()

        def get_sig(node: tree_sitter.Node) -> str:
            start_row = node.start_point[0]
            if start_row < len(lines):
                return lines[start_row].strip()
            return ""

        def get_text(node: tree_sitter.Node) -> str:
            return node.text.decode("utf-8")

        def walk(node: tree_sitter.Node, parent_id: Optional[UUID] = None):
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

            if t in ("function_definition", "function_declaration"):
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

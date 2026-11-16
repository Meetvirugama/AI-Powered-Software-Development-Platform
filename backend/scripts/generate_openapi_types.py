#!/usr/bin/env python3
"""Generate TypeScript definitions from the FastAPI OpenAPI schema (OPT-03).

Exports all models in `components.schemas` directly into `frontend/src/types/api.gen.ts`
ensuring frontend contracts are strictly synchronized with backend Pydantic models.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

# Ensure backend is on sys.path
repo_root = Path(__file__).resolve().parent.parent.parent
backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app  # noqa: E402


def resolve_type(prop: dict, parent_schema: dict | None = None) -> str:
    """Recursively resolve OpenAPI property schema to TypeScript type."""
    if "$ref" in prop:
        return prop["$ref"].split("/")[-1]

    if "anyOf" in prop:
        types = [resolve_type(t) for t in prop["anyOf"]]
        # deduplicate while keeping order
        deduped = []
        for t in types:
            if t not in deduped:
                deduped.append(t)
        return " | ".join(deduped)

    if "oneOf" in prop:
        types = [resolve_type(t) for t in prop["oneOf"]]
        return " | ".join(dict.fromkeys(types))

    if "allOf" in prop:
        types = [resolve_type(t) for t in prop["allOf"]]
        return " & ".join(dict.fromkeys(types))

    if "enum" in prop:
        return " | ".join(json.dumps(val) for val in prop["enum"])

    t = prop.get("type")
    if t == "string":
        if prop.get("format") in ("date-time", "date"):
            return "string"
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "array":
        items = prop.get("items", {})
        item_t = resolve_type(items)
        if " " in item_t or "|" in item_t or "&" in item_t:
            return f"({item_t})[]"
        return f"{item_t}[]"
    if t == "object":
        add_props = prop.get("additionalProperties")
        if add_props is True or add_props == {}:
            return "Record<string, unknown>"
        if isinstance(add_props, dict):
            val_t = resolve_type(add_props)
            return f"Record<string, {val_t}>"
        props = prop.get("properties")
        if props:
            # Inline object definition
            lines = ["{"]
            req = set(prop.get("required", []))
            for p_name, p_spec in props.items():
                opt = "" if p_name in req else "?"
                p_type = resolve_type(p_spec)
                lines.append(f"  {json.dumps(p_name)}{opt}: {p_type};")
            lines.append("}")
            return " ".join(lines)
        return "Record<string, unknown>"
    if t == "null":
        return "null"

    return "unknown"


def generate_typescript_definitions() -> str:
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})

    output = [
        "/**",
        " * AUTO-GENERATED FILE — DO NOT EDIT DIRECTLY.",
        " * Generated from FastAPI OpenAPI schema via backend/scripts/generate_openapi_types.py (OPT-03).",
        " */",
        "",
    ]

    for name in sorted(schemas.keys()):
        schema = schemas[name]
        description = schema.get("description", "")
        if description:
            output.append("/**")
            for line in description.strip().splitlines():
                output.append(f" * {line}")
            output.append(" */")

        if "enum" in schema:
            variants = " | ".join(json.dumps(v) for v in schema["enum"])
            output.append(f"export type {name} = {variants};")
            output.append("")
            continue

        if schema.get("type") != "object" and "properties" not in schema:
            resolved = resolve_type(schema)
            output.append(f"export type {name} = {resolved};")
            output.append("")
            continue

        output.append(f"export interface {name} {{")
        props = schema.get("properties", {})
        required = set(schema.get("required", []))

        for prop_name, prop_spec in props.items():
            prop_desc = prop_spec.get("description", "")
            if prop_desc:
                output.append(f"  /** {prop_desc.strip()} */")
            is_req = prop_name in required
            opt = "" if is_req else "?"
            t_str = resolve_type(prop_spec, schema)
            output.append(f"  {prop_name}{opt}: {t_str};")

        output.append("}")
        output.append("")

    return "\n".join(output)


def main() -> None:
    target_path = repo_root / "frontend" / "src" / "types" / "api.gen.ts"
    print(f"Generating OpenAPI TypeScript definitions -> {target_path}...")
    ts_code = generate_typescript_definitions()
    target_path.write_text(ts_code, encoding="utf-8")
    print(f"Wrote {len(ts_code.splitlines())} lines to {target_path}")


if __name__ == "__main__":
    main()

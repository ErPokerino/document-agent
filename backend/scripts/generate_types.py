"""Generate lib/types.ts from the FastAPI OpenAPI schema.

The frontend contract used to be transcribed by hand, and it had already
drifted from the Pydantic models. Generating it makes the drift impossible:
test_generated_types.py fails whenever the committed file and the live schema
disagree.

Usage:
    .venv/Scripts/python.exe backend/scripts/generate_types.py
"""

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TYPES_PATH = REPO_ROOT / "lib" / "types.ts"

HEADER = """// Generated from the FastAPI OpenAPI schema. Do not edit by hand.
// Regenerate with: .venv/Scripts/python.exe backend/scripts/generate_types.py
//
// Every property is emitted as required: FastAPI serializes response models in
// full, defaults included, and the frontend always sends complete objects back.
"""

# FastAPI's own request/error plumbing is not part of the frontend contract.
INTERNAL_PREFIXES = ("Body_",)
INTERNAL_NAMES = {"HTTPValidationError", "ValidationError"}

# Literal unions that the frontend needs as standalone names. Derived from the
# generated models with an indexed access type, so they track the backend.
DERIVED_ALIASES = (
    ("Confidence", "FieldExtraction", "confidence"),
    ("ModelRuntimeState", "ModelInfo", "runtime_state"),
)


class UnsupportedSchema(RuntimeError):
    """Raised when the schema uses a construct this generator does not model."""


def _is_internal(name: str) -> bool:
    return name in INTERNAL_NAMES or name.startswith(INTERNAL_PREFIXES)


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _union(parts: list[str]) -> str:
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return " | ".join(seen)


def _type_of(schema: dict[str, Any], context: str) -> str:
    if "$ref" in schema:
        return _ref_name(schema["$ref"])
    if "anyOf" in schema:
        return _union([_type_of(option, context) for option in schema["anyOf"]])
    if "enum" in schema:
        return _union([f'"{value}"' for value in schema["enum"]])
    if "const" in schema:
        # Pydantic renders a single-value Literal as `const`, not as a one-item enum.
        return f'"{schema["const"]}"'

    if not schema:
        # An unconstrained value: Pydantic renders `Any` as an empty schema.
        return "unknown"

    kind = schema.get("type")
    if kind == "string":
        return "string"
    if kind in {"number", "integer"}:
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        item = schema.get("items")
        if item is None:
            raise UnsupportedSchema(f"{context}: array without items")
        return f"{_type_of(item, context)}[]"
    if kind == "object":
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"Record<string, {_type_of(additional, context)}>"
        if additional is True:
            return "Record<string, unknown>"
        raise UnsupportedSchema(f"{context}: object without additionalProperties")

    raise UnsupportedSchema(f"{context}: unsupported schema {sorted(schema)}")


def _render_object(name: str, schema: dict[str, Any]) -> str:
    lines = [f"export type {name} = {{"]
    for prop, prop_schema in schema.get("properties", {}).items():
        lines.append(f"  {prop}: {_type_of(prop_schema, f'{name}.{prop}')};")
    lines.append("};")
    return "\n".join(lines)


def render_types(openapi_schema: dict[str, Any]) -> str:
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    public = {name: body for name, body in schemas.items() if not _is_internal(name)}

    blocks: list[str] = []

    # Standalone enums first: they read as the vocabulary of the API.
    for name in sorted(public):
        body = public[name]
        if "enum" in body:
            blocks.append(f"export type {name} = {_type_of(body, name)};")

    for name, model, prop in DERIVED_ALIASES:
        if model in public:
            blocks.append(f'export type {name} = {model}["{prop}"];')

    for name in sorted(public):
        body = public[name]
        if "enum" in body:
            continue
        if body.get("type") != "object":
            raise UnsupportedSchema(f"{name}: top-level schema is not an object")
        blocks.append(_render_object(name, body))

    return HEADER + "\n" + "\n\n".join(blocks) + "\n"


def main() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.main import app

    TYPES_PATH.write_text(render_types(app.openapi()), encoding="utf-8", newline="\n")
    print(f"wrote {TYPES_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

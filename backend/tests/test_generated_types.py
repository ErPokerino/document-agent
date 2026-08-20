from pathlib import Path

from app.main import app
from scripts.generate_types import TYPES_PATH, render_types


def test_generated_typescript_matches_the_committed_file() -> None:
    committed = Path(TYPES_PATH).read_text(encoding="utf-8")

    assert committed == render_types(app.openapi()), (
        "lib/types.ts is out of date with the FastAPI schema. "
        "Run: .venv/Scripts/python.exe backend/scripts/generate_types.py"
    )


def test_every_api_model_is_exported() -> None:
    generated = render_types(app.openapi())

    for name in ("AppSettings", "ExtractionResponse", "FieldExtraction", "ModelInfo"):
        assert f"export type {name} = {{" in generated


def test_internal_fastapi_schemas_are_not_exported() -> None:
    generated = render_types(app.openapi())

    assert "HTTPValidationError" not in generated
    assert "ValidationError" not in generated
    assert "Body_extract_document" not in generated


def test_nullable_fields_become_a_null_union() -> None:
    generated = render_types(app.openapi())

    assert "warning: string | null;" in generated
    assert "size_bytes: number | null;" in generated


def test_a_dict_of_models_becomes_a_record() -> None:
    assert "data: Record<string, FieldExtraction>;" in render_types(app.openapi())


def test_literal_unions_are_reused_as_named_aliases() -> None:
    generated = render_types(app.openapi())

    # page.tsx keys Record<> maps on these, and deriving them from the generated
    # models means they cannot drift away from the backend.
    assert 'export type Confidence = FieldExtraction["confidence"];' in generated
    assert 'export type ModelRuntimeState = ModelInfo["runtime_state"];' in generated


def test_an_unsupported_schema_construct_fails_loudly() -> None:
    import pytest

    from scripts.generate_types import UnsupportedSchema, render_types as render

    broken = {
        "components": {
            "schemas": {
                "Weird": {
                    "type": "object",
                    "properties": {"thing": {"not": {"type": "string"}}},
                }
            }
        }
    }
    with pytest.raises(UnsupportedSchema):
        render(broken)

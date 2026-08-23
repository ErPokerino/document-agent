"""Filling an entity the document never carried, from the register."""

import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction
from app.pipeline.engine import PipelineContext
from app.pipeline.steps import LookUpInMasterData
from app.services.master_data import SubjectStore


ENTITIES = [
    EntityDefinition(name="supplier_name", format=EntityFormat.text, description="x"),
    EntityDefinition(name="id_subject", format=EntityFormat.text, description="x", source="derived"),
]


@pytest.fixture
def register(tmp_path) -> SubjectStore:
    store = SubjectStore(tmp_path / "docuflow.db")
    store.seed(["ACME S.r.l.", "Zeta Trasporti", "UL Solutions"])
    return store


def context(extraction: dict) -> PipelineContext:
    ctx = PipelineContext(filename="a.pdf", content=b"", model="m", lm_studio_url="http://x")
    ctx.artifacts["extraction"] = extraction
    return ctx


def step(register: SubjectStore, **overrides) -> LookUpInMasterData:
    return LookUpInMasterData(
        entities=ENTITIES,
        subjects=register,
        source_entity=overrides.pop("source_entity", "supplier_name"),
        target_entity=overrides.pop("target_entity", "id_subject"),
        algorithm=overrides.pop("algorithm", "combined"),
        minimum_similarity=overrides.pop("minimum_similarity", 0.75),
    )


@pytest.mark.asyncio
async def test_an_exact_name_finds_its_identifier(register) -> None:
    ctx = context({"supplier_name": FieldExtraction(value="ACME S.r.l.", confidence="high")})

    await step(register).run(ctx)

    found = ctx.artifacts["extraction"]["id_subject"]
    assert found.value == "S0001"
    assert found.score == 1.0
    assert found.confidence == "high"


@pytest.mark.asyncio
async def test_a_different_spelling_still_finds_it(register) -> None:
    ctx = context({"supplier_name": FieldExtraction(value="ACME SRL", confidence="high")})

    await step(register).run(ctx)

    assert ctx.artifacts["extraction"]["id_subject"].value == "S0001"


@pytest.mark.asyncio
async def test_the_confidence_reports_how_good_the_match_was(register) -> None:
    ctx = context({"supplier_name": FieldExtraction(value="Zeta Traspoti", confidence="high")})

    await step(register, minimum_similarity=0.5).run(ctx)

    found = ctx.artifacts["extraction"]["id_subject"]
    assert found.value == "S0002"
    assert 0.5 < found.score < 1.0
    # Not a perfect match, so it must not claim to be a certain one.
    assert found.confidence in {"low", "medium"}


@pytest.mark.asyncio
async def test_nothing_close_enough_leaves_the_field_empty_and_says_why(register) -> None:
    ctx = context({"supplier_name": FieldExtraction(value="Bianchi Costruzioni", confidence="high")})

    await step(register).run(ctx)

    found = ctx.artifacts["extraction"]["id_subject"]
    assert found.value is None
    assert found.confidence == "low"
    assert "Bianchi Costruzioni" in found.warning
    assert "0.75" in found.warning


@pytest.mark.asyncio
async def test_the_threshold_is_the_one_the_pipeline_was_given(register) -> None:
    ctx = context({"supplier_name": FieldExtraction(value="Zeta Traspoti", confidence="high")})

    await step(register, minimum_similarity=0.99).run(ctx)

    assert ctx.artifacts["extraction"]["id_subject"].value is None


@pytest.mark.asyncio
async def test_no_source_value_means_no_lookup_and_no_pretence(register) -> None:
    ctx = context({"supplier_name": FieldExtraction(value=None, confidence="low")})

    await step(register).run(ctx)

    found = ctx.artifacts["extraction"]["id_subject"]
    assert found.value is None
    assert "supplier_name" in found.warning


@pytest.mark.asyncio
async def test_an_empty_register_is_reported_as_such(tmp_path) -> None:
    empty = SubjectStore(tmp_path / "docuflow.db")
    ctx = context({"supplier_name": FieldExtraction(value="ACME", confidence="high")})

    await step(empty).run(ctx)

    assert "register is empty" in ctx.artifacts["extraction"]["id_subject"].warning


@pytest.mark.asyncio
async def test_the_step_leaves_every_other_field_alone(register) -> None:
    extraction = {
        "supplier_name": FieldExtraction(value="ACME S.r.l.", confidence="high"),
        "total_amount": FieldExtraction(value=125.31, confidence="medium"),
    }
    ctx = context(extraction)

    await step(register).run(ctx)

    assert ctx.artifacts["extraction"]["total_amount"].value == 125.31
    assert ctx.artifacts["extraction"]["supplier_name"].value == "ACME S.r.l."

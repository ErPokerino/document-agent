import json

import pytest

from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
from app.pipeline.store import PipelineStore, UnknownPipeline


def store(tmp_path) -> PipelineStore:
    return PipelineStore(tmp_path / "pipelines")


def a_pipeline(name: str = "ocr-then-llm") -> PipelineDefinition:
    return PipelineDefinition(
        name=name,
        description="",
        steps=[
            PipelineStep(kind=StepKind.render_pages),
            PipelineStep(kind=StepKind.llm_extract),
        ],
    )


def test_an_empty_store_still_offers_the_default_pipeline(tmp_path) -> None:
    listed = store(tmp_path).list()

    assert [pipeline.name for pipeline in listed] == [PipelineDefinition.default().name]


def test_a_saved_pipeline_comes_back_as_written(tmp_path) -> None:
    pipelines = store(tmp_path)

    pipelines.save(a_pipeline())

    assert pipelines.read("ocr-then-llm") == a_pipeline()


def test_saving_again_replaces_the_previous_version(tmp_path) -> None:
    pipelines = store(tmp_path)
    pipelines.save(a_pipeline())

    updated = a_pipeline()
    updated.description = "now with a note"
    pipelines.save(updated)

    assert pipelines.read("ocr-then-llm").description == "now with a note"
    assert len([p for p in pipelines.list() if p.name == "ocr-then-llm"]) == 1


def test_reading_a_pipeline_that_was_never_saved_says_so(tmp_path) -> None:
    with pytest.raises(UnknownPipeline, match="nope"):
        store(tmp_path).read("nope")


def test_the_default_pipeline_is_readable_without_being_saved(tmp_path) -> None:
    assert store(tmp_path).read(PipelineDefinition.default().name) == PipelineDefinition.default()


def test_a_saved_pipeline_may_override_the_default(tmp_path) -> None:
    pipelines = store(tmp_path)
    mine = a_pipeline(PipelineDefinition.default().name)
    mine.description = "my version"

    pipelines.save(mine)

    assert pipelines.read(mine.name).description == "my version"
    assert len(pipelines.list()) == 1


def test_a_deleted_pipeline_is_gone(tmp_path) -> None:
    pipelines = store(tmp_path)
    pipelines.save(a_pipeline())

    pipelines.delete("ocr-then-llm")

    assert [p.name for p in pipelines.list()] == [PipelineDefinition.default().name]


def test_deleting_something_that_is_not_there_says_so(tmp_path) -> None:
    with pytest.raises(UnknownPipeline):
        store(tmp_path).delete("nope")


def test_a_name_that_would_escape_the_folder_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        store(tmp_path).read("../../settings")


def test_a_corrupt_file_does_not_take_the_whole_list_down(tmp_path) -> None:
    pipelines = store(tmp_path)
    pipelines.save(a_pipeline())
    (tmp_path / "pipelines" / "broken.json").write_text("{not json", encoding="utf-8")

    names = [p.name for p in pipelines.list()]

    assert "ocr-then-llm" in names
    assert "broken" not in names


def test_the_stored_file_is_plain_readable_json(tmp_path) -> None:
    pipelines = store(tmp_path)
    pipelines.save(a_pipeline())

    written = json.loads((tmp_path / "pipelines" / "ocr-then-llm.json").read_text(encoding="utf-8"))

    assert written["steps"][0]["kind"] == "render_pages"

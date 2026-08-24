"""What LM Studio's selected inference engine means for a run.

A model can be held on the processor and still do part of its work on the
GPU: `--gpu off` governs the model's own layers, while the vision projector
follows whatever engine LM Studio has selected. On a machine whose only
accelerator is an integrated GPU, that split is where runs die, so the app
has to be able to say which engine is in use rather than assume.
"""

from fastapi.testclient import TestClient

from app import main
from app.services.lm_studio import parse_selected_runtime, runtime_uses_gpu


RUNTIME_LS = """LLM ENGINE                                             SELECTED    MODEL FORMAT
executorch-asr-win-x86_64-nvidia-cuda128-avx2@0.0.8                    PTE     
llama.cpp-win-x86_64-avx2@2.28.2                                       GGUF    
llama.cpp-win-x86_64-vulkan-avx2@2.29.1                   \u2713            GGUF    
llama.cpp-win-x86_64-vulkan-avx2@2.28.2                                GGUF    
"""


def test_the_selected_gguf_engine_is_read_from_the_listing() -> None:
    assert parse_selected_runtime(RUNTIME_LS) == "llama.cpp-win-x86_64-vulkan-avx2@2.29.1"


def test_an_engine_selected_for_another_model_format_is_not_the_llm_engine() -> None:
    # The ASR engine can carry its own tick; it has nothing to do with GGUF.
    listing = """LLM ENGINE                          SELECTED    MODEL FORMAT
executorch-asr-win-x86_64-avx2@0.0.8    \u2713           PTE     
llama.cpp-win-x86_64-avx2@2.29.1                    GGUF    
"""
    assert parse_selected_runtime(listing) is None


def test_nothing_selected_reads_as_nothing() -> None:
    assert parse_selected_runtime("") is None
    assert parse_selected_runtime("LLM ENGINE  SELECTED  MODEL FORMAT\n") is None


def test_accelerated_builds_are_told_apart_from_the_processor_build() -> None:
    assert runtime_uses_gpu("llama.cpp-win-x86_64-vulkan-avx2@2.29.1")
    assert runtime_uses_gpu("llama.cpp-win-x86_64-nvidia-cuda-avx2@2.28.2")
    assert runtime_uses_gpu("llama.cpp-mac-arm64-metal@1.0.0")
    assert not runtime_uses_gpu("llama.cpp-win-x86_64-avx2@2.29.1")


def test_an_unknown_engine_is_not_assumed_to_be_accelerated() -> None:
    # Claiming the GPU is involved when it may not be would put a warning in
    # front of a user who has nothing to fix.
    assert not runtime_uses_gpu("")
    assert not runtime_uses_gpu(None)


def test_the_engine_is_reported_over_the_api(monkeypatch) -> None:
    """The UI cannot read `lms`; the backend reads it and says what it found."""
    async def fake_selected_runtime(self: object) -> str | None:
        return "llama.cpp-win-x86_64-vulkan-avx2@2.29.1"

    monkeypatch.setattr(main.LMStudioClient, "selected_runtime", fake_selected_runtime)
    with TestClient(main.app) as client:
        body = client.get("/api/runtime-engine").json()
    assert body["engine"] == "llama.cpp-win-x86_64-vulkan-avx2@2.29.1"
    assert body["uses_gpu"] is True


def test_an_unreadable_engine_is_reported_as_unknown(monkeypatch) -> None:
    """No `lms` on the path, or a remote endpoint: say nothing rather than guess."""
    async def fake_selected_runtime(self: object) -> str | None:
        return None

    monkeypatch.setattr(main.LMStudioClient, "selected_runtime", fake_selected_runtime)
    with TestClient(main.app) as client:
        body = client.get("/api/runtime-engine").json()
    assert body["engine"] is None
    assert body["uses_gpu"] is False

import json

import pytest

from app.services.lm_studio import LMStudioClient, LMStudioError, requires_cpu_safe_profile


# Every test here states the machine it assumes, instead of inheriting whatever
# hardware happens to run the suite. Without this the decision falls back to
# the careful case and the assertions describe nothing.
LAPTOP_SURVEY = """Survey by llama.cpp-win-x86_64-vulkan-avx2 (2.29.1)
GPU/ACCELERATORS                             VRAM
Intel(R) UHD Graphics (Vulkan, Integrated)   19.82 GiB

CPU: x86_64 (AVX, AVX2)
RAM: 39.64 GiB
"""


@pytest.fixture(autouse=True)
def integrated_laptop(monkeypatch):
    """The machine the current thresholds were measured on."""
    from app.services.host import parse_survey
    from app.services.lm_studio import LMStudioClient

    host = parse_survey(LAPTOP_SURVEY)

    async def read_host(self):
        return host

    monkeypatch.setattr(LMStudioClient, "host_capabilities", read_host)
    monkeypatch.setattr(LMStudioClient, "_host_cache", None)
    return host



def item(
    key: str,
    quantization: str = "Q4_K_M",
    size_gb: float = 1.0,
    instances: list | None = None,
    vision: bool = True,
) -> dict:
    return {
        "type": "llm",
        "key": key,
        "display_name": key,
        "quantization": {"name": quantization},
        "size_bytes": int(size_gb * 1024**3),
        "capabilities": {"vision": vision},
        "loaded_instances": instances or [],
    }


def make_items(*items: dict):
    async def fetch(self):
        return list(items)

    return fetch


def loaded(parallel: int, context_length: int = 8192) -> list:
    return [{"id": "i1", "config": {"parallel": parallel, "context_length": context_length}}]


def test_a_large_model_needs_the_cpu_safe_profile(integrated_laptop) -> None:
    assert requires_cpu_safe_profile("Q4_K_M", int(16.5 * 1024**3), host=integrated_laptop) is True


def test_an_iq_quant_needs_it_even_below_the_size_threshold(integrated_laptop) -> None:
    # IQ2_XXS at 7.6 GB used to take the REST path with GPU offload still on:
    # the compatibility profile was applied by halves.
    assert requires_cpu_safe_profile("IQ2_XXS", int(7.63 * 1024**3), host=integrated_laptop) is True


def test_a_small_ordinary_quant_does_not_need_it(integrated_laptop) -> None:
    assert requires_cpu_safe_profile("Q8_0", int(0.95 * 1024**3), host=integrated_laptop) is False
    assert requires_cpu_safe_profile("Q5_K_S", int(1.97 * 1024**3), host=integrated_laptop) is False


@pytest.mark.asyncio
async def test_a_model_loaded_by_someone_else_is_reported_as_a_profile_mismatch(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        # parallel 4 is LM Studio's default: this instance was not loaded by us.
        return [item("qwen3.8-27b@iq2_m", "IQ2_M", 10.48, loaded(parallel=4))]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.loaded is True
    assert model.requires_safe_profile is True
    assert model.profile_matches is False


@pytest.mark.asyncio
async def test_a_model_loaded_by_us_matches_the_profile(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [item("qwen3.8-27b@iq2_m", "IQ2_M", 10.48, loaded(parallel=1))]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.requires_safe_profile is True
    assert model.profile_matches is True


@pytest.mark.asyncio
async def test_a_model_that_needs_no_special_profile_always_matches(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [item("qwen3.5-0.8b", "Q8_0", 0.95, loaded(parallel=4))]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.requires_safe_profile is False
    assert model.profile_matches is True


@pytest.mark.asyncio
async def test_an_unloaded_model_is_not_a_mismatch(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [item("qwen/qwen3.8-27b", "Q4_K_M", 16.5)]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.loaded is False
    assert model.profile_matches is True


@pytest.mark.asyncio
async def test_an_iq_quant_below_the_threshold_is_loaded_through_the_cli(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    used_cli: list[str] = []

    async def fake_items():
        return [item("qwen3.8-27b@iq2_xxs", "IQ2_XXS", 7.63)]

    async def fake_cli(model: str) -> int:
        used_cli.append(model)
        return 1000

    async def fake_post(path, payload, timeout):
        raise AssertionError(f"the REST load path must not be used: {path}")

    async def fake_warmup(*args, **kwargs):
        return None

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_load_large_model_with_cli", fake_cli)
    monkeypatch.setattr(client, "_post_json", fake_post)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("qwen3.8-27b@iq2_xxs")

    assert used_cli == ["qwen3.8-27b@iq2_xxs"]
    assert result["profile"] == "compatibility"


@pytest.mark.asyncio
async def test_a_text_only_model_is_listed_and_marked_as_such(monkeypatch) -> None:
    """OCR pipelines can use a model without vision, so it has to be offered."""
    monkeypatch.setattr(
        LMStudioClient,
        "_fetch_model_items",
        make_items(
            item("vision-one", vision=True),
            item("text-one", vision=False),
        ),
    )

    listed = await LMStudioClient("http://localhost:1234").list_models()

    assert {model.id: model.vision for model in listed} == {
        "vision-one": True,
        "text-one": False,
    }


@pytest.mark.asyncio
async def test_a_text_only_model_is_warmed_up_without_an_image(monkeypatch) -> None:
    """Sending an image to a model without vision is an error, not a warm-up."""
    client = LMStudioClient("http://localhost:1234")
    monkeypatch.setattr(
        LMStudioClient, "_fetch_model_items", make_items(item("text-one", vision=False))
    )

    posted: list[dict] = []

    from app.domain.models import PromptConfiguration

    entities = PromptConfiguration().entities
    answer = json.dumps({entity.name: None for entity in entities} | {"c": "l" * len(entities)})

    async def fake_post(self, path, payload, timeout=None):
        posted.append(payload)
        return {"load_time_seconds": 0.1, "choices": [{"message": {"content": answer}}]}

    monkeypatch.setattr(LMStudioClient, "_post_json", fake_post)

    report = await client.load_and_warm_model("text-one")

    assert report["warmup_mode"] == "schema"
    sent_content = [message["content"] for payload in posted for message in payload.get("messages", [])]
    assert not any(
        isinstance(content, list) and any(part.get("type") == "image_url" for part in content)
        for content in sent_content
    )


def test_a_27b_model_needs_the_safe_profile_however_small_its_file_is(integrated_laptop) -> None:
    """bonsai-27b is 27B parameters in a 4.4 GB Q1_0 file.

    The file size says "small"; the runtime allocates activations, KV cache and
    a vision projector for 27B parameters, and the Vulkan device is lost part
    way through a run. The parameter count is the honest signal.
    """
    assert requires_cpu_safe_profile("Q1_0", int(4.41 * 1024**3), "27B", host=integrated_laptop) is True


def test_a_small_model_is_still_left_on_the_gpu(integrated_laptop) -> None:
    assert requires_cpu_safe_profile("Q4_K_M", int(2.6 * 1024**3), "4B", host=integrated_laptop) is False
    assert requires_cpu_safe_profile("Q8_0", int(0.95 * 1024**3), "0.8B", host=integrated_laptop) is False


def test_an_unreadable_parameter_count_falls_back_to_the_other_signals(integrated_laptop) -> None:
    assert requires_cpu_safe_profile("Q4_K_M", int(2.6 * 1024**3), None, host=integrated_laptop) is False
    assert requires_cpu_safe_profile("Q4_K_M", int(2.6 * 1024**3), "who knows", host=integrated_laptop) is False
    assert requires_cpu_safe_profile("IQ2_M", int(2.6 * 1024**3), "who knows", host=integrated_laptop) is True


def test_parameter_counts_are_read_the_way_lm_studio_writes_them() -> None:
    from app.services.lm_studio import parameter_billions

    assert parameter_billions("27B") == 27
    assert parameter_billions("0.8B") == 0.8
    assert parameter_billions("8x7B") == 7
    assert parameter_billions("700M") == 0.7
    assert parameter_billions(None) is None
    assert parameter_billions("unknown") is None


@pytest.mark.asyncio
async def test_a_big_model_in_a_small_file_is_loaded_through_the_safe_path(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    cli_loads: list[str] = []

    monkeypatch.setattr(
        LMStudioClient,
        "_fetch_model_items",
        make_items({**item("bonsai-27b", "Q1_0", 4.41), "params_string": "27B"}),
    )

    async def fake_cli_load(self, model):
        cli_loads.append(model)
        return 1250

    monkeypatch.setattr(LMStudioClient, "_load_large_model_with_cli", fake_cli_load)
    monkeypatch.setattr(LMStudioClient, "_warm_up_structured_output", lambda self, *a, **k: _noop())

    report = await client.load_and_warm_model("bonsai-27b")

    assert report["profile"] == "compatibility"
    assert cli_loads == ["bonsai-27b"]


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_the_safe_load_asks_for_nothing_a_model_might_not_have(monkeypatch) -> None:
    """The CLI load used to demand MTP speculative decoding from every model.

    bonsai-27b has no MTP head, so the load failed outright with "MTP
    speculative decoding requires a GGUF model with a bundled supported MTP
    head" — the model could not be loaded at all through the safe path.
    """
    import subprocess

    client = LMStudioClient("http://127.0.0.1:1234")
    commands: list[list[str]] = []

    monkeypatch.setattr("app.services.lm_studio.shutil.which", lambda name: "lms")
    monkeypatch.setattr("app.services.lm_studio.asyncio.sleep", lambda seconds: _noop())

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.services.lm_studio.subprocess.run", fake_run)

    await client._load_large_model_with_cli("bonsai-27b")

    assert "--speculative-draft-mtp" not in commands[0]
    # What the profile is actually for stays: no GPU layers, one request.
    assert "--gpu" in commands[0] and "off" in commands[0]
    assert "--parallel" in commands[0]


@pytest.mark.asyncio
async def test_a_pipeline_that_sends_no_images_warms_up_without_one(monkeypatch) -> None:
    """bonsai-27b answers text and dies on any image, even entirely on CPU.

    Warming it up for vision made it unloadable, although it is perfectly
    usable behind an OCR step. The warm-up now asks for what the pipeline
    will actually ask for.
    """
    client = LMStudioClient("http://localhost:1234")
    monkeypatch.setattr(
        LMStudioClient, "_fetch_model_items", make_items(item("sees", vision=True))
    )
    options: dict = {}

    async def fake_warmup(self, model, entities, **kwargs):
        options.update(kwargs)

    monkeypatch.setattr(LMStudioClient, "_warm_up_structured_output", fake_warmup)
    monkeypatch.setattr(
        LMStudioClient, "_post_json", lambda self, *a, **k: _load_answer()
    )

    report = await client.load_and_warm_model("sees", warm_vision=False)

    assert options["include_image"] is False
    assert report["warmup_mode"] == "schema"


async def _load_answer() -> dict:
    return {"load_time_seconds": 0.1}


def test_a_bare_load_failure_is_explained_with_what_the_cli_saw() -> None:
    """LM Studio's REST API drops the reason a load failed.

    It answers `Failed to load LLM 'x': Error: Failed to load model.` for an
    unsupported architecture, a corrupt file and a memory failure alike, which
    leaves someone with nothing to act on. The CLI prints the cause.
    """
    from app.services.lm_studio import explain_load_failure

    cli_output = (
        "Loading ling-3.0-tiny 6%\n"
        "Error: Failed to load model. \n\n\n   (X) CAUSE  \n\n"
        "error loading model: unknown model architecture: 'bailingmoe3'\n"
    )

    explained = explain_load_failure("Failed to load model.", cli_output)

    assert "bailingmoe3" in explained
    assert "architecture" in explained
    # And what to do about it, since there is nothing DocuFlow can change.
    assert "runtime" in explained.lower()


def test_a_cause_the_cli_gives_is_passed_on_even_when_it_is_not_recognised() -> None:
    from app.services.lm_studio import explain_load_failure

    explained = explain_load_failure(
        "Failed to load model.",
        "Error: Failed to load model.\n\n (X) CAUSE \n\nerror loading model: tensor 'blk.0' not found\n",
    )

    assert "tensor 'blk.0' not found" in explained


def test_nothing_from_the_cli_leaves_the_original_message_alone() -> None:
    from app.services.lm_studio import explain_load_failure

    assert explain_load_failure("Something went wrong", "") == "Something went wrong"
    assert explain_load_failure("Something went wrong", "Loading 10%\nLoading 20%") == (
        "Something went wrong"
    )


@pytest.mark.asyncio
async def test_a_large_model_gets_more_than_one_second_chance_at_the_image(monkeypatch) -> None:
    """The vision path of a big model on CPU often fails once and then works.

    qwen3.6-35b-a3b needs 95 seconds to look at a blank warm-up page, and its
    first attempt after loading fails; the second succeeds. Giving up after one
    retry left a usable model reported as broken.
    """
    client = LMStudioClient("http://127.0.0.1:1234")
    monkeypatch.setattr(
        LMStudioClient,
        "_fetch_model_items",
        make_items(item("big", "Q4_K_M", 20.5, vision=True)),
    )
    monkeypatch.setattr(LMStudioClient, "_load_large_model_with_cli", lambda self, model: _load_ms())
    monkeypatch.setattr(LMStudioClient, "_reload_large_model_with_cli", lambda self, model: _load_ms())
    monkeypatch.setattr("app.services.lm_studio.asyncio.sleep", lambda seconds: _noop())

    attempts = {"count": 0}

    async def fails_twice(self, model, entities, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise LMStudioError("LM Studio stopped while processing the document image.")

    monkeypatch.setattr(LMStudioClient, "_warm_up_structured_output", fails_twice)

    report = await client.load_and_warm_model("big")

    assert report["status"] == "ready"
    assert report["preparation_attempts"] == 3


@pytest.mark.asyncio
async def test_a_model_that_never_manages_it_still_fails(monkeypatch) -> None:
    client = LMStudioClient("http://127.0.0.1:1234")
    monkeypatch.setattr(
        LMStudioClient,
        "_fetch_model_items",
        make_items(item("big", "Q4_K_M", 20.5, vision=True)),
    )
    monkeypatch.setattr(LMStudioClient, "_load_large_model_with_cli", lambda self, model: _load_ms())
    monkeypatch.setattr(LMStudioClient, "_reload_large_model_with_cli", lambda self, model: _load_ms())
    monkeypatch.setattr("app.services.lm_studio.asyncio.sleep", lambda seconds: _noop())

    async def always_fails(self, model, entities, **kwargs):
        raise LMStudioError("LM Studio stopped while processing the document image.")

    monkeypatch.setattr(LMStudioClient, "_warm_up_structured_output", always_fails)

    with pytest.raises(LMStudioError, match="document image"):
        await client.load_and_warm_model("big")


async def _load_ms() -> int:
    return 1


def test_cli_output_is_decoded_as_utf8_whatever_the_console_codepage_is(monkeypatch) -> None:
    """`lms` prints spinner and box characters that cp1252 cannot decode.

    Without an explicit encoding, Python decodes a subprocess's output with the
    console codepage, and the reader thread dies with UnicodeDecodeError before
    anything is read — turning a working load into a mystery.
    """
    import subprocess

    from app.services import lm_studio

    captured: dict = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(lm_studio.subprocess, "run", fake_run)
    monkeypatch.setattr(lm_studio.shutil, "which", lambda name: "lms")

    import asyncio

    asyncio.run(lm_studio.LMStudioClient("http://127.0.0.1:1234")._cli_load_failure_cause("m"))

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"

"""Loading a model on a machine that has no `lms` on PATH.

The chain that broke: without the CLI the hardware cannot be surveyed, an
unreadable machine is treated as the careful case, the careful case wants the
CPU-safe profile, and that profile was applied through the CLI. So the one
thing missing made every model unloadable — including the small ones that
never needed the profile in the first place.

The profile is mostly a load configuration, and LM Studio's REST API takes a
load configuration. Only holding the layers off the GPU needs the CLI.
"""

import pytest

from app.services.host import parse_survey
from app.services.lm_studio import LMStudioClient


LAPTOP = parse_survey(
    """Survey by llama.cpp-win-x86_64-vulkan-avx2 (2.29.1)
GPU/ACCELERATORS                             VRAM
Intel(R) UHD Graphics (Vulkan, Integrated)   19.82 GiB

CPU: x86_64 (AVX, AVX2)
RAM: 39.64 GiB
"""
)


def big_model() -> dict:
    return {
        "type": "llm",
        "key": "big/model",
        "display_name": "Big",
        "quantization": {"name": "Q4_K_M"},
        "size_bytes": int(20 * 1024**3),
        "params_string": "35B",
        "capabilities": {"vision": False},
        "loaded_instances": [],
    }


@pytest.fixture
def client(monkeypatch) -> LMStudioClient:
    client = LMStudioClient("http://127.0.0.1:1234")

    async def items(self):
        return [big_model()]

    async def host(self):
        return LAPTOP

    async def warm(self, *args, **kwargs):
        return None

    monkeypatch.setattr(LMStudioClient, "_fetch_model_items", items)
    monkeypatch.setattr(LMStudioClient, "host_capabilities", host)
    monkeypatch.setattr(LMStudioClient, "_warm_up_structured_output", warm)
    monkeypatch.setattr(LMStudioClient, "_await_ready", warm, raising=False)
    return client


def without_cli(monkeypatch) -> None:
    monkeypatch.setattr("app.services.lm_studio.shutil.which", lambda name: None)


def with_cli(monkeypatch) -> None:
    monkeypatch.setattr("app.services.lm_studio.shutil.which", lambda name: r"C:\lms.exe")


@pytest.mark.asyncio
async def test_a_machine_without_the_cli_can_still_load_a_model(client, monkeypatch) -> None:
    without_cli(monkeypatch)
    posted: list[tuple[str, dict]] = []

    async def post(self, path, payload, timeout):
        posted.append((path, payload))
        return {"load_time_seconds": 1.0}

    monkeypatch.setattr(LMStudioClient, "_post_json", post)
    report = await client.load_and_warm_model("big/model", skip_warmup=True)

    assert report["status"] == "ready"
    assert any(path == "/api/v1/models/load" for path, _ in posted)


@pytest.mark.asyncio
async def test_the_part_of_the_profile_rest_can_apply_is_applied(client, monkeypatch) -> None:
    without_cli(monkeypatch)
    posted: list[dict] = []

    async def post(self, path, payload, timeout):
        posted.append(payload)
        return {"load_time_seconds": 1.0}

    monkeypatch.setattr(LMStudioClient, "_post_json", post)
    await client.load_and_warm_model("big/model", skip_warmup=True)

    load = next(payload for payload in posted if payload.get("model") == "big/model")
    assert load["context_length"] == 8192
    assert load["parallel"] == 1
    assert load["offload_kv_cache_to_gpu"] is False


@pytest.mark.asyncio
async def test_the_report_does_not_claim_a_profile_it_could_not_fully_apply(
    client, monkeypatch
) -> None:
    """Holding the layers off the GPU is the CLI's part, and it did not run."""
    without_cli(monkeypatch)

    async def post(self, path, payload, timeout):
        return {"load_time_seconds": 1.0}

    monkeypatch.setattr(LMStudioClient, "_post_json", post)
    report = await client.load_and_warm_model("big/model", skip_warmup=True)
    assert report["profile"] == "compatibility_partial"


@pytest.mark.asyncio
async def test_with_the_cli_present_nothing_changes(client, monkeypatch) -> None:
    with_cli(monkeypatch)
    used_cli: list[str] = []

    async def cli(self, model):
        used_cli.append(model)
        return 1234

    monkeypatch.setattr(LMStudioClient, "_load_large_model_with_cli", cli)
    report = await client.load_and_warm_model("big/model", skip_warmup=True)

    assert used_cli == ["big/model"]
    assert report["profile"] == "compatibility"


# -- the vision retry -----------------------------------------------------------


def test_the_retry_recognises_the_failure_the_engine_actually_reports() -> None:
    """A large model often fails its first image and succeeds on the next.

    The condition for retrying used to match a sentence that has since been
    rewritten, which left the retry unreachable without a test noticing. It
    matches the message the engine mapper produces now, and this test holds
    the two together.
    """
    from app.services.lm_studio import LMStudioClient, is_vision_startup_failure

    reported = LMStudioClient._friendly_engine_error(
        "slot operator(): failed to process image, res = -1", "LM Studio rejected the request"
    )
    assert is_vision_startup_failure(reported)


def test_an_unrelated_failure_is_not_retried() -> None:
    from app.services.lm_studio import is_vision_startup_failure

    assert not is_vision_startup_failure("No Gemini API key is configured.")
    assert not is_vision_startup_failure("")


@pytest.mark.asyncio
async def test_a_vision_retry_works_without_the_cli(client, monkeypatch) -> None:
    """The model is already loaded; the retry is another attempt at the image."""
    from app.services.lm_studio import LMStudioError

    without_cli(monkeypatch)

    async def post(self, path, payload, timeout):
        return {"load_time_seconds": 1.0}

    attempts = {"n": 0}

    async def warm(self, *args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise LMStudioError(
                "LM Studio failed to encode the page image. Its log reports the Vulkan "
                "device being lost inside the vision encoder."
            )
        return None

    monkeypatch.setattr(LMStudioClient, "_post_json", post)
    monkeypatch.setattr(LMStudioClient, "_warm_up_structured_output", warm)
    monkeypatch.setattr("app.services.lm_studio.VISION_WARMUP_SETTLE_SECONDS", 0)

    def vision_model(self):
        item = big_model()
        item["capabilities"] = {"vision": True}
        return item

    async def items(self):
        return [vision_model(self)]

    monkeypatch.setattr(LMStudioClient, "_fetch_model_items", items)

    report = await client.load_and_warm_model("big/model")
    assert report["status"] == "ready"
    assert attempts["n"] == 2

"""Finding the models installed on whatever machine this is.

DocuFlow never touches model files: it asks LM Studio. That request is the
single point where a working install can look like an empty one, so what it
does when the answer is not the expected shape matters more than the happy
path.

Two things went wrong on a second machine. Only LM Studio's own
`/api/v1/models` was tried, which arrived in a later version than the
OpenAI-compatible `/v1/models` every build has. And every failure — refused
connection, 404, timeout — was reported as "LM Studio is not reachable",
which sends someone to check a server that is already running.
"""

import httpx
import pytest

from app.services.lm_studio import LMStudioClient, LMStudioError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )


def answering(routes: dict[str, FakeResponse | Exception], seen: list[str] | None = None):
    """A client whose GETs are answered from a table of paths."""

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url: str, **kwargs):
            path = url.split("1234", 1)[-1]
            if seen is not None:
                seen.append(path)
            answer = routes.get(path)
            if answer is None:
                return FakeResponse(404, {})
            if isinstance(answer, Exception):
                raise answer
            return answer

    return FakeClient


NATIVE = {
    "/api/v1/models": FakeResponse(
        200,
        {
            "models": [
                {
                    "type": "llm",
                    "key": "qwen/qwen3-vl-4b",
                    "display_name": "Qwen3 VL 4B",
                    "quantization": {"name": "Q4_K_M"},
                    "size_bytes": 3_300_000_000,
                    "params_string": "4B",
                    "capabilities": {"vision": True},
                    "loaded_instances": [],
                }
            ]
        },
    )
}

OPENAI_ONLY = {
    "/v1/models": FakeResponse(
        200, {"data": [{"id": "qwen/qwen3-vl-4b"}, {"id": "some-embedding-model"}]}
    )
}


@pytest.fixture
def client() -> LMStudioClient:
    return LMStudioClient("http://127.0.0.1:1234")


async def models_of(client: LMStudioClient) -> list:
    return await client.list_models()


# -- the happy path stays the happy path --------------------------------------


@pytest.mark.asyncio
async def test_lm_studios_own_api_is_used_when_it_answers(client, monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(httpx, "AsyncClient", answering(NATIVE, seen))
    models = await models_of(client)
    assert [model.id for model in models] == ["qwen/qwen3-vl-4b"]
    assert models[0].vision is True
    assert models[0].size_bytes == 3_300_000_000
    # The richer endpoint answered, so there is no reason to ask the other one.
    assert "/v1/models" not in seen


# -- an older LM Studio -------------------------------------------------------


@pytest.mark.asyncio
async def test_an_install_without_the_native_api_still_lists_its_models(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", answering(OPENAI_ONLY))
    models = await models_of(client)
    assert "qwen/qwen3-vl-4b" in [model.id for model in models]


@pytest.mark.asyncio
async def test_what_the_older_api_cannot_say_is_not_invented(client, monkeypatch) -> None:
    """It reports ids and nothing else, so nothing else may be claimed."""
    monkeypatch.setattr(httpx, "AsyncClient", answering(OPENAI_ONLY))
    model = next(m for m in await models_of(client) if m.id == "qwen/qwen3-vl-4b")
    assert model.capabilities_known is False
    assert model.size_bytes is None
    assert model.quantization is None


@pytest.mark.asyncio
async def test_a_model_of_unknown_capability_is_not_labelled_text_only(
    client, monkeypatch
) -> None:
    """Tagging it TEXT ONLY would hide it from every vision pipeline."""
    monkeypatch.setattr(httpx, "AsyncClient", answering(OPENAI_ONLY))
    model = next(m for m in await models_of(client) if m.id == "qwen/qwen3-vl-4b")
    assert model.vision is False and model.capabilities_known is False


# -- failures that say what happened ------------------------------------------


@pytest.mark.asyncio
async def test_a_refused_connection_says_so_and_names_the_endpoint(
    client, monkeypatch
) -> None:
    refused = httpx.ConnectError("connection refused")
    monkeypatch.setattr(
        httpx, "AsyncClient", answering({"/api/v1/models": refused, "/v1/models": refused})
    )
    with pytest.raises(LMStudioError) as raised:
        await models_of(client)
    message = str(raised.value)
    # The address it tried, and the fact that nothing answered there — not a
    # verdict on whether LM Studio is installed.
    assert "127.0.0.1:1234" in message
    assert "listening" in message.lower()
    assert "not reachable" not in message.lower()


@pytest.mark.asyncio
async def test_a_server_that_answers_but_has_no_models_is_not_an_error(
    client, monkeypatch
) -> None:
    """An empty install is a fact about the machine, not a failure to report."""
    monkeypatch.setattr(httpx, "AsyncClient", answering({"/v1/models": FakeResponse(200, {"data": []})}))
    assert await models_of(client) == []


@pytest.mark.asyncio
async def test_an_unexpected_status_is_reported_as_the_status_it_was(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        answering({"/api/v1/models": FakeResponse(500, {}), "/v1/models": FakeResponse(500, {})}),
    )
    with pytest.raises(LMStudioError) as raised:
        await models_of(client)
    # Not "not reachable": it was reached, and it answered.
    assert "500" in str(raised.value)
    assert "not reachable" not in str(raised.value)

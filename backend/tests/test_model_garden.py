"""Partner protocols and accounting must survive failures, caches and retries."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api import deps
from app.domain.billing import UsageRecord
from app.domain.models import AppSettings, EntityDefinition, ModelGardenSettings, PromptConfiguration
from app.services import gcp_runtime
from app.services.billing import MeteredProvider, UsageStore, account, tariff
from app.services.errors import ProviderError
from app.services.model_garden import ModelGardenClient, generation_schema, grok_output_tokens

PROMPTS = PromptConfiguration(entities=[EntityDefinition(name="invoice_number", format="text", description="Invoice number")])
ANSWER = json.dumps({"invoice_number": "TEST-1", "confidence": {"invoice_number": "high"}})


def record(model="grok-4.7", publisher="xai", location="global"):
    return UsageRecord(id="attempt", group_id="group", created_at="2026-10-06", model=model,
                       provider="model_garden", publisher=publisher, location=location,
                       step="llm_extract", document="synthetic.pdf", status="succeeded")


@pytest.mark.parametrize("model,location,input_rate,output_rate", [
    ("claude-sonnet-5-5", "eu", 2.2, 11), ("claude-sonnet-5-5", "global", 2, 10),
    ("claude-opus-5-5", "eu", 4.4, 22), ("claude-opus-5-5", "global", 4, 20),
])
def test_claude_prices_follow_the_model_garden_location(model, location, input_rate, output_rate):
    """A regional surcharge must not accidentally use the global tariff."""
    rates = tariff(model, location)
    assert (rates["input"], rates["output"]) == (input_rate, output_rate)


def test_grok_long_context_includes_cache_and_prices_the_whole_request():
    """The threshold includes cache hits and is not a marginal or run-level tier."""
    raw = {"prompt_tokens": 200001, "completion_tokens": 10,
           "prompt_tokens_details": {"cached_tokens": 100001}}
    result = account(record(), raw, 200)
    assert result.tariff["context_tier"] == ">200k"
    assert result.cost.total_usd == pytest.approx((100000 * 4 + 100001 + 10 * 12) / 1000000)
    assert tariff("grok-4.7", "global", 200000)["input"] == 2


@pytest.mark.parametrize("total,expected", [(684, 96), (612, 24), (600, None)])
def test_grok_output_uses_the_reported_total_without_counting_reasoning_twice(total, expected):
    """The Model Garden smoke reports reasoning outside completion tokens."""
    usage = {"prompt_tokens": 588, "completion_tokens": 24, "total_tokens": total,
             "completion_tokens_details": {"reasoning_tokens": 72}}
    assert grok_output_tokens(usage) == expected


def test_claude_cache_categories_are_priced_independently():
    """Cache reads and writes are additional to Anthropic input_tokens."""
    raw = {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 1000,
           "cache_creation_input_tokens": 150, "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 50}}
    result = account(record("claude-sonnet-5-5", "anthropic", "eu"), raw, 200)
    assert result.cost.total_usd == pytest.approx((220 + 220 + 220 + 275 + 220) / 1000000)
    assert result.raw_usage == raw


def test_missing_usage_and_unspecified_cache_ttl_are_never_free():
    """An incomplete response must not become a falsely complete zero estimate."""
    assert account(record(), {}, 200).cost.total_usd is None
    result = account(record("claude-opus-5-5", "anthropic", "eu"),
        {"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 50}, 200)
    assert result.cost.status == "partial"
    assert result.cost.total_usd is None
    assert result.cost.known_usd > 0


def test_refusals_are_free_but_disconnects_have_unknown_cost():
    """Google's 4xx/5xx rule cannot be applied to requests with no HTTP status."""
    assert account(record(), {}, 403).cost.total_usd == 0
    assert account(record(), {}, None).cost.total_usd is None


@pytest.mark.parametrize("model,location", [("claude-sonnet-5-5", "eu"), ("claude-opus-5-5", "global"), ("grok-4.7", "global")])
@pytest.mark.asyncio
async def test_partner_requests_use_google_identity_and_the_correct_schema(monkeypatch, model, location):
    """No partner API key, Gemini schema dialect or forced tool may leak into requests."""
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    monkeypatch.setattr(gcp_runtime, "access_token", AsyncMock(return_value="test-token"))
    seen = []
    def respond(request):
        body = json.loads(request.content)
        seen.append((request, body))
        assert request.headers["authorization"] == "Bearer test-token"
        if model.startswith("claude"):
            assert request.url.path.endswith(f"/publishers/anthropic/models/{model}:rawPredict")
            assert body["thinking"] == {"type": "adaptive"}
            assert "tool_choice" not in body and "temperature" not in body
            return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": "private"}, {"type": "text", "text": ANSWER}],
                "usage": {"input_tokens": 100, "output_tokens": 20}, "stop_reason": "end_turn"})
        assert body["model"] == "xai/grok-4.7"
        assert body["reasoning_effort"] == "low"
        return httpx.Response(200, json={"choices": [{"message": {"content": ANSWER}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 150,
                      "completion_tokens_details": {"reasoning_tokens": 30}}})
    original = httpx.AsyncClient
    monkeypatch.setattr("app.services.model_garden.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    client = ModelGardenClient(ModelGardenSettings(claude_location=location))
    result = await client.extract_entities(model, ["aW1hZ2U="], PROMPTS, "1", 1, 1)
    assert result["invoice_number"].value == "TEST-1"
    assert client.last_prediction_stats["completion_tokens"] == (20 if model.startswith("claude") else 50)
    assert len(seen) == 1
    schema = generation_schema(PROMPTS.entities)
    assert schema["properties"]["invoice_number"]["type"] == ["string", "null"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_a_paid_invalid_answer_remains_in_history_and_is_not_retried(tmp_path, monkeypatch):
    """Response validation must never erase the charge of a successful HTTP call."""
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    context = deps.pipeline_context(AppSettings(provider="model_garden", model="claude-sonnet-5-5"), "synthetic.pdf", b"synthetic")
    context.evaluation_id = 5
    class Invalid:
        http_status = 200
        request_id = "request-1"
        last_usage = {"input_tokens": 100, "output_tokens": 20}
        last_prediction_stats = {"prompt_tokens": 100, "completion_tokens": 20}
        calls = 0
        async def extract_entities(self, *args):
            self.calls += 1
            raise ProviderError("Invalid JSON")
    client = Invalid()
    with pytest.raises(ProviderError, match="Invalid JSON"):
        await MeteredProvider(client, context).extract_entities(context.model, [], PROMPTS, "1", 1, 1)
    detail = context.usage_store.detail(evaluation_id=5)
    assert client.calls == 1 and len(detail.records) == 1
    assert detail.records[0].request_id == "request-1"
    assert detail.cost.total_usd == pytest.approx(.00044)
    context.usage_store.bind_run(context.usage_group, 8)
    assert context.usage_store.detail(run_id=8).cost == detail.cost


@pytest.mark.asyncio
async def test_retry_records_each_attempt_and_never_switches_endpoint(monkeypatch):
    """A 429 is retried only on the selected model, and every attempt is auditable."""
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    monkeypatch.setattr("app.services.billing.asyncio.sleep", AsyncMock())
    context = deps.pipeline_context(AppSettings(provider="model_garden", model="claude-opus-5-5"), "synthetic.pdf", b"")
    class Busy:
        http_status = 429
        last_usage = None
        last_prediction_stats = None
        calls = 0
        async def extract_entities(self, model, *args):
            assert model == "claude-opus-5-5"
            self.calls += 1
            raise ProviderError("Quota exceeded")
    client = Busy()
    with pytest.raises(ProviderError):
        await MeteredProvider(client, context).extract_entities(context.model, [], PROMPTS, "1", 1, 1)
    detail = context.usage_store.detail(group_id=context.usage_group)
    assert client.calls == 3 and len(detail.records) == 3 and detail.cost.total_usd == 0
    assert {item.location for item in detail.records} == {"eu"}


def test_grok_reservations_are_shared_between_store_instances(tmp_path, monkeypatch):
    """Two workers cannot both reserve beyond the same output quota."""
    monkeypatch.setenv("DOCUFLOW_GROK_OUTPUT_TPM", "5000")
    store = UsageStore(tmp_path / "usage.db")
    first = record().model_copy(update={"status": "pending"})
    assert store.reserve_grok(first, "test/global/grok", 4096) == 0
    other = UsageStore(tmp_path / "usage.db")
    second = record().model_copy(update={"id": "second", "status": "pending"})
    assert other.reserve_grok(second, "test/global/grok", 4096) > 0


def test_a_disconnected_grok_request_keeps_its_quota_reservation(tmp_path, monkeypatch):
    """Unknown consumption must not let another worker overspend the token quota."""
    monkeypatch.setenv("DOCUFLOW_GROK_OUTPUT_TPM", "5000")
    store = UsageStore(tmp_path / "usage.db")
    first = record().model_copy(update={"status": "pending"})
    assert store.reserve_grok(first, "test/global/grok", 4096) == 0
    first = account(first, {}, None)
    first.status = "failed"
    store.save(first, "test/global/grok")
    second = record().model_copy(update={"id": "second"})
    assert store.reserve_grok(second, "test/global/grok", 4096) > 0


def test_model_garden_profiles_pin_the_project_region_and_generation_controls(monkeypatch):
    """Worker retries must not silently inherit a newly selected endpoint."""
    from app.services.model_garden import find_partner
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "original-project")
    settings = AppSettings(provider="model_garden", model="claude-sonnet-5-5")
    profile = deps.execution_profile(settings, None, find_partner(settings.model))
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "new-project")
    settings.model_garden.claude_effort = "high"
    settings.model_garden.claude_max_output_tokens = 8000
    context = deps.pipeline_context(settings, "a.pdf", b"", recorded_profile=profile)
    assert (context.model_garden_project, context.model_garden_location) == ("original-project", "eu")
    assert context.model_garden_settings.claude_effort == "low"
    assert context.model_garden_settings.claude_max_output_tokens == 4096


def test_workspace_persists_partner_usage_and_exposes_the_original_tariff(tmp_path, monkeypatch):
    """The complete upload pipeline must bind its charges to the saved Workspace run."""
    import pymupdf
    from fastapi.testclient import TestClient
    from app import main
    from app.domain.models import FieldExtraction
    from app.services.settings_store import SettingsStore
    from app.services.run_store import RunStore
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    path = tmp_path / "app.db"
    monkeypatch.setattr(deps, "DATABASE_PATH", path)
    monkeypatch.setattr(deps, "run_store", RunStore(path))
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(provider="model_garden", model="grok-4.7", prompts=PROMPTS))
    monkeypatch.setattr(deps, "settings_store", settings)
    async def extract(self, *args, **kwargs):
        self.http_status = 200
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 150,
                           "completion_tokens_details": {"reasoning_tokens": 30}}
        self.last_prediction_stats = {"prompt_tokens": 100, "completion_tokens": 50}
        return {"invoice_number": FieldExtraction(value="TEST-1", confidence="high")}
    monkeypatch.setattr(ModelGardenClient, "extract_entities", extract)
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Synthetic invoice number TEST-1")
    content = pdf.tobytes()
    pdf.close()
    with TestClient(main.app) as client:
        response = client.post("/api/documents/extract", files={"file": ("synthetic.pdf", content, "application/pdf")})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["cost"]["total_usd"] == pytest.approx(.0005)
        usage = client.get(f'/api/runs/{body["run_id"]}/usage').json()
        assert usage["records"][0]["raw_usage"]["total_tokens"] == 150
        assert usage["records"][0]["tariff"]["output"] == 6
        history = client.get(f'/api/runs/{body["run_id"]}').json()
        assert history["provider"] == "model_garden"
        assert history["cost"] == body["cost"]


@pytest.mark.asyncio
async def test_evaluation_cost_keeps_a_failed_paid_attempt_and_its_retry(tmp_path, monkeypatch):
    """Overwriting a document result during retry must not erase earlier charges."""
    from app.evaluation.store import EvaluationStore
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    path = tmp_path / "app.db"
    monkeypatch.setattr(deps, "DATABASE_PATH", path)
    evaluations = EvaluationStore(path)
    evaluation_id = evaluations.start(dataset="synthetic", model="grok-4.7", prompts=PROMPTS, total_documents=1, provider="model_garden")
    context = deps.pipeline_context(AppSettings(provider="model_garden", model="grok-4.7"), "synthetic.pdf", b"")
    context.evaluation_id = evaluation_id
    first = account(record().model_copy(update={"evaluation_id": evaluation_id, "status": "failed"}),
                    {"prompt_tokens": 100, "completion_tokens": 20}, 200)
    context.usage_store.save(first, "test")
    evaluations.record_document_failure(evaluation_id, "synthetic.pdf", "Invalid JSON")
    assert evaluations.get_evaluation(evaluation_id).cost.total_usd == pytest.approx(.00032)
    second = first.model_copy(update={"id": "retry", "status": "succeeded"})
    context.usage_store.save(second, "test")
    assert evaluations.get_evaluation(evaluation_id).cost.total_usd == pytest.approx(.00064)


CLAUDE_QUOTA = ("Quota exceeded for aiplatform.googleapis.com/eu_multi_region_online_prediction_requests_per_base_model "
                "with base model: anthropic-claude-sonnet. Please submit a quota increase request. "
                "https://cloud.google.com/vertex-ai/docs/generative-ai/quotas-genai.")


def test_settings_saved_with_one_output_limit_give_it_to_each_publisher():
    """Settings written before the limits were split must still load, unchanged in effect."""
    loaded = ModelGardenSettings.model_validate({"claude_location": "eu", "max_output_tokens": 2048})
    assert (loaded.claude_max_output_tokens, loaded.grok_max_output_tokens) == (2048, 2048)
    assert loaded.output_limit("anthropic") == loaded.output_limit("xai") == 2048


def test_a_quota_refusal_is_reported_as_what_happened_without_googles_advice():
    from app.services.hosted_checks import refusal_fact
    fact = refusal_fact(429, CLAUDE_QUOTA)
    assert "eu_multi_region_online_prediction_requests_per_base_model" in fact
    assert "anthropic-claude-sonnet" in fact
    assert "submit" not in fact.lower() and "http" not in fact


@pytest.mark.asyncio
async def test_an_extraction_refused_for_quota_names_the_model_location_and_quota(monkeypatch):
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    monkeypatch.setattr(gcp_runtime, "access_token", AsyncMock(return_value="test-token"))
    original = httpx.AsyncClient
    monkeypatch.setattr("app.services.model_garden.httpx.AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {"code": 429, "message": CLAUDE_QUOTA}})), **kwargs))
    with pytest.raises(ProviderError) as raised:
        await ModelGardenClient(ModelGardenSettings()).extract_entities("claude-sonnet-5-5", [], PROMPTS, "1", 1, 1)
    message = str(raised.value)
    assert message.startswith("Claude Sonnet 5.5 in eu, project test-project:")
    assert "requests_per_base_model" in message and "submit" not in message.lower()


@pytest.mark.parametrize("status,expected", [(200, "answering"), (429, "no_quota"), (404, "not_offered"), (403, "refused")])
@pytest.mark.asyncio
async def test_a_check_asks_for_one_token_and_records_the_answer_per_location(monkeypatch, status, expected):
    from app.services import hosted_checks
    hosted_checks.clear()
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    monkeypatch.setattr(gcp_runtime, "access_token", AsyncMock(return_value="test-token"))
    seen = []
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(status, json={"content": []} if status == 200 else {"error": {"message": CLAUDE_QUOTA}})
    original = httpx.AsyncClient
    monkeypatch.setattr("app.services.model_garden.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    check = await ModelGardenClient(ModelGardenSettings()).check("claude-opus-5-5", "global")
    assert seen[0]["max_tokens"] == 1 and "thinking" not in seen[0]
    assert (check.status, check.location, check.publisher) == (expected, "global", "anthropic")
    assert bool(check.detail) is (status != 200)
    assert hosted_checks.all_checks() == [check]


@pytest.mark.asyncio
async def test_grok_is_never_asked_in_a_location_without_an_endpoint(monkeypatch):
    monkeypatch.setenv("DOCUFLOW_MODEL_GARDEN_PROJECT", "test-project")
    monkeypatch.setattr("app.services.model_garden.httpx.AsyncClient", lambda **kwargs: pytest.fail("no request expected"))
    check = await ModelGardenClient(ModelGardenSettings()).check("grok-4.7", "eu")
    assert check.status == "not_offered"


def test_a_gemini_location_chosen_in_llm_replaces_the_deployments_and_is_recorded(monkeypatch):
    """Gemini 3.1 Pro Preview is offered in global only; the run must say where it ran."""
    from app.services.gemini import GeminiClient, find_model
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_PROJECT", "test-project")
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_LOCATION", "eu")
    assert "/locations/eu/" in GeminiClient("")._url("gemini-3.8-flash")
    assert "aiplatform.googleapis.com/v1/projects/test-project/locations/global/" in GeminiClient("", location="global")._url("gemini-3.1-pro-preview")
    settings = AppSettings(provider="gemini", model="gemini-3.1-pro-preview")
    settings.gemini.location = "global"
    profile = deps.execution_profile(settings, None, find_model(settings.model))
    assert profile.location == "global"
    settings.gemini.location = None
    assert deps.pipeline_context(settings, "a.pdf", b"", recorded_profile=profile).gemini_location == "global"
    assert deps.key_status(settings).vertex_location == "eu"


def test_a_gemini_429_states_what_google_refused_without_its_advice():
    from app.services.gemini import GeminiClient, GeminiError
    response = httpx.Response(429, json={"error": {"message": "Resource exhausted. Please try again later. Please refer to https://cloud.google.com/x for more details."}})
    with pytest.raises(GeminiError) as raised:
        GeminiClient("key")._raise_for_status(response)
    assert str(raised.value) == "Gemini: Google refused the request with 429 (rate limit or quota). Resource exhausted."


@pytest.mark.parametrize("location,on,expected", [
    ("global", "2026-10-06", (.75, 3.75, .075)), ("eu", "2026-10-06", (.825, 4.125, .0825)),
    ("eu", "2027-01-01", (1.65, 8.25, .165)),
])
def test_gemini_is_priced_by_location_and_by_the_day_of_the_request(location, on, expected):
    """Google prices Gemini 10% higher outside global, and Flash doubles on 1 January 2027."""
    rates = tariff("gemini-3.8-flash", location, on=on)
    assert (rates["input"], rates["output"], rates["cache_read"]) == expected


def test_a_rate_edited_in_llm_replaces_googles_up_to_200k_of_context():
    edited = {"claude-sonnet-5-5@eu": {"input_per_million": 3, "output_per_million": None, "cache_read_per_million": .3}}
    rates = tariff("claude-sonnet-5-5", "eu", rates=edited)
    assert (rates["input"], rates["output"], rates["cache_read"], rates["source"]) == (3, None, .3, "LLM settings")
    # Another location keeps Google's rate; a long context uses Google's long-context table.
    assert tariff("claude-sonnet-5-5", "global", rates=edited)["input"] == 2
    assert tariff("claude-sonnet-5-5", "eu", 200001, rates=edited)["input"] == 2.2
    # A removed rate is an unknown cost, never a free one.
    cost = account(record("claude-sonnet-5-5", "anthropic", "eu"), {"input_tokens": 10, "output_tokens": 10}, 200, edited).cost
    assert cost.status == "partial" and cost.total_usd is None


def test_gemini_usage_separates_cached_input_and_bills_thinking_as_output():
    raw = {"promptTokenCount": 1000, "cachedContentTokenCount": 400, "candidatesTokenCount": 50, "thoughtsTokenCount": 150}
    item = account(record("gemini-3.8-flash", "google", "global"), raw, 200)
    assert (item.input_tokens, item.cached_tokens, item.output_tokens, item.reasoning_tokens) == (600, 400, 200, 150)
    rates = item.tariff
    assert item.cost.total_usd == pytest.approx((600 * rates["input"] + 400 * rates["cache_read"] + 200 * rates["output"]) / 1e6)


@pytest.mark.asyncio
async def test_a_gemini_429_is_retried_and_every_attempt_recorded(tmp_path, monkeypatch):
    """Gemini's shared quota in global refuses now and then; the run must not fail on the first refusal."""
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_PROJECT", "test-project")
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_LOCATION", "eu")
    monkeypatch.setattr("app.services.billing.asyncio.sleep", AsyncMock())
    settings = AppSettings(provider="gemini", model="gemini-3.8-flash")
    settings.gemini.location = "global"
    context = deps.pipeline_context(settings, "synthetic.pdf", b"")
    class Shared:
        http_status = None
        last_usage = None
        last_prediction_stats = None
        calls = 0
        async def extract_entities(self, *args):
            self.calls += 1
            if self.calls == 1:
                self.http_status = 429
                raise ProviderError("Gemini: Google refused the request with 429 (rate limit or quota).")
            self.http_status, self.last_usage = 200, {"promptTokenCount": 100, "candidatesTokenCount": 10}
            return {"invoice_number": "TEST-1"}
    client = Shared()
    assert await MeteredProvider(client, context).extract_entities(context.model, [], PROMPTS, "1", 1, 1) == {"invoice_number": "TEST-1"}
    detail = context.usage_store.detail(group_id=context.usage_group)
    assert [item.status for item in detail.records] == ["failed", "succeeded"]
    assert {(item.provider, item.publisher, item.project, item.location) for item in detail.records} == {("gemini", "google", "test-project", "global")}
    assert detail.cost.status == "complete" and detail.cost.total_usd > 0


def test_settings_saved_with_one_effort_give_it_to_claude():
    loaded = ModelGardenSettings.model_validate({"effort": "high", "max_output_tokens": 2048})
    assert (loaded.claude_effort, loaded.grok_effort) == ("high", "low")
    assert loaded.effort("anthropic") == "high" and loaded.effort("xai") == "low"


@pytest.mark.asyncio
async def test_the_gemini_output_limit_caps_thinking_models_and_old_profiles_stay_uncapped(monkeypatch):
    from app.services.gemini import GeminiClient
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_PROJECT", "test-project")
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_LOCATION", "eu")
    monkeypatch.setattr(gcp_runtime, "access_token", AsyncMock(return_value="test-token"))
    sent = []
    def respond(request):
        sent.append(json.loads(request.content)["generationConfig"])
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": ANSWER}]}, "finishReason": "STOP"}],
                                         "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})
    original = httpx.AsyncClient
    monkeypatch.setattr("app.services.gemini.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    await GeminiClient("", max_output_tokens=16000).extract_entities("gemini-3.8-flash", [], PROMPTS, "1", 1, 1, "text")
    await GeminiClient("").extract_entities("gemini-3.8-flash", [], PROMPTS, "1", 1, 1, "text")
    assert sent[0]["maxOutputTokens"] == 16000 and "maxOutputTokens" not in sent[1]
    from app.services.gemini import find_model
    settings = AppSettings(provider="gemini", model="gemini-3.8-flash")
    profile = deps.execution_profile(settings, None, find_model(settings.model))
    assert profile.max_output_tokens == 16000
    old = profile.model_copy(update={"max_output_tokens": None})
    assert deps.pipeline_context(settings, "a.pdf", b"", recorded_profile=old).gemini_max_output_tokens is None


def test_every_selectable_hosted_model_has_a_published_rate_where_it_is_offered():
    from app.services.billing import hosted_offers, published
    offers = hosted_offers()
    assert ("gemini-3.1-pro-preview", "global") in offers and ("gemini-3.1-pro-preview", "eu") not in offers
    assert ("grok-4.7", "eu") not in offers
    assert all(published(model, location)[0] is not None for model, location in offers)

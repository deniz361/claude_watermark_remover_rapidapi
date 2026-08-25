"""Tests for the RapidAPI-facing service."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cleaning import REWRITE_UNAVAILABLE
from config import Settings, get_settings
from main import app, rate_limiter

PROXY_SECRET = "test-proxy-secret"
HIDDEN = "A tidy draft\u200b can still carry soft\u00adhyphens."


def build_settings(**overrides) -> Settings:
    defaults = dict(
        proxy_secret=PROXY_SECRET,
        thorough_tiers=frozenset({"PRO", "ULTRA", "MEGA", "CUSTOM"}),
        max_characters=1_000,
        thorough_max_characters=100,
        rate_limit=5,
        rate_window_seconds=60,
        openai_api_key="test-key",
        openai_model="test-model",
        openai_timeout_seconds=5.0,
        openai_max_output_tokens=100,
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def client():
    rate_limiter.reset()
    # The override must take no arguments, or FastAPI treats its parameters as
    # request fields to validate.
    app.dependency_overrides[get_settings] = lambda: build_settings()
    yield TestClient(app)
    app.dependency_overrides.clear()
    rate_limiter.reset()


def configure(**overrides) -> None:
    app.dependency_overrides[get_settings] = lambda: build_settings(**overrides)


def post(client, payload, *, secret=PROXY_SECRET, user="alice", tier="PRO"):
    headers = {}
    if secret is not None:
        headers["X-RapidAPI-Proxy-Secret"] = secret
    if user is not None:
        headers["X-RapidAPI-User"] = user
    if tier is not None:
        headers["X-RapidAPI-Subscription"] = tier
    return client.post("/v1/remove-watermark", json=payload, headers=headers)


def test_careful_removes_hidden_characters_and_reports_them(client):
    response = post(client, {"text": HIDDEN, "mode": "careful"})
    body = response.json()

    assert response.status_code == 200
    assert body["text"] == "A tidy draft can still carry softhyphens."
    assert body["removed_characters"] == 2
    assert body["mode"] == "careful"
    assert {finding["codepoint"] for finding in body["findings"]} == {"U+200B", "U+00AD"}
    # Careful never rewrites, so the rewrite block is omitted entirely.
    assert "rewrite" not in body


def test_response_hides_internal_fields(client):
    body = post(client, {"text": HIDDEN}).json()

    # The Flask endpoint returns these; subscribers must not depend on them.
    for leaked in ("inspection_text", "billing", "source_characters"):
        assert leaked not in body


def test_emoji_sequences_are_preserved_not_removed(client):
    body = post(client, {"text": "family \U0001f468\u200d\U0001f469\u200d\U0001f467 here"}).json()

    assert body["removed_characters"] == 0
    assert "\u200d" in body["text"]
    assert all(finding["action"] == "preserved" for finding in body["findings"])


def test_request_without_the_proxy_secret_is_refused(client):
    response = post(client, {"text": HIDDEN}, secret=None)

    assert response.status_code == 403
    assert response.json()["code"] == "proxy_secret_invalid"


def test_request_with_a_wrong_proxy_secret_is_refused(client):
    response = post(client, {"text": HIDDEN}, secret="not-the-secret")

    assert response.status_code == 403
    assert response.json()["code"] == "proxy_secret_invalid"


def test_service_refuses_traffic_when_no_secret_is_configured(client):
    configure(proxy_secret="")
    response = post(client, {"text": HIDDEN}, secret="anything")

    assert response.status_code == 503
    assert response.json()["code"] == "proxy_secret_not_configured"


def test_thorough_is_withheld_from_the_free_tier(client):
    response = post(client, {"text": HIDDEN, "mode": "thorough"}, tier="BASIC")

    assert response.status_code == 403
    assert response.json()["code"] == "thorough_requires_paid_plan"


def test_thorough_is_withheld_when_the_tier_header_is_missing(client):
    """Rapid omits the header on some plans; that must fail closed."""
    response = post(client, {"text": HIDDEN, "mode": "thorough"}, tier=None)

    assert response.status_code == 403
    assert response.json()["code"] == "thorough_requires_paid_plan"


def test_thorough_reports_a_failed_rewrite_instead_of_erroring(client, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("cleaning.rewrite_text_with_openai", explode)
    response = post(client, {"text": HIDDEN, "mode": "thorough"})
    body = response.json()

    assert response.status_code == 200
    assert body["rewrite"] == {"applied": False, "reason": REWRITE_UNAVAILABLE}
    # The Unicode pass still ran on the original text.
    assert body["removed_characters"] == 2


def test_thorough_applies_the_rewrite_when_the_provider_responds(client, monkeypatch):
    monkeypatch.setattr(
        "cleaning.rewrite_text_with_openai",
        lambda *_a, **_k: "A neat draft\u200b still carries soft hyphens.",
    )
    body = post(client, {"text": HIDDEN, "mode": "thorough"}).json()

    assert body["rewrite"] == {"applied": True}
    assert body["text"] == "A neat draft still carries soft hyphens."


def test_thorough_is_unavailable_without_provider_credentials(client):
    configure(openai_api_key="")
    response = post(client, {"text": HIDDEN, "mode": "thorough"})

    assert response.status_code == 503
    assert response.json()["code"] == "thorough_unavailable"


def test_oversized_text_is_rejected_per_mode(client):
    # Over the thorough ceiling (100) but under the overall ceiling (1,000).
    long_text = "word " * 30
    assert 100 < len(long_text) < 1_000

    careful = post(client, {"text": long_text, "mode": "careful"})
    assert careful.status_code == 200

    thorough = post(client, {"text": long_text, "mode": "thorough"})
    assert thorough.status_code == 413
    assert thorough.json()["code"] == "text_too_large_for_thorough"

    configure(max_characters=10)
    assert post(client, {"text": long_text}).json()["code"] == "text_too_large"


def test_blank_and_invalid_payloads_use_the_shared_error_shape(client):
    blank = post(client, {"text": "   "})
    assert blank.status_code == 400
    assert blank.json()["code"] == "text_required"

    bad_mode = post(client, {"text": HIDDEN, "mode": "aggressive"})
    assert bad_mode.status_code == 400
    assert bad_mode.json()["code"] == "invalid_request"
    assert "mode" in bad_mode.json()["error"]

    missing = post(client, {"mode": "careful"})
    assert missing.status_code == 400
    assert missing.json()["code"] == "invalid_request"


def test_rate_limit_is_per_subscriber_and_sets_retry_after(client):
    for _ in range(5):
        assert post(client, {"text": HIDDEN}, user="alice").status_code == 200

    limited = post(client, {"text": HIDDEN}, user="alice")
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limit_reached"
    assert int(limited.headers["Retry-After"]) >= 1

    # A different subscriber is unaffected.
    assert post(client, {"text": HIDDEN}, user="bob").status_code == 200


def test_health_reports_configuration(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["proxy_secret_configured"] is True
    assert body["thorough_available"] is True


def test_openapi_document_is_publishable(client):
    raw = client.get("/openapi.json")
    spec = raw.json()
    operation = spec["paths"]["/v1/remove-watermark"]["post"]

    assert spec["info"]["title"] == "Claude Watermark Remover"
    assert set(operation["responses"]) == {"200", "400", "403", "413", "429", "503"}
    # Validation failures are reshaped into 400, so a documented 422 would lie.
    assert "422" not in operation["responses"]
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    # The proxy secret is injected by Rapid and must not appear in public docs.
    assert "parameters" not in operation
    for internal in ("Proxy-Secret", "stripe", "cwr_", "inspection_text"):
        assert internal.lower() not in raw.text.lower()

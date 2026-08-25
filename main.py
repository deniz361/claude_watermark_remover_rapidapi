"""FastAPI service that fronts the Claude watermark remover on RapidAPI.

Run it from the repository root:

    uvicorn rapid_api.main:app --port 8000

Rapid forwards subscriber traffic here, so this process never sees a
``cwr_`` API key and never meters anything through Stripe -- Rapid bills the
subscriber and pays out separately. The Flask endpoint at /v1/remove-watermark
keeps serving direct customers on its own key and billing.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from cleaning import clean_careful, clean_thorough
from config import Settings, get_settings
from errors import ApiError
from schemas import CleanRequest, CleanResponse, ErrorResponse, RewriteInfo
from security import RateLimiter, consumer_identity, require_proxy_secret, subscription_tier

DESCRIPTION = """
Detect and remove hidden Unicode characters from text produced by AI
assistants -- zero-width spaces, soft hyphens, word joiners, byte order marks,
stray joiners and variation selectors -- and get a full report of everything
that changed.

**careful** removes the hidden characters and leaves your wording untouched.
**thorough** also rewrites the wording to remove the recurring wording pattern,
and is available on paid plans.

Characters that belong to emoji sequences are reported but kept, so multi-code-point
emoji survive intact.
""".strip()

app = FastAPI(
    title="Claude Watermark Remover",
    version="1.0.0",
    description=DESCRIPTION,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

rate_limiter = RateLimiter()

ERROR_RESPONSES: dict[int | str, dict] = {
    400: {"model": ErrorResponse, "description": "The request body was not usable."},
    403: {"model": ErrorResponse, "description": "Not forwarded by RapidAPI, or the plan does not include this mode."},
    413: {"model": ErrorResponse, "description": "The text exceeds the size limit for the mode."},
    429: {"model": ErrorResponse, "description": "Too many requests. Honour the Retry-After header."},
    503: {"model": ErrorResponse, "description": "The service is not configured to serve this request."},
}


def custom_openapi() -> dict:
    """Publish the contract this service actually honours.

    FastAPI documents a 422 for every endpoint that validates a body, but the
    handler below turns those into a 400 in this API's error shape. Leaving the
    422 in would tell subscribers to handle a status they will never receive.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation.get("responses", {}).pop("422", None)
    schemas = schema.get("components", {}).get("schemas", {})
    for unused in ("HTTPValidationError", "ValidationError"):
        schemas.pop(unused, None)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.exception_handler(ApiError)
async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code, content=error.payload, headers=error.headers
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    """Render FastAPI's validation failures in this API's error shape."""
    first = (error.errors() or [{}])[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = first.get("msg", "The request body was not usable.")
    return JSONResponse(
        status_code=400,
        content={
            "code": "invalid_request",
            "error": f"{location}: {message}" if location else message,
        },
    )


def authorize(
    request: Request, settings: Settings = Depends(get_settings)
) -> str:
    """Verify the request came from Rapid, then throttle it per subscriber."""
    require_proxy_secret(request, settings)
    identity = consumer_identity(request)
    retry_after = rate_limiter.retry_after(
        identity, settings.rate_limit, settings.rate_window_seconds
    )
    if retry_after:
        raise ApiError(
            429,
            "rate_limit_reached",
            "Too many requests. Please retry shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    return identity


@app.get("/health", tags=["Service"], summary="Liveness and configuration check")
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Report whether the service can serve traffic. Not part of the listing."""
    return {
        "status": "ok",
        "proxy_secret_configured": settings.proxy_secret_configured,
        "thorough_available": settings.thorough_configured,
    }


@app.post(
    "/v1/remove-watermark",
    response_model=CleanResponse,
    response_model_exclude_none=True,
    responses=ERROR_RESPONSES,
    tags=["Cleaning"],
    summary="Remove hidden characters from text",
)
def remove_watermark(
    payload: CleanRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    _identity: str = Depends(authorize),
) -> CleanResponse:
    text = payload.text
    if not text.strip():
        raise ApiError(400, "text_required", "Send a non-empty text field.")
    if len(text) > settings.max_characters:
        raise ApiError(
            413,
            "text_too_large",
            f"Text must be at most {settings.max_characters:,} characters.",
        )

    if payload.mode == "careful":
        outcome = clean_careful(text)
    else:
        if not settings.thorough_configured:
            raise ApiError(
                503,
                "thorough_unavailable",
                "Thorough mode is not available on this deployment.",
            )
        if not settings.tier_may_use_thorough(subscription_tier(request)):
            raise ApiError(
                403,
                "thorough_requires_paid_plan",
                "Thorough mode requires a paid plan. Use mode=careful, or upgrade.",
            )
        if len(text) > settings.thorough_max_characters:
            raise ApiError(
                413,
                "text_too_large_for_thorough",
                (
                    "Thorough mode accepts at most "
                    f"{settings.thorough_max_characters:,} characters. "
                    "Split the text, or use mode=careful."
                ),
            )
        outcome = clean_thorough(text, settings)

    result = outcome.result
    return CleanResponse(
        text=result["text"],
        mode=payload.mode,
        input_characters=result["input_characters"],
        output_characters=result["output_characters"],
        removed_characters=result["removed_characters"],
        normalized=result["normalized"],
        findings=result["findings"],
        rewrite=(
            None
            if outcome.rewrite_applied is None
            else RewriteInfo(
                applied=outcome.rewrite_applied, reason=outcome.rewrite_reason
            )
        ),
    )

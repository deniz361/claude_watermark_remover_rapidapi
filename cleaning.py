"""Bridge to the cleaning implementation that already powers the website.

The Unicode pass and the wording rewrite are imported rather than reimplemented.
A second copy of this logic would eventually disagree with the site, and the
marketplace listing would then document behaviour the product no longer has.

``clean_text`` is a pure function and needs no Flask application context, so it
is safe to call from here. Importing it does pull the Flask module in, which is
the price of having exactly one implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from clean_text import rewrite_text_with_openai, clean_text
from config import Settings

REWRITE_UNAVAILABLE = (
    "The wording rewrite was unavailable, so only hidden Unicode was removed. "
    "The wording was not changed."
)


@dataclass(frozen=True)
class CleanOutcome:
    result: dict
    rewrite_applied: bool | None
    rewrite_reason: str | None


def clean_careful(text: str) -> CleanOutcome:
    return CleanOutcome(clean_text(text, mode="careful"), None, None)


def clean_thorough(text: str, settings: Settings) -> CleanOutcome:
    """Rewrite the wording, then run the same Unicode pass over the result.

    Mirrors the Flask behaviour: a failed rewrite degrades to the Unicode-only
    clean of the original text rather than failing the request, because a
    caller would rather have partial work than a 502.
    """
    try:
        rewritten = rewrite_text_with_openai(
            text,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout=settings.openai_timeout_seconds,
            max_output_tokens=settings.openai_max_output_tokens,
        )
        result = clean_text(rewritten, mode="thorough")
        if not result["text"].strip():
            raise ValueError("The rewritten text was empty after cleaning.")
    except Exception:
        return CleanOutcome(
            clean_text(text, mode="thorough"), False, REWRITE_UNAVAILABLE
        )
    return CleanOutcome(result, True, None)

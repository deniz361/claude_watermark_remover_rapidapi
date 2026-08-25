"""Settings for the RapidAPI service, read from the environment.

The OpenAI variables are deliberately the same names the Flask app uses, so a
single ``.env`` drives both processes. Everything specific to the marketplace
listing is prefixed ``RAPIDAPI_``.

Values are loaded from a local ``.env`` file (if present), then from the
process environment. Explicit environment variables always win.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv

from clean_text import DEFAULT_REWRITE_MODEL

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Rapid sends the subscriber's tier as X-RapidAPI-Subscription. Thorough mode
# spends real money on every call, so it is withheld from the free tier by
# default; override with RAPIDAPI_THOROUGH_TIERS.
DEFAULT_THOROUGH_TIERS = "PRO,ULTRA,MEGA,CUSTOM"

# Assumed when Rapid omits the subscription header, which it does for some
# plans. BASIC is the free tier, so this fails closed.
FALLBACK_TIER = "BASIC"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def _tiers(raw: str) -> frozenset[str]:
    return frozenset(part.strip().upper() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    proxy_secret: str
    thorough_tiers: frozenset[str]
    max_characters: int
    thorough_max_characters: int
    rate_limit: int
    rate_window_seconds: int
    openai_api_key: str
    openai_model: str
    openai_timeout_seconds: float
    openai_max_output_tokens: int

    @property
    def proxy_secret_configured(self) -> bool:
        return bool(self.proxy_secret)

    @property
    def thorough_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    def tier_may_use_thorough(self, tier: str | None) -> bool:
        if not self.thorough_tiers:
            return True
        return (tier or FALLBACK_TIER).strip().upper() in self.thorough_tiers


def build_settings() -> Settings:
    return Settings(
        proxy_secret=(os.environ.get("RAPIDAPI_PROXY_SECRET") or "").strip(),
        thorough_tiers=_tiers(
            os.environ.get("RAPIDAPI_THOROUGH_TIERS") or DEFAULT_THOROUGH_TIERS
        ),
        max_characters=_int_env("RAPIDAPI_MAX_CHARACTERS", 200_000),
        thorough_max_characters=_int_env("OPENAI_REWRITE_MAX_CHARACTERS", 20_000),
        rate_limit=_int_env("RAPIDAPI_RATE_LIMIT", 60),
        rate_window_seconds=_int_env("RAPIDAPI_RATE_WINDOW_SECONDS", 60),
        openai_api_key=(os.environ.get("OPENAI_API_KEY") or "").strip(),
        openai_model=(
            os.environ.get("OPENAI_REWRITE_MODEL") or DEFAULT_REWRITE_MODEL
        ).strip(),
        openai_timeout_seconds=_float_env("OPENAI_REWRITE_TIMEOUT_SECONDS", 25.0),
        openai_max_output_tokens=_int_env("OPENAI_REWRITE_MAX_OUTPUT_TOKENS", 12_000),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()

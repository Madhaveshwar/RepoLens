"""
Multi-provider LLM client abstraction layer.

This module resolves which LLM provider a user has selected (Groq, OpenAI,
Anthropic, Gemini, or OpenRouter) and returns a unified client interface that
the scanning pipeline can call without knowing which provider is active.

All clients expose the same method:
    client.chat.completions.create(messages=..., model=..., temperature=..., max_tokens=...)

Supported providers
-------------------
groq         – Groq API (default; fastest free tier)
openai       – OpenAI API (GPT-4o, GPT-4-turbo, etc.)
anthropic    – Anthropic Claude (via openai-compatible wrapper)
gemini       – Google Gemini (via openai-compatible wrapper)
openrouter   – OpenRouter.ai (gateway to 100+ models)
"""

from __future__ import annotations

import os
from typing import Any

from app.utils.logger import get_logger

logger = get_logger("llm_client")

# ── Default model names per provider ─────────────────────────────────────────
# NOTE (2026): Groq moved `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`
# to Enterprise-only plans. The current free/developer-tier production models
# are the GPT-OSS family. Defaults below reflect what is actually callable
# with a standard Groq API key today.

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "groq":       "openai/gpt-oss-120b",
    "openai":     "gpt-4o-mini",
    "anthropic":  "claude-3-haiku-20240307",
    "gemini":     "gemini-1.5-flash",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}

# Models exposed in the Settings page per provider (ordered by preference).
PROVIDER_MODELS: dict[str, list[str]] = {
    "groq": [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ],
    "openai": [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
    ],
    "anthropic": [
        "claude-3-haiku-20240307",
        "claude-3-5-haiku-20241022",
        "claude-sonnet-4-20250514",
    ],
    "gemini": [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash",
    ],
    "openrouter": [
        "meta-llama/llama-3.3-70b-instruct:free",
        "openai/gpt-oss-20b:free",
        "deepseek/deepseek-chat-v3-0324:free",
    ],
}

# Fallback chain per provider. If the primary/default model is rejected
# (404 model-not-found, decommissioned, no access...), the request is retried
# with the next model in this list until one succeeds.
PROVIDER_FALLBACK_MODELS: dict[str, list[str]] = {
    "groq": [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
    ],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "anthropic": ["claude-3-haiku-20240307"],
    "gemini": ["gemini-1.5-flash", "gemini-2.0-flash"],
    "openrouter": [
        "meta-llama/llama-3.3-70b-instruct:free",
        "openai/gpt-oss-20b:free",
    ],
}

# Legacy Groq fallback used across older service modules. Kept as an alias so
# existing imports keep working, but now points to a valid free-tier model.
GROQ_FALLBACK_MODEL = "openai/gpt-oss-120b"


def build_llm_client(
    provider: str,
    api_key: str,
) -> Any:
    """
    Build and return an OpenAI-compatible chat completion client.

    Parameters
    ----------
    provider : str
        One of: groq, openai, anthropic, gemini, openrouter
    api_key : str
        The decrypted API key for the chosen provider.

    Returns
    -------
    An OpenAI SDK client instance (or compatible wrapper).

    Raises
    ------
    ValueError
        If the provider is unsupported or the API key is empty.
    ImportError
        If the required package for the provider is not installed.
    """
    if not api_key:
        raise ValueError(f"API key is missing for provider '{provider}'.")

    provider = (provider or "groq").lower().strip()
    logger.info(f"Building LLM client for provider: {provider}")

    if provider == "groq":
        return _build_groq(api_key)
    elif provider == "openai":
        return _build_openai(api_key)
    elif provider in ("anthropic", "claude"):
        return _build_anthropic(api_key)
    elif provider == "gemini":
        return _build_gemini(api_key)
    elif provider == "openrouter":
        return _build_openrouter(api_key)
    else:
        logger.warning(f"Unknown LLM provider '{provider}'. Falling back to Groq.")
        return _build_groq(api_key)


def get_model_name(provider: str, user_model: str | None) -> str:
    """
    Return the model name to use for the given provider.
    Uses the user's saved model preference if set, otherwise the provider default.
    """
    provider = (provider or "groq").lower().strip()
    if user_model and user_model.strip():
        return user_model.strip()
    return PROVIDER_DEFAULT_MODELS.get(provider, PROVIDER_DEFAULT_MODELS["groq"])


def get_provider_models(provider: str) -> list[str]:
    """Return the selectable model list for a provider (for the Settings UI)."""
    provider = (provider or "groq").lower().strip()
    return PROVIDER_MODELS.get(provider, PROVIDER_MODELS["groq"])


def is_model_not_found_error(exc: Exception) -> bool:
    """Detect 'model does not exist / no access / decommissioned' API errors (404/403 class)."""
    msg = str(exc).lower()
    signals = [
        "does not exist",
        "not found",
        "no longer supported",
        "decommissioned",
        "deprecated",
        "do not have access",
        "does not have access",
        "not have permission",
        "unavailable",
    ]
    has_model_signal = "model" in msg or "model_name" in msg
    status_signal = "404" in msg or "model_not_found" in msg
    return (has_model_signal and any(s in msg for s in signals)) or (status_signal and has_model_signal)


def is_auth_error(exc: Exception) -> bool:
    """Detect invalid/expired API key errors (401/403 class)."""
    msg = str(exc).lower()
    return (
        "401" in msg
        or "403" in msg
        or "invalid_api_key" in msg
        or "invalid api key" in msg
        or "unauthorized" in msg
        or "authentication" in msg
        or "api key" in msg and "expired" in msg
    )


def is_rate_limit_error(exc: Exception) -> bool:
    """Detect 429 / quota / rate-limit errors."""
    msg = str(exc).lower()
    return (
        "429" in msg
        or "rate_limit" in msg
        or "rate limit" in msg
        or "quota" in msg
        or "limit exceeded" in msg
        or "too many requests" in msg
    )


def friendly_llm_error(provider: str, exc: Exception) -> str:
    """
    Convert a raw provider exception into a short, user-facing message.
    The guidance always points at the Settings page.
    """
    provider = (provider or "groq").lower().strip()
    if is_auth_error(exc):
        return (
            f"The {provider.capitalize()} API key is missing, invalid, or expired. "
            "Please update your API key in Settings."
        )
    if is_rate_limit_error(exc):
        return (
            f"The {provider.capitalize()} API rate limit was exceeded. "
            "Please wait a moment and try again."
        )
    if is_model_not_found_error(exc):
        return (
            f"The selected {provider.capitalize()} model is not available on your account. "
            "Please choose a different model in Settings."
        )
    return (
        "LLM provider is not configured correctly. "
        "Please update your API key and model in Settings."
    )


def create_chat_completion(
    client: Any,
    provider: str,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> Any:
    """
    Provider-aware chat completion with automatic model fallback.

    Tries the requested model first; on a model-not-found/decommission error
    it retries through PROVIDER_FALLBACK_MODELS until one succeeds. Other
    error classes (auth, rate limit, network) are re-raised unchanged so the
    caller can present a friendly message via friendly_llm_error().
    """
    provider = (provider or "groq").lower().strip()
    requested_model = model or PROVIDER_DEFAULT_MODELS.get(provider, PROVIDER_DEFAULT_MODELS["groq"])

    fallbacks = [m for m in PROVIDER_FALLBACK_MODELS.get(provider, [requested_model]) if m != requested_model]
    candidates = [requested_model] + fallbacks

    last_exc: Exception | None = None
    for candidate in candidates:
        try:
            return client.chat.completions.create(
                messages=messages,
                model=candidate,
                temperature=temperature,
                **({"max_tokens": max_tokens} if max_tokens else {}),
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - normalised below
            last_exc = exc
            if is_model_not_found_error(exc) and candidate != candidates[-1]:
                logger.warning(
                    f"Model '{candidate}' unavailable for provider '{provider}' "
                    f"({exc}). Retrying with fallback model..."
                )
                continue
            raise

    # Should not be reached, but be defensive.
    raise last_exc if last_exc else RuntimeError("LLM chat completion failed for an unknown reason.")


# ── Private builder functions ─────────────────────────────────────────────────

def _build_groq(api_key: str) -> Any:
    """Groq SDK – returns a native Groq client (OpenAI-compatible interface)."""
    from groq import Groq  # type: ignore
    return Groq(api_key=api_key)


def _build_openai(api_key: str) -> Any:
    """OpenAI SDK – returns an OpenAI client."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ImportError(
            "The 'openai' package is required for the OpenAI provider. "
            "Install it with: pip install openai"
        ) from e
    return OpenAI(api_key=api_key)


def _build_anthropic(api_key: str) -> Any:
    """
    Anthropic – uses the openai-compatible Messages endpoint via base_url override.
    This lets us call client.chat.completions.create() identically to other providers.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ImportError(
            "The 'openai' package is required as the Anthropic adapter. "
            "Install it with: pip install openai"
        ) from e
    return OpenAI(
        api_key=api_key,
        base_url="https://api.anthropic.com/v1/",
        default_headers={
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
        },
    )


def _build_gemini(api_key: str) -> Any:
    """
    Google Gemini – uses the OpenAI-compatible Gemini endpoint.
    Requires the 'openai' package.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ImportError(
            "The 'openai' package is required as the Gemini adapter. "
            "Install it with: pip install openai"
        ) from e
    return OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


def _build_openrouter(api_key: str) -> Any:
    """
    OpenRouter – gateway to 100+ models via OpenAI-compatible API.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise ImportError(
            "The 'openai' package is required for the OpenRouter adapter. "
            "Install it with: pip install openai"
        ) from e
    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://github.com/RepoLens-AI",
            "X-Title": "RepoLens AI",
        },
    )


# ── Backwards-compatibility shim ─────────────────────────────────────────────
# The existing pipeline imports `build_groq_client` from reviewer.py.
# Keep that working while encouraging migration to build_llm_client.

def build_groq_client(api_key: str) -> Any:
    """Backwards-compatible shim – builds a Groq client directly."""
    return _build_groq(api_key)

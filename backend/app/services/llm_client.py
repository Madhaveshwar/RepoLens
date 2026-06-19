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

from backend.app.utils.logger import get_logger

logger = get_logger("llm_client")

# ── Default model names per provider ─────────────────────────────────────────

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "groq":       "llama-3.3-70b-versatile",
    "openai":     "gpt-4o-mini",
    "anthropic":  "claude-3-haiku-20240307",
    "gemini":     "gemini-1.5-flash",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}

# ── Fallback Groq model when the primary quota is exhausted ──────────────────
GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"


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
            "HTTP-Referer": "https://github.com/AI-Code-Reviewer",
            "X-Title": "AI Code Reviewer",
        },
    )


# ── Backwards-compatibility shim ─────────────────────────────────────────────
# The existing pipeline imports `build_groq_client` from reviewer.py.
# Keep that working while encouraging migration to build_llm_client.

def build_groq_client(api_key: str) -> Any:
    """Backwards-compatible shim – builds a Groq client directly."""
    return _build_groq(api_key)

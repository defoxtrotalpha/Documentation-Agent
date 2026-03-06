from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)

# ── Concurrency control ──────────────────────────────────────────────
_MAX_CONCURRENT = int(os.getenv("DOC_LLM_CONCURRENCY", "5"))
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init so the semaphore is created within the running event loop."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        LOGGER.info("[llm] Semaphore initialised (max_concurrent=%d)", _MAX_CONCURRENT)
    return _semaphore


# ── Config ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    foundry_project_endpoint: Optional[str] = None
    foundry_model_deployment: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: Optional[str] = None
    azure_openai_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None


_config_loaded: bool = False
_config_value: LLMConfig | None = None


def load_llm_config(env_path: Path | None = None) -> LLMConfig | None:
    """Load LLM configuration from environment variables. Cached after first call."""
    global _config_loaded, _config_value
    if _config_loaded:
        return _config_value

    LOGGER.info("[llm] Loading LLM configuration (env_path=%s)", env_path)
    if env_path and env_path.exists():
        load_dotenv(env_path)
    elif env_path:
        LOGGER.warning("[llm] env_path does not exist: %s", env_path)

    provider = _normalize_provider((os.getenv("DOC_LLM_PROVIDER") or "").strip().lower())
    if not provider:
        if os.getenv("FOUNDRY_PROJECT_ENDPOINT") and os.getenv(
            "FOUNDRY_MODEL_DEPLOYMENT"
        ):
            provider = "foundry"
        elif os.getenv("AZURE_OPENAI_URL"):
            provider = "azure-openai"
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"
        elif os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("GEMINI_API_KEY"):
            provider = "gemini"
        else:
            LOGGER.warning("[llm] No LLM provider configured — generation disabled")
            _config_loaded = True
            _config_value = None
            return None

    LOGGER.info("[llm] Detected provider: %s", provider)
    config: LLMConfig | None = None

    if provider == "foundry":
        config = _load_foundry_config()
    elif provider == "azure-openai":
        config = _load_azure_openai_config()
    elif provider == "openai":
        config = _load_openai_config()
    elif provider == "anthropic":
        config = _load_anthropic_config()
    elif provider == "gemini":
        config = _load_gemini_config()
    else:
        LOGGER.warning("[llm] Unknown provider %r", provider)

    _config_loaded = True
    _config_value = config
    return config


def _load_foundry_config() -> LLMConfig | None:
    ep = (os.getenv("FOUNDRY_PROJECT_ENDPOINT") or "").strip()
    dep = (os.getenv("FOUNDRY_MODEL_DEPLOYMENT") or "").strip()
    if not ep or not dep:
        LOGGER.warning("[llm] Foundry config incomplete")
        return None
    LOGGER.info("[llm] Foundry OK — endpoint=%s  deployment=%s", ep, dep)
    return LLMConfig(
        provider="foundry",
        foundry_project_endpoint=ep,
        foundry_model_deployment=dep,
    )


def _normalize_provider(provider: str) -> str:
    alias_map = {
        "azure": "azure-openai",
        "azure-openai": "azure-openai",
        "foundry": "foundry",
        "openai": "openai",
        "chatgpt": "openai",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "gemini": "gemini",
        "google": "gemini",
    }
    return alias_map.get(provider, provider)


def _load_azure_openai_config() -> LLMConfig | None:
    endpoint = (os.getenv("AZURE_OPENAI_URL") or "").strip()
    api_key = (os.getenv("AZURE_OPENAI_KEY") or "").strip()
    api_version = (os.getenv("AZURE_GPT_API") or "").strip() or "2024-12-01-preview"
    model = (os.getenv("AZURE_OPENAI_MODEL") or os.getenv("DOC_LLM_MODEL") or "gpt-4.1").strip()
    if not endpoint or not api_key:
        LOGGER.warning("[llm] Azure OpenAI config incomplete")
        return None
    LOGGER.info("[llm] Azure OpenAI OK — endpoint=%s  model=%s", endpoint, model)
    return LLMConfig(
        provider="azure-openai",
        azure_openai_endpoint=endpoint,
        azure_openai_api_key=api_key or None,
        azure_openai_api_version=api_version,
        azure_openai_model=model,
    )


def _load_openai_config() -> LLMConfig | None:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    model = (os.getenv("OPENAI_MODEL") or os.getenv("DOC_LLM_MODEL") or "gpt-4.1").strip()
    if not api_key:
        LOGGER.warning("[llm] OpenAI config incomplete")
        return None
    LOGGER.info("[llm] OpenAI OK — model=%s", model)
    return LLMConfig(
        provider="openai",
        openai_api_key=api_key,
        openai_model=model,
    )


def _load_anthropic_config() -> LLMConfig | None:
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    model = (
        os.getenv("ANTHROPIC_MODEL")
        or os.getenv("DOC_LLM_MODEL")
        or "claude-3-7-sonnet-latest"
    ).strip()
    if not api_key:
        LOGGER.warning("[llm] Anthropic config incomplete")
        return None
    LOGGER.info("[llm] Anthropic OK — model=%s", model)
    return LLMConfig(
        provider="anthropic",
        anthropic_api_key=api_key,
        anthropic_model=model,
    )


def _load_gemini_config() -> LLMConfig | None:
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    model = (os.getenv("GEMINI_MODEL") or os.getenv("DOC_LLM_MODEL") or "gemini-2.0-flash").strip()
    if not api_key:
        LOGGER.warning("[llm] Gemini config incomplete")
        return None
    LOGGER.info("[llm] Gemini OK — model=%s", model)
    return LLMConfig(
        provider="gemini",
        gemini_api_key=api_key,
        gemini_model=model,
    )


def is_llm_configured(env_path: Path | None = None) -> bool:
    return load_llm_config(env_path) is not None


# ── Generation (async-first) ─────────────────────────────────────────


async def generate_markdown(
    prompt: str, label: str = "", env_path: Path | None = None
) -> str | None:
    """
    Generate markdown via LLM.  Concurrency-limited by a shared semaphore.
    *label* appears in log lines for traceability (e.g. "endpoint:orders").
    """
    config = load_llm_config(env_path)
    if not config:
        LOGGER.warning(
            "[llm] Skipping generation — no config%s",
            f"  ({label})" if label else "",
        )
        return None

    tag = f"  [{label}]" if label else ""
    sem = _get_semaphore()
    async with sem:
        LOGGER.info(
            "[llm] >> Sending request%s  (provider=%s, prompt=%d chars)",
            tag,
            config.provider,
            len(prompt),
        )
        try:
            result = await _dispatch(prompt, config)
            LOGGER.info(
                "[llm] << Received response%s  (%d chars)",
                tag,
                len(result) if result else 0,
            )
            return result
        except Exception as exc:
            LOGGER.error(
                "[llm] !! Generation failed%s: %s", tag, exc, exc_info=True
            )
            return None


def generate_markdown_sync(prompt: str, env_path: Path | None = None) -> str | None:
    """Synchronous convenience wrapper (do NOT call from inside an event loop)."""
    try:
        return asyncio.run(generate_markdown(prompt, env_path=env_path))
    except RuntimeError:
        LOGGER.warning("[llm] Cannot run sync wrapper inside an existing event loop")
        return None


# ── Provider dispatchers ──────────────────────────────────────────────


async def _dispatch(prompt: str, config: LLMConfig) -> str | None:
    if config.provider == "foundry":
        return await _run_foundry(prompt, config)
    if config.provider == "azure-openai":
        return await _run_azure_openai(prompt, config)
    if config.provider == "openai":
        return await _run_openai(prompt, config)
    if config.provider == "anthropic":
        return await _run_anthropic(prompt, config)
    if config.provider == "gemini":
        return await _run_gemini(prompt, config)
    LOGGER.warning("[llm] No handler for provider %r", config.provider)
    return None


async def _run_foundry(prompt: str, config: LLMConfig) -> str | None:
    from agent_framework.azure import AzureAIClient
    from azure.identity.aio import DefaultAzureCredential

    async with (
        DefaultAzureCredential() as credential,
        AzureAIClient(
            project_endpoint=config.foundry_project_endpoint,
            model_deployment_name=config.foundry_model_deployment,
            credential=credential,
        ).create_agent(
            name="documentation-agent",
            instructions="You write clear technical documentation in markdown.",
        ) as agent,
    ):
        result = await agent.run(prompt)
        return result.text.strip() if result and result.text else None


async def _run_azure_openai(prompt: str, config: LLMConfig) -> str | None:
    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(
        api_key=config.azure_openai_api_key,
        api_version=config.azure_openai_api_version or "2024-12-01-preview",
        azure_endpoint=config.azure_openai_endpoint,
        max_retries=3,
    )
    response = await client.chat.completions.create(
        model=config.azure_openai_model or "gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    content = response.choices[0].message.content if response.choices else None
    return content.strip() if content else None


async def _run_openai(prompt: str, config: LLMConfig) -> str | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=config.openai_api_key,
        max_retries=3,
    )
    response = await client.chat.completions.create(
        model=config.openai_model or "gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    content = response.choices[0].message.content if response.choices else None
    return content.strip() if content else None


async def _run_anthropic(prompt: str, config: LLMConfig) -> str | None:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=config.anthropic_api_key)
    response = await client.messages.create(
        model=config.anthropic_model or "claude-3-7-sonnet-latest",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        text = getattr(block, "text", None)
        if text:
            return text.strip()
    return None


async def _run_gemini(prompt: str, config: LLMConfig) -> str | None:
    from google import genai

    client = genai.Client(api_key=config.gemini_api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=config.gemini_model or "gemini-2.0-flash",
        contents=prompt,
    )
    text = getattr(response, "text", None)
    return text.strip() if text else None

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    foundry_project_endpoint: Optional[str] = None
    foundry_model_deployment: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_deployment: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: Optional[str] = None
    azure_openai_model: Optional[str] = None


def load_llm_config(env_path: Path | None = None) -> LLMConfig | None:
    LOGGER.info("[llm_client] Loading LLM config (env_path=%s)", env_path)
    if env_path and env_path.exists():
        LOGGER.info("[llm_client] Loading .env from: %s", env_path)
        load_dotenv(env_path)
    elif env_path:
        LOGGER.warning("[llm_client] Provided env_path does not exist: %s", env_path)

    provider = (os.getenv("DOC_LLM_PROVIDER") or "").strip().lower()
    LOGGER.info("[llm_client] DOC_LLM_PROVIDER=%r", provider or "(not set)")
    if not provider:
        if os.getenv("FOUNDRY_PROJECT_ENDPOINT") and os.getenv("FOUNDRY_MODEL_DEPLOYMENT"):
            provider = "foundry"
            LOGGER.info("[llm_client] Auto-detected provider: foundry")
        elif os.getenv("AZURE_OPENAI_URL"):
            provider = "azure-openai"
            LOGGER.info("[llm_client] Auto-detected provider: azure-openai")
        else:
            LOGGER.warning("[llm_client] No LLM provider configured — returning None")
            return None

    if provider == "foundry":
        project_endpoint = (os.getenv("FOUNDRY_PROJECT_ENDPOINT") or "").strip()
        deployment = (os.getenv("FOUNDRY_MODEL_DEPLOYMENT") or "").strip()
        LOGGER.info("[llm_client] Foundry — endpoint=%s, deployment=%s", project_endpoint or "(empty)", deployment or "(empty)")
        if not project_endpoint or not deployment:
            LOGGER.warning("[llm_client] Foundry config incomplete — returning None")
            return None
        LOGGER.info("[llm_client] Foundry config loaded successfully")
        return LLMConfig(
            provider=provider,
            foundry_project_endpoint=project_endpoint,
            foundry_model_deployment=deployment,
        )

    if provider == "azure-openai":
        endpoint = (
            os.getenv("AZURE_OPENAI_URL")
            or ""
        ).strip()
        api_key = (
            os.getenv("AZURE_OPENAI_KEY")
            or ""
        ).strip()
        api_version = (os.getenv("AZURE_GPT_API") or "").strip() or "2024-12-01-preview"
        model = (
            os.getenv("DOC_LLM_MODEL")
            or "gpt-4.1"
        ).strip()
        LOGGER.info(
            "[llm_client] Azure OpenAI — endpoint=%s, key=%s, api_version=%s, model=%s",
            endpoint or "(empty)",
            f"...{api_key[-8:]}" if api_key else "(empty)",
            api_version,
            model,
        )
        if not endpoint or not api_key:
            LOGGER.warning("[llm_client] Azure OpenAI config incomplete (endpoint or key missing) — returning None")
            return None
        LOGGER.info("[llm_client] Azure OpenAI config loaded successfully")
        return LLMConfig(
            provider=provider,
            azure_openai_endpoint=endpoint,
            azure_openai_api_key=api_key or None,
            azure_openai_api_version=api_version,
            azure_openai_model=model,
        )

    LOGGER.warning("[llm_client] Unknown provider %r — returning None", provider)
    return None


def is_llm_configured(env_path: Path | None = None) -> bool:
    return load_llm_config(env_path) is not None


def generate_markdown_sync(prompt: str, env_path: Path | None = None) -> str | None:
    LOGGER.info("[llm_client] generate_markdown_sync called (prompt length=%d, env_path=%s)", len(prompt), env_path)
    config = load_llm_config(env_path)
    if not config:
        LOGGER.warning("[llm_client] No LLM config available — skipping generation")
        return None

    try:
        LOGGER.info("[llm_client] Starting async LLM call via provider=%s", config.provider)
        result = asyncio.run(_generate_markdown(prompt, config))
        LOGGER.info("[llm_client] LLM call completed — result length=%d", len(result) if result else 0)
        return result
    except RuntimeError as exc:
        LOGGER.warning("[llm_client] Unable to run LLM call: %s", exc)
        return None


async def _generate_markdown(prompt: str, config: LLMConfig) -> str | None:
    LOGGER.debug("[llm_client] _generate_markdown dispatching to provider=%s", config.provider)
    if config.provider == "foundry":
        return await _run_foundry(prompt, config)
    if config.provider == "azure-openai":
        return await _run_azure_openai(prompt, config)
    LOGGER.warning("[llm_client] No handler for provider=%s", config.provider)
    return None


async def _run_foundry(prompt: str, config: LLMConfig) -> str | None:
    LOGGER.info("[llm_client] Running Foundry call — endpoint=%s, deployment=%s", config.foundry_project_endpoint, config.foundry_model_deployment)
    from agent_framework.azure import AzureAIClient
    from azure.identity.aio import DefaultAzureCredential

    try:
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
            LOGGER.info("[llm_client] Foundry agent created, sending prompt...")
            result = await agent.run(prompt)
            output = result.text.strip() if result and result.text else None
            LOGGER.info("[llm_client] Foundry response received — length=%d", len(output) if output else 0)
            return output
    except Exception as exc:
        LOGGER.error("[llm_client] Foundry call failed: %s", exc, exc_info=True)
        raise


async def _run_azure_openai(prompt: str, config: LLMConfig) -> str | None:
    from openai import AsyncAzureOpenAI

    LOGGER.info(
        "[llm_client] Azure OpenAI call — endpoint=%s, model=%s, api_version=%s, key=...%s",
        config.azure_openai_endpoint,
        config.azure_openai_model,
        config.azure_openai_api_version,
        config.azure_openai_api_key[-8:] if config.azure_openai_api_key else "(none)",
    )
    client = AsyncAzureOpenAI(
        api_key=config.azure_openai_api_key,
        api_version=config.azure_openai_api_version or "2024-12-01-preview",
        azure_endpoint=config.azure_openai_endpoint,
        max_retries=3,
    )
    try:
        LOGGER.info("[llm_client] Sending chat completion request (prompt length=%d)...", len(prompt))
        response = await client.chat.completions.create(
            model=config.azure_openai_model or "gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        content = response.choices[0].message.content if response.choices else None
        LOGGER.info(
            "[llm_client] Azure OpenAI response — choices=%d, content_length=%d, model=%s",
            len(response.choices) if response.choices else 0,
            len(content) if content else 0,
            response.model if response else "(none)",
        )
        return content.strip() if content else None
    except Exception as exc:
        LOGGER.error("[llm_client] Azure OpenAI call failed: %s", exc, exc_info=True)
        raise

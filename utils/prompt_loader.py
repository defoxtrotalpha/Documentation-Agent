from __future__ import annotations

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def load_prompt(name: str) -> str:
    prompts_dir = Path(__file__).resolve().parents[1] / "prompts"
    prompt_path = prompts_dir / f"{name}.txt"
    LOGGER.info("[prompt_loader] Loading prompt '%s' from %s", name, prompt_path)
    if not prompt_path.exists():
        LOGGER.error("[prompt_loader] Prompt file not found: %s", prompt_path)
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    content = prompt_path.read_text(encoding="utf-8")
    LOGGER.debug("[prompt_loader] Prompt '%s' loaded (%d chars)", name, len(content))
    return content


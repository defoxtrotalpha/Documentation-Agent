from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .utils import (
    ROOT_DOC_FILENAME,
    DocRenderResult,
    build_metadata,
    compute_sources_hash,
    generate_markdown_sync,
    load_prompt,
    render_backend_endpoint_document,
    render_backend_root_document,
    render_directory_tree,
    save_metadata,
    should_regenerate,
    write_if_changed,
)

LOGGER = logging.getLogger(__name__)
AGENT_VERSION = "0.1"


def generate_backend_docs(repo_root: Path, changed_files: Iterable[Path] | None = None) -> None:
    LOGGER.info("[backend_agent] Starting backend documentation generation (repo_root=%s)", repo_root)
    repo_root = repo_root.resolve()
    _ensure_root_document(repo_root)

    endpoints = _collect_endpoints(repo_root, changed_files)
    LOGGER.info("[backend_agent] Found %d endpoint(s) to document", len(endpoints))
    for i, endpoint_path in enumerate(endpoints, 1):
        LOGGER.info("[backend_agent] Processing endpoint %d/%d: %s", i, len(endpoints), endpoint_path.name)
        _ensure_endpoint_document(endpoint_path)
    LOGGER.info("[backend_agent] Backend documentation generation complete")


def _ensure_root_document(repo_root: Path) -> None:
    LOGGER.info("[backend_agent] Generating root document...")
    content = _render_root_with_llm(repo_root)
    if content:
        LOGGER.info("[backend_agent] Root document rendered via LLM (length=%d)", len(content))
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info("[backend_agent] LLM unavailable — using scaffold template for root document")
        result = render_backend_root_document(repo_root)
    backend_root = _resolve_backend_root(repo_root)
    doc_path = (backend_root / ROOT_DOC_FILENAME).resolve()
    LOGGER.info("[backend_agent] Writing root document to %s", doc_path)
    _write_with_metadata(
        doc_path,
        result,
        sources=[backend_root],
        doc_type="backend-root",
    )


def _collect_endpoints(
    repo_root: Path,
    changed_files: Iterable[Path] | None,
) -> list[Path]:
    backend_root = _resolve_backend_root(repo_root)
    endpoints_root = (backend_root / "api" / "v1" / "endpoints").resolve()
    LOGGER.info("[backend_agent] Scanning endpoints at %s", endpoints_root)
    if not endpoints_root.exists():
        LOGGER.warning("[backend_agent] Endpoints root not found: %s", endpoints_root)
        return []

    if changed_files is None:
        all_endpoints = sorted(endpoints_root.glob("*.py"))
        LOGGER.info("[backend_agent] Full scan — found %d endpoint file(s)", len(all_endpoints))
        return all_endpoints

    if not changed_files:
        LOGGER.info("[backend_agent] No changed files — skipping endpoint docs")
        return []

    if changed_files:
        candidates = [
            path
            for path in changed_files
            if path.suffix == ".py" and _is_relative_to(path, endpoints_root)
        ]
        result = sorted({p.resolve() for p in candidates})
        LOGGER.info("[backend_agent] Incremental scan — %d changed endpoint file(s)", len(result))
        return result

    return []


def _ensure_endpoint_document(endpoint_path: Path) -> None:
    LOGGER.info("[backend_agent] Generating doc for endpoint: %s", endpoint_path.stem)
    content = _render_endpoint_with_llm(endpoint_path)
    if content:
        LOGGER.info("[backend_agent] Endpoint %s rendered via LLM (length=%d)", endpoint_path.stem, len(content))
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info("[backend_agent] LLM unavailable — using scaffold template for endpoint %s", endpoint_path.stem)
        result = render_backend_endpoint_document(endpoint_path)
    doc_dir = endpoint_path.parent / endpoint_path.stem
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_path = doc_dir / ROOT_DOC_FILENAME
    LOGGER.info("[backend_agent] Writing endpoint doc to %s", doc_path)
    _write_with_metadata(
        doc_path,
        result,
        sources=[endpoint_path],
        doc_type="backend-endpoint",
    )


def _write_with_metadata(
    doc_path: Path,
    result: DocRenderResult,
    sources: Iterable[Path],
    doc_type: str,
) -> None:
    if not should_regenerate(doc_path, sources):
        LOGGER.info("[backend_agent] Skipping %s — sources unchanged", doc_path.name)
        return

    if not result.source_hash:
        result = DocRenderResult(content=result.content, source_hash=compute_sources_hash(sources))

    write_if_changed(doc_path, result.content)
    metadata = build_metadata(
        source_hash=result.source_hash,
        agent_version=AGENT_VERSION,
        doc_type=doc_type,
        sources=sources,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    save_metadata(doc_path, metadata)
    LOGGER.info("[backend_agent] Wrote %s with metadata (type=%s, hash=%s)", doc_path.name, doc_type, result.source_hash[:12])


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _render_root_with_llm(repo_root: Path) -> str | None:
    backend_root = _resolve_backend_root(repo_root)
    env_path = (backend_root / ".env").resolve()
    LOGGER.info("[backend_agent] Rendering root doc with LLM (env_path=%s)", env_path)
    prompt = load_prompt("backend_root")
    tree = render_directory_tree(
        backend_root,
        max_depth=3,
        exclude_dirs=["__pycache__", ".venv", ".git"],
    )
    filled = prompt.format(directory_tree=tree)
    LOGGER.debug("[backend_agent] Root prompt length=%d", len(filled))
    return generate_markdown_sync(filled, env_path=env_path)


def _render_endpoint_with_llm(endpoint_path: Path) -> str | None:
    env_path = _find_repo_env(endpoint_path)
    LOGGER.info("[backend_agent] Rendering endpoint %s with LLM (env_path=%s)", endpoint_path.stem, env_path)
    prompt = load_prompt("backend_endpoint")
    source = _read_text_with_limit(endpoint_path, limit=12000)
    filled = prompt.format(source_path=str(endpoint_path), source_content=source)
    LOGGER.debug("[backend_agent] Endpoint prompt length=%d", len(filled))
    return generate_markdown_sync(filled, env_path=env_path)


def _read_text_with_limit(path: Path, limit: int) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[TRUNCATED]\n"


def _resolve_backend_root(repo_root: Path) -> Path:
    repo_root = repo_root.resolve()
    backend_root = repo_root / "backend"
    if backend_root.exists():
        LOGGER.debug("[backend_agent] Backend root resolved to %s", backend_root)
        return backend_root.resolve()
    LOGGER.debug("[backend_agent] No 'backend/' dir found — using repo_root as backend root")
    return repo_root


def _find_repo_env(start_path: Path) -> Path:
    LOGGER.debug("[backend_agent] Searching for .env starting from %s", start_path)
    for parent in start_path.resolve().parents:
        candidate = parent / ".env"
        if candidate.exists():
            LOGGER.debug("[backend_agent] Found .env at %s", candidate)
            return candidate
        if (parent / "backend").exists():
            backend_env = parent / "backend" / ".env"
            if backend_env.exists():
                LOGGER.debug("[backend_agent] Found .env at %s", backend_env)
                return backend_env
    fallback = (start_path.resolve().parents[0] / ".env").resolve()
    LOGGER.warning("[backend_agent] No .env found — falling back to %s", fallback)
    return fallback

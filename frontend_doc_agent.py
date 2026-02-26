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
    render_frontend_feature_document,
    render_frontend_root_document,
    render_directory_tree,
    save_metadata,
    should_regenerate,
    write_if_changed,
)

LOGGER = logging.getLogger(__name__)
AGENT_VERSION = "0.1"


def generate_frontend_docs(repo_root: Path, changed_files: Iterable[Path] | None = None) -> None:
    LOGGER.info("[frontend_agent] Starting frontend documentation generation (repo_root=%s)", repo_root)
    repo_root = repo_root.resolve()
    _ensure_root_document(repo_root)

    features = _collect_features(repo_root, changed_files)
    LOGGER.info("[frontend_agent] Found %d feature(s) to document", len(features))
    for i, feature_dir in enumerate(features, 1):
        LOGGER.info("[frontend_agent] Processing feature %d/%d: %s", i, len(features), feature_dir.name)
        _ensure_feature_document(feature_dir)
    LOGGER.info("[frontend_agent] Frontend documentation generation complete")


def _ensure_root_document(repo_root: Path) -> None:
    LOGGER.info("[frontend_agent] Generating root document...")
    content = _render_root_with_llm(repo_root)
    if content:
        LOGGER.info("[frontend_agent] Root document rendered via LLM (length=%d)", len(content))
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info("[frontend_agent] LLM unavailable — using scaffold template for root document")
        result = render_frontend_root_document(repo_root)
    frontend_root = _resolve_frontend_root(repo_root)
    doc_path = (frontend_root / ROOT_DOC_FILENAME).resolve()
    LOGGER.info("[frontend_agent] Writing root document to %s", doc_path)
    _write_with_metadata(
        doc_path,
        result,
        sources=[frontend_root],
        doc_type="frontend-root",
    )


def _collect_features(
    repo_root: Path,
    changed_files: Iterable[Path] | None,
) -> list[Path]:
    frontend_root = _resolve_frontend_root(repo_root)
    features_root = (frontend_root / "src" / "features").resolve()
    LOGGER.info("[frontend_agent] Scanning features at %s", features_root)
    if not features_root.exists():
        LOGGER.warning("[frontend_agent] Features root not found: %s", features_root)
        return []

    if changed_files is None:
        all_features = sorted([p for p in features_root.iterdir() if p.is_dir()])
        LOGGER.info("[frontend_agent] Full scan — found %d feature dir(s)", len(all_features))
        return all_features

    if not changed_files:
        LOGGER.info("[frontend_agent] No changed files — skipping feature docs")
        return []

    if changed_files:
        feature_dirs: set[Path] = set()
        for path in changed_files:
            if not _is_relative_to(path, features_root):
                continue
            try:
                relative = path.resolve().relative_to(features_root)
            except ValueError:
                continue
            if not relative.parts:
                continue
            feature_dirs.add(features_root / relative.parts[0])
        result = sorted({p.resolve() for p in feature_dirs if p.exists()})
        LOGGER.info("[frontend_agent] Incremental scan — %d changed feature dir(s)", len(result))
        return result

    return []


def _ensure_feature_document(feature_dir: Path) -> None:
    LOGGER.info("[frontend_agent] Generating doc for feature: %s", feature_dir.name)
    content = _render_feature_with_llm(feature_dir)
    if content:
        LOGGER.info("[frontend_agent] Feature %s rendered via LLM (length=%d)", feature_dir.name, len(content))
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info("[frontend_agent] LLM unavailable — using scaffold template for feature %s", feature_dir.name)
        result = render_frontend_feature_document(feature_dir)
    doc_path = feature_dir / ROOT_DOC_FILENAME
    LOGGER.info("[frontend_agent] Writing feature doc to %s", doc_path)
    _write_with_metadata(
        doc_path,
        result,
        sources=[feature_dir],
        doc_type="frontend-feature",
    )


def _write_with_metadata(
    doc_path: Path,
    result: DocRenderResult,
    sources: Iterable[Path],
    doc_type: str,
) -> None:
    if not should_regenerate(doc_path, sources):
        LOGGER.info("[frontend_agent] Skipping %s — sources unchanged", doc_path.name)
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
    LOGGER.info("[frontend_agent] Wrote %s with metadata (type=%s, hash=%s)", doc_path.name, doc_type, result.source_hash[:12])


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _render_root_with_llm(repo_root: Path) -> str | None:
    env_path = _find_repo_env(repo_root)
    LOGGER.info("[frontend_agent] Rendering root doc with LLM (env_path=%s)", env_path)
    prompt = load_prompt("frontend_root")
    tree = render_directory_tree(
        _resolve_frontend_root(repo_root),
        max_depth=3,
        exclude_dirs=["node_modules", "dist", ".git"],
    )
    filled = prompt.format(directory_tree=tree)
    LOGGER.debug("[frontend_agent] Root prompt length=%d", len(filled))
    return generate_markdown_sync(filled, env_path=env_path)


def _render_feature_with_llm(feature_dir: Path) -> str | None:
    env_path = _find_repo_env(feature_dir)
    LOGGER.info("[frontend_agent] Rendering feature %s with LLM (env_path=%s)", feature_dir.name, env_path)
    prompt = load_prompt("frontend_feature")
    source = _read_feature_sources(feature_dir)
    filled = prompt.format(source_path=str(feature_dir), source_content=source)
    LOGGER.debug("[frontend_agent] Feature prompt length=%d", len(filled))
    return generate_markdown_sync(filled, env_path=env_path)


def _read_feature_sources(feature_dir: Path) -> str:
    allowed = {".js", ".jsx", ".ts", ".tsx", ".css"}
    parts: list[str] = []
    files = [
        path
        for path in sorted(feature_dir.rglob("*"), key=lambda p: str(p))
        if path.is_file() and path.suffix in allowed
    ]
    LOGGER.debug("[frontend_agent] Feature %s: %d source files found, reading up to 5", feature_dir.name, len(files))

    for path in files[:5]:
        content = path.read_text(encoding="utf-8", errors="ignore")
        if len(content) > 6000:
            content = content[:6000] + "\n\n[TRUNCATED]\n"
        parts.append(f"---\n{path}\n---\n{content}")

    if not parts:
        LOGGER.warning("[frontend_agent] No source files found for feature %s", feature_dir.name)
        return "No source files found."

    return "\n\n".join(parts)


def _resolve_frontend_root(repo_root: Path) -> Path:
    repo_root = repo_root.resolve()
    frontend_root = repo_root / "frontend"
    if frontend_root.exists():
        LOGGER.debug("[frontend_agent] Frontend root resolved to %s", frontend_root)
        return frontend_root.resolve()
    LOGGER.debug("[frontend_agent] No 'frontend/' dir found — using repo_root as frontend root")
    return repo_root


def _find_repo_env(start_path: Path) -> Path:
    LOGGER.debug("[frontend_agent] Searching for .env starting from %s", start_path)
    for parent in start_path.resolve().parents:
        candidate = parent / ".env"
        if candidate.exists():
            LOGGER.debug("[frontend_agent] Found .env at %s", candidate)
            return candidate
        if (parent / "backend").exists():
            backend_env = parent / "backend" / ".env"
            if backend_env.exists():
                LOGGER.debug("[frontend_agent] Found .env at %s", backend_env)
                return backend_env
    fallback = (start_path.resolve().parents[0] / ".env").resolve()
    LOGGER.warning("[frontend_agent] No .env found — falling back to %s", fallback)
    return fallback

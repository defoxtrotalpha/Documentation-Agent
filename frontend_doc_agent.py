from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .utils import (
    ROOT_DOC_FILENAME,
    DocRenderResult,
    build_metadata,
    compute_sources_hash,
    compute_structure_fingerprint,
    generate_markdown,
    load_prompt,
    render_frontend_feature_document,
    render_frontend_root_document,
    render_directory_tree,
    save_metadata,
    should_regenerate,
    should_regenerate_root,
    write_if_changed,
)

LOGGER = logging.getLogger(__name__)
AGENT_VERSION = "0.2"


# ── Public entry point ────────────────────────────────────────────────


async def generate_frontend_docs(
    repo_root: Path,
    changed_files: list[Path] | None = None,
) -> None:
    """
    Generate frontend documentation with true parallelism.

    - changed_files=None  →  full scan
    - changed_files=[]    →  no changes
    - changed_files=[..]  →  incremental (only affected features)
    """
    LOGGER.info("[frontend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    LOGGER.info("[frontend] Starting frontend documentation agent")
    LOGGER.info("[frontend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    t0 = time.monotonic()
    repo_root = repo_root.resolve()
    frontend_root = _resolve_frontend_root(repo_root)
    features_root = (frontend_root / "src" / "features").resolve()

    # 1. Discover ALL feature directories (needed for structure comparison)
    all_features = _list_all_features(features_root)
    LOGGER.info("[frontend] Total features on disk: %d", len(all_features))
    for feat in all_features:
        LOGGER.debug("[frontend]   - %s", feat.name)

    # 2. Determine which features need doc regeneration
    full_scan = changed_files is None
    if full_scan:
        LOGGER.info("[frontend] Mode: FULL SCAN — all features will be evaluated")
        candidates = all_features
    elif not changed_files:
        LOGGER.info("[frontend] Mode: INCREMENTAL — no frontend file changes")
        candidates = []
    else:
        LOGGER.info(
            "[frontend] Mode: INCREMENTAL — %d changed frontend file(s)",
            len(changed_files),
        )
        candidates = _identify_affected_features(changed_files, features_root)
        LOGGER.info("[frontend] Affected features: %d", len(candidates))
        for feat in candidates:
            LOGGER.info("[frontend]   -> %s", feat.name)

    # 3. Filter out features whose docs are already up-to-date
    to_generate = [
        feat
        for feat in candidates
        if should_regenerate(feat / ROOT_DOC_FILENAME, [feat])
    ]
    skipped = len(candidates) - len(to_generate)
    if skipped:
        LOGGER.info(
            "[frontend] Skipped %d feature(s) — docs already up-to-date", skipped
        )
    LOGGER.info("[frontend] Features needing generation: %d", len(to_generate))

    # 4. Root doc decision (structural: new/removed feature dirs)
    root_doc_path = (frontend_root / ROOT_DOC_FILENAME).resolve()
    regen_root = full_scan or should_regenerate_root(root_doc_path, all_features)
    if regen_root:
        LOGGER.info(
            "[frontend] Root doc will be regenerated (structural change detected)"
        )
    else:
        LOGGER.info("[frontend] Root doc is up-to-date — skipping")

    # 5. Early exit
    if not to_generate and not regen_root:
        elapsed = time.monotonic() - t0
        LOGGER.info(
            "[frontend] Nothing to do — all docs are current (%.1fs)", elapsed
        )
        return

    # 6. Parallel generation
    tasks: list[asyncio.Task] = []
    for feat in to_generate:
        tasks.append(asyncio.ensure_future(_generate_feature_doc(feat)))
    if regen_root:
        tasks.append(
            asyncio.ensure_future(
                _generate_root_doc(repo_root, frontend_root, all_features)
            )
        )

    LOGGER.info("[frontend] Launching %d parallel LLM task(s)...", len(tasks))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 7. Report
    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if isinstance(r, Exception))
    elapsed = time.monotonic() - t0
    LOGGER.info("[frontend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    LOGGER.info(
        "[frontend] Finished  | generated=%d  failed=%d  (%.1fs)",
        successes,
        failures,
        elapsed,
    )
    LOGGER.info("[frontend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for r in results:
        if isinstance(r, Exception):
            LOGGER.error("[frontend] Task error: %s", r, exc_info=r)


# ── Individual generators ─────────────────────────────────────────────


async def _generate_feature_doc(feature_dir: Path) -> bool:
    """Generate documentation for a single feature directory."""
    label = f"feature:{feature_dir.name}"
    LOGGER.info("[frontend] >> Generating doc for %s", feature_dir.name)
    t0 = time.monotonic()

    content = await _render_feature_with_llm(feature_dir, label)
    if content:
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info(
            "[frontend] LLM unavailable for %s — using scaffold", feature_dir.name
        )
        result = render_frontend_feature_document(feature_dir)

    doc_path = feature_dir / ROOT_DOC_FILENAME
    _write_with_metadata(
        doc_path, result, sources=[feature_dir], doc_type="frontend-feature"
    )
    elapsed = time.monotonic() - t0
    LOGGER.info("[frontend] << %s done (%.1fs)", feature_dir.name, elapsed)
    return True


async def _generate_root_doc(
    repo_root: Path, frontend_root: Path, all_features: list[Path]
) -> bool:
    """Generate the root frontend documentation."""
    LOGGER.info("[frontend] >> Generating root document")
    t0 = time.monotonic()

    content = await _render_root_with_llm(repo_root, frontend_root)
    if content:
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info("[frontend] LLM unavailable for root — using scaffold")
        result = render_frontend_root_document(repo_root)

    doc_path = (frontend_root / ROOT_DOC_FILENAME).resolve()
    structure_hash = compute_structure_fingerprint(all_features)
    # Root docs use structure_hash as source_hash — avoids hashing the
    # entire frontend/ tree (node_modules alone can be 100k+ files).
    result = DocRenderResult(content=result.content, source_hash=structure_hash)
    _write_with_metadata(
        doc_path,
        result,
        sources=[frontend_root],
        doc_type="frontend-root",
        structure_hash=structure_hash,
    )
    elapsed = time.monotonic() - t0
    LOGGER.info("[frontend] << Root document done (%.1fs)", elapsed)
    return True


# ── Metadata helpers ──────────────────────────────────────────────────


def _write_with_metadata(
    doc_path: Path,
    result: DocRenderResult,
    sources: Iterable[Path],
    doc_type: str,
    structure_hash: str = "",
) -> None:
    if not result.source_hash:
        result = DocRenderResult(
            content=result.content, source_hash=compute_sources_hash(sources)
        )
    write_if_changed(doc_path, result.content)
    metadata = build_metadata(
        source_hash=result.source_hash,
        agent_version=AGENT_VERSION,
        doc_type=doc_type,
        sources=sources,
        generated_at=datetime.now(timezone.utc).isoformat(),
        structure_hash=structure_hash,
    )
    save_metadata(doc_path, metadata)


# ── Discovery helpers ─────────────────────────────────────────────────


def _list_all_features(features_root: Path) -> list[Path]:
    """List every feature directory under src/features/."""
    if not features_root.exists():
        LOGGER.warning("[frontend] Features directory not found: %s", features_root)
        return []
    return sorted(p for p in features_root.iterdir() if p.is_dir())


def _identify_affected_features(
    changed_files: Iterable[Path], features_root: Path
) -> list[Path]:
    """Map changed files back to their parent feature directories."""
    feature_dirs: set[Path] = set()
    for path in changed_files:
        if not _is_child(path, features_root):
            continue
        try:
            relative = path.resolve().relative_to(features_root)
        except ValueError:
            continue
        if relative.parts:
            candidate = features_root / relative.parts[0]
            if candidate.exists() and candidate.is_dir():
                feature_dirs.add(candidate.resolve())
    return sorted(feature_dirs)


def _is_child(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ── LLM rendering ─────────────────────────────────────────────────────


async def _render_root_with_llm(
    repo_root: Path, frontend_root: Path
) -> str | None:
    prompt = load_prompt("frontend_root")
    tree = render_directory_tree(
        frontend_root, max_depth=3, exclude_dirs=["node_modules", "dist", ".git"]
    )
    filled = prompt.format(directory_tree=tree)
    return await generate_markdown(filled, label="frontend-root")


async def _render_feature_with_llm(
    feature_dir: Path, label: str
) -> str | None:
    prompt = load_prompt("frontend_feature")
    source = _read_feature_sources(feature_dir)
    filled = prompt.format(source_path=str(feature_dir), source_content=source)
    return await generate_markdown(filled, label=label)


def _read_feature_sources(feature_dir: Path) -> str:
    allowed = {".js", ".jsx", ".ts", ".tsx", ".css"}
    files = [
        p
        for p in sorted(feature_dir.rglob("*"), key=str)
        if p.is_file() and p.suffix in allowed
    ]
    LOGGER.debug(
        "[frontend] %s: %d source file(s) found", feature_dir.name, len(files)
    )
    parts: list[str] = []
    for path in files[:5]:
        content = path.read_text(encoding="utf-8", errors="ignore")
        if len(content) > 6000:
            content = content[:6000] + "\n\n[TRUNCATED]\n"
        parts.append(f"---\n{path}\n---\n{content}")
    return "\n\n".join(parts) if parts else "No source files found."


def _resolve_frontend_root(repo_root: Path) -> Path:
    candidate = (repo_root / "frontend").resolve()
    return candidate if candidate.exists() else repo_root.resolve()

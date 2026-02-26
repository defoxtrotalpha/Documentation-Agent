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
    render_backend_endpoint_document,
    render_backend_root_document,
    render_directory_tree,
    save_metadata,
    should_regenerate,
    should_regenerate_root,
    write_if_changed,
)

LOGGER = logging.getLogger(__name__)
AGENT_VERSION = "0.2"


# ── Public entry point ────────────────────────────────────────────────


async def generate_backend_docs(
    repo_root: Path,
    changed_files: list[Path] | None = None,
) -> None:
    """
    Generate backend documentation with true parallelism.

    - changed_files=None  →  full scan (regenerate everything)
    - changed_files=[]    →  no changes (skip all)
    - changed_files=[..]  →  incremental (only affected docs)
    """
    LOGGER.info("[backend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    LOGGER.info("[backend] Starting backend documentation agent")
    LOGGER.info("[backend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    t0 = time.monotonic()
    repo_root = repo_root.resolve()
    backend_root = _resolve_backend_root(repo_root)
    endpoints_root = (backend_root / "api" / "v1" / "endpoints").resolve()

    # 1. Discover ALL endpoint source files (needed for structure comparison)
    all_endpoints = _list_all_endpoints(endpoints_root)
    LOGGER.info("[backend] Total endpoints on disk: %d", len(all_endpoints))
    for ep in all_endpoints:
        LOGGER.debug("[backend]   - %s", ep.stem)

    # 2. Determine which endpoints need doc regeneration
    full_scan = changed_files is None
    if full_scan:
        LOGGER.info("[backend] Mode: FULL SCAN — all endpoints will be evaluated")
        candidates = all_endpoints
    elif not changed_files:
        LOGGER.info("[backend] Mode: INCREMENTAL — no backend file changes")
        candidates = []
    else:
        LOGGER.info(
            "[backend] Mode: INCREMENTAL — %d changed backend file(s)",
            len(changed_files),
        )
        candidates = _filter_changed_endpoints(changed_files, endpoints_root)
        LOGGER.info("[backend] Changed endpoints: %d", len(candidates))
        for ep in candidates:
            LOGGER.info("[backend]   -> %s", ep.stem)

    # 3. Filter out endpoints whose docs are already up-to-date (source hash match)
    to_generate = [
        ep
        for ep in candidates
        if should_regenerate(_endpoint_doc_path(ep), [ep])
    ]
    skipped = len(candidates) - len(to_generate)
    if skipped:
        LOGGER.info(
            "[backend] Skipped %d endpoint(s) — docs already up-to-date", skipped
        )
    LOGGER.info("[backend] Endpoints needing generation: %d", len(to_generate))

    # 4. Decide if root doc needs regeneration (structural change: added/removed endpoints)
    root_doc_path = (backend_root / ROOT_DOC_FILENAME).resolve()
    regen_root = full_scan or should_regenerate_root(root_doc_path, all_endpoints)
    if regen_root:
        LOGGER.info("[backend] Root doc will be regenerated (structural change detected)")
    else:
        LOGGER.info("[backend] Root doc is up-to-date — skipping")

    # 5. Early exit if nothing to do
    if not to_generate and not regen_root:
        elapsed = time.monotonic() - t0
        LOGGER.info(
            "[backend] Nothing to do — all docs are current (%.1fs)", elapsed
        )
        return

    # 6. Launch ALL generation tasks in parallel
    tasks: list[asyncio.Task] = []
    for ep in to_generate:
        tasks.append(
            asyncio.ensure_future(_generate_endpoint_doc(ep, backend_root))
        )
    if regen_root:
        tasks.append(
            asyncio.ensure_future(
                _generate_root_doc(repo_root, backend_root, all_endpoints)
            )
        )

    LOGGER.info("[backend] Launching %d parallel LLM task(s)...", len(tasks))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 7. Report
    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if isinstance(r, Exception))
    elapsed = time.monotonic() - t0
    LOGGER.info("[backend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    LOGGER.info(
        "[backend] Finished  | generated=%d  failed=%d  (%.1fs)",
        successes,
        failures,
        elapsed,
    )
    LOGGER.info("[backend] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for r in results:
        if isinstance(r, Exception):
            LOGGER.error("[backend] Task error: %s", r, exc_info=r)


# ── Individual generators ─────────────────────────────────────────────


async def _generate_endpoint_doc(
    endpoint_path: Path, backend_root: Path
) -> bool:
    """Generate documentation for a single endpoint file."""
    label = f"endpoint:{endpoint_path.stem}"
    LOGGER.info("[backend] >> Generating doc for %s", endpoint_path.stem)
    t0 = time.monotonic()

    content = await _render_endpoint_with_llm(endpoint_path, label)
    if content:
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info(
            "[backend] LLM unavailable for %s — using scaffold", endpoint_path.stem
        )
        result = render_backend_endpoint_document(endpoint_path)

    doc_dir = endpoint_path.parent / endpoint_path.stem
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_path = doc_dir / ROOT_DOC_FILENAME
    _write_with_metadata(
        doc_path, result, sources=[endpoint_path], doc_type="backend-endpoint"
    )
    elapsed = time.monotonic() - t0
    LOGGER.info("[backend] << %s done (%.1fs)", endpoint_path.stem, elapsed)
    return True


async def _generate_root_doc(
    repo_root: Path, backend_root: Path, all_endpoints: list[Path]
) -> bool:
    """Generate the root backend documentation."""
    LOGGER.info("[backend] >> Generating root document")
    t0 = time.monotonic()

    content = await _render_root_with_llm(repo_root, backend_root)
    if content:
        result = DocRenderResult(content=content, source_hash="")
    else:
        LOGGER.info("[backend] LLM unavailable for root — using scaffold")
        result = render_backend_root_document(repo_root)

    doc_path = (backend_root / ROOT_DOC_FILENAME).resolve()
    structure_hash = compute_structure_fingerprint(all_endpoints)
    # Root docs use structure_hash as source_hash — avoids hashing the
    # entire backend/ tree (which is slow and unnecessary; the root doc
    # only needs to regenerate when endpoints are added or removed).
    result = DocRenderResult(content=result.content, source_hash=structure_hash)
    _write_with_metadata(
        doc_path,
        result,
        sources=[backend_root],
        doc_type="backend-root",
        structure_hash=structure_hash,
    )
    elapsed = time.monotonic() - t0
    LOGGER.info("[backend] << Root document done (%.1fs)", elapsed)
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


def _list_all_endpoints(endpoints_root: Path) -> list[Path]:
    """List every *.py endpoint file (excluding __init__.py)."""
    if not endpoints_root.exists():
        LOGGER.warning("[backend] Endpoints directory not found: %s", endpoints_root)
        return []
    return sorted(
        p for p in endpoints_root.glob("*.py") if p.name != "__init__.py"
    )


def _filter_changed_endpoints(
    changed_files: Iterable[Path], endpoints_root: Path
) -> list[Path]:
    """From a set of changed files, return only those that are endpoint sources."""
    return sorted(
        {
            p.resolve()
            for p in changed_files
            if p.suffix == ".py"
            and p.name != "__init__.py"
            and _is_child(p, endpoints_root)
        }
    )


def _endpoint_doc_path(endpoint_path: Path) -> Path:
    return endpoint_path.parent / endpoint_path.stem / ROOT_DOC_FILENAME


def _is_child(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ── LLM rendering ─────────────────────────────────────────────────────


async def _render_root_with_llm(
    repo_root: Path, backend_root: Path
) -> str | None:
    prompt = load_prompt("backend_root")
    tree = render_directory_tree(
        backend_root, max_depth=3, exclude_dirs=["__pycache__", ".venv", ".git"]
    )
    filled = prompt.format(directory_tree=tree)
    return await generate_markdown(filled, label="backend-root")


async def _render_endpoint_with_llm(
    endpoint_path: Path, label: str
) -> str | None:
    prompt = load_prompt("backend_endpoint")
    source = _read_text_limited(endpoint_path, limit=12_000)
    filled = prompt.format(source_path=str(endpoint_path), source_content=source)
    return await generate_markdown(filled, label=label)


def _read_text_limited(path: Path, limit: int) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text if len(text) <= limit else text[:limit] + "\n\n[TRUNCATED]\n"


def _resolve_backend_root(repo_root: Path) -> Path:
    candidate = (repo_root / "backend").resolve()
    return candidate if candidate.exists() else repo_root.resolve()

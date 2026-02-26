from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .doc_generator import (
    format_mermaid_diagram,
    generate_document,
    generate_section,
    render_directory_tree,
)

LOGGER = logging.getLogger(__name__)

DOC_METADATA_FILENAME = "_doc_metadata.json"
ROOT_DOC_FILENAME = "documentation.md"
DETAIL_DOC_FILENAME = "documentation.md"
METADATA_VERSION = 2  # v2: structure-aware root metadata


@dataclass(frozen=True)
class DocRenderResult:
    content: str
    source_hash: str


# ── Hashing ───────────────────────────────────────────────────────────


# Directories that should never be crawled when computing hashes.
_HASH_EXCLUDE_DIRS: set[str] = {
    "node_modules", "dist", "build", ".git", "__pycache__", ".venv", "venv",
    ".next", ".nuxt", ".output", "coverage", ".pytest_cache", ".mypy_cache",
}


def compute_sources_hash(paths: Iterable[Path]) -> str:
    """Content-based hash for a set of source files / directories."""
    digest = hashlib.sha256()
    for path in sorted({p.resolve() for p in paths}, key=str):
        _hash_path(digest, path)
    return digest.hexdigest()


def compute_structure_fingerprint(items: Iterable[Path]) -> str:
    """
    Hash based on sorted *names* only.
    Changes when endpoints / features are added or removed,
    but NOT when their content is edited.
    """
    names = sorted(p.name for p in items)
    return hashlib.sha256("\n".join(names).encode()).hexdigest()


def _hash_path(digest: "hashlib._Hash", path: Path) -> None:
    digest.update(str(path).encode())
    if not path.exists():
        return
    if path.is_dir():
        for item in sorted(path.rglob("*"), key=str):
            # Skip excluded directories and everything below them
            if item.is_dir():
                continue
            if any(part in _HASH_EXCLUDE_DIRS for part in item.parts):
                continue
            digest.update(str(item).encode())
            digest.update(item.read_bytes())
        return
    digest.update(path.read_bytes())


# ── Metadata I/O ──────────────────────────────────────────────────────


def load_metadata(doc_path: Path) -> dict:
    meta_path = doc_path.parent / DOC_METADATA_FILENAME
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_metadata(doc_path: Path, metadata: dict) -> None:
    meta_path = doc_path.parent / DOC_METADATA_FILENAME
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def build_metadata(
    *,
    source_hash: str,
    agent_version: str,
    doc_type: str,
    sources: Iterable[Path],
    generated_at: str,
    structure_hash: str = "",
) -> dict:
    meta: dict = {
        "metadata_version": METADATA_VERSION,
        "generated_at": generated_at,
        "source_hash": source_hash,
        "agent_version": agent_version,
        "doc_type": doc_type,
        "sources": [str(p.resolve()) for p in sources],
    }
    if structure_hash:
        meta["structure_hash"] = structure_hash
    return meta


# ── Regeneration checks ──────────────────────────────────────────────


def should_regenerate(doc_path: Path, sources: Iterable[Path]) -> bool:
    """Check whether an individual doc (endpoint / feature) needs regeneration."""
    if not doc_path.exists():
        LOGGER.info("[meta] %s missing — regeneration needed", doc_path.name)
        return True
    meta = load_metadata(doc_path)
    if meta.get("metadata_version") != METADATA_VERSION:
        LOGGER.info(
            "[meta] %s metadata version mismatch — regeneration needed",
            doc_path.name,
        )
        return True
    current_hash = compute_sources_hash(sources)
    if meta.get("source_hash") != current_hash:
        LOGGER.info("[meta] %s source hash changed — regeneration needed", doc_path.name)
        return True
    LOGGER.info("[meta] %s is up-to-date — skipping", doc_path.name)
    return False


def should_regenerate_root(doc_path: Path, current_items: Iterable[Path]) -> bool:
    """
    Check whether a root doc needs regeneration.
    Based on *structure fingerprint* (sorted item names) rather than content hash,
    so that content-only edits to individual items do NOT trigger root regeneration.
    """
    if not doc_path.exists():
        LOGGER.info("[meta] Root doc %s missing — regeneration needed", doc_path.name)
        return True
    meta = load_metadata(doc_path)
    if meta.get("metadata_version") != METADATA_VERSION:
        LOGGER.info(
            "[meta] Root doc %s metadata version mismatch — regeneration needed",
            doc_path.name,
        )
        return True
    current_fp = compute_structure_fingerprint(current_items)
    stored_fp = meta.get("structure_hash", "")
    if stored_fp != current_fp:
        LOGGER.info(
            "[meta] Root doc %s structure changed — regeneration needed", doc_path.name
        )
        return True
    LOGGER.info("[meta] Root doc %s structure unchanged — skipping", doc_path.name)
    return False


# ── File writing ──────────────────────────────────────────────────────


def write_if_changed(doc_path: Path, content: str) -> bool:
    """Write *content* to *doc_path* only when it differs.  Returns True if written."""
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    if doc_path.exists() and doc_path.read_text(encoding="utf-8") == content:
        LOGGER.debug("[write] %s unchanged — skipped", doc_path.name)
        return False
    doc_path.write_text(content, encoding="utf-8")
    LOGGER.info("[write] Wrote %s (%d chars)", doc_path, len(content))
    return True


# ── Scaffold renderers (fallback when LLM is unavailable) ────────────


def render_backend_root_document(repo_root: Path) -> DocRenderResult:
    backend_root = _resolve_backend(repo_root)
    tree = render_directory_tree(
        backend_root, max_depth=3, exclude_dirs=["__pycache__", ".venv", ".git"]
    )
    overview = (
        "This document provides a high-level map of the backend codebase, "
        "including core modules, API endpoints, and supporting services."
    )
    sections = [
        generate_section("Overview", overview),
        generate_section("Directory Tree", f"```\n{tree}\n```"),
        format_mermaid_diagram(
            "Request Flow",
            "flowchart LR\n    Client --> API\n    API --> Services\n    Services --> Storage",
        ),
    ]
    content = generate_document("Backend Documentation", sections)
    return DocRenderResult(content=content, source_hash=compute_sources_hash([backend_root]))


def render_frontend_root_document(repo_root: Path) -> DocRenderResult:
    frontend_root = _resolve_frontend(repo_root)
    tree = render_directory_tree(
        frontend_root, max_depth=3, exclude_dirs=["node_modules", "dist", ".git"]
    )
    overview = (
        "This document describes the frontend structure, key features, "
        "and how application state flows through the UI."
    )
    sections = [
        generate_section("Overview", overview),
        generate_section("Directory Tree", f"```\n{tree}\n```"),
        format_mermaid_diagram(
            "UI Flow",
            "flowchart LR\n    User --> UI\n    UI --> State\n    State --> API",
        ),
    ]
    content = generate_document("Frontend Documentation", sections)
    return DocRenderResult(
        content=content, source_hash=compute_sources_hash([frontend_root])
    )


def render_backend_endpoint_document(endpoint_path: Path) -> DocRenderResult:
    endpoint_path = endpoint_path.resolve()
    sections = [
        generate_section(
            "Overview",
            "Describe the endpoint purpose, request/response shapes, "
            "and any validation or authorization requirements.",
        ),
        generate_section("Routes", "- List API routes here."),
        generate_section("Request", "- Document input models and parameters."),
        generate_section("Response", "- Document response models and status codes."),
        generate_section("Dependencies", "- List services, clients, and helpers."),
        format_mermaid_diagram(
            "Endpoint Flow",
            "flowchart TD\n    Client --> Endpoint\n    Endpoint --> Services\n    Services --> Storage",
        ),
    ]
    content = generate_document(f"Endpoint: {endpoint_path.stem}", sections)
    return DocRenderResult(
        content=content, source_hash=compute_sources_hash([endpoint_path])
    )


def render_frontend_feature_document(feature_dir: Path) -> DocRenderResult:
    feature_dir = feature_dir.resolve()
    sections = [
        generate_section(
            "Overview",
            "Describe the feature purpose, main components, state management, "
            "and API interactions.",
        ),
        generate_section("Components", "- List main components and responsibilities."),
        generate_section("State", "- Document context/hooks/state usage."),
        generate_section("API", "- Document API calls and payloads."),
        generate_section("Dependencies", "- List shared utilities and modules."),
        format_mermaid_diagram(
            "Feature Flow",
            "flowchart TD\n    User --> Component\n    Component --> State\n    State --> API",
        ),
    ]
    content = generate_document(f"Feature: {feature_dir.name}", sections)
    return DocRenderResult(
        content=content, source_hash=compute_sources_hash([feature_dir])
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _resolve_backend(repo_root: Path) -> Path:
    candidate = (repo_root / "backend").resolve()
    return candidate if candidate.exists() else repo_root.resolve()


def _resolve_frontend(repo_root: Path) -> Path:
    candidate = (repo_root / "frontend").resolve()
    return candidate if candidate.exists() else repo_root.resolve()

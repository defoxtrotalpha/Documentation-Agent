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
METADATA_VERSION = 1


@dataclass(frozen=True)
class DocRenderResult:
    content: str
    source_hash: str


def compute_sources_hash(paths: Iterable[Path]) -> str:
    """Compute a stable hash for a set of source files."""
    digest = hashlib.sha256()
    for path in sorted({p.resolve() for p in paths}, key=lambda p: str(p)):
        _update_hash_for_path(digest, path)
    return digest.hexdigest()


def _update_hash_for_path(digest: "hashlib._Hash", path: Path) -> None:
    digest.update(str(path).encode("utf-8"))
    if not path.exists():
        return
    if path.is_dir():
        for item in sorted(path.rglob("*"), key=lambda p: str(p)):
            if not item.is_file():
                continue
            digest.update(str(item).encode("utf-8"))
            digest.update(item.read_bytes())
        return
    digest.update(path.read_bytes())


def load_metadata(doc_path: Path) -> dict:
    metadata_path = doc_path.parent / DOC_METADATA_FILENAME
    if not metadata_path.exists():
        return {}
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_metadata(doc_path: Path, metadata: dict) -> None:
    metadata_path = doc_path.parent / DOC_METADATA_FILENAME
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def should_regenerate(doc_path: Path, sources: Iterable[Path]) -> bool:
    if not doc_path.exists():
        LOGGER.info("[scaffold] %s does not exist — regeneration needed", doc_path.name)
        return True
    existing = load_metadata(doc_path)
    if existing.get("metadata_version") != METADATA_VERSION:
        LOGGER.info("[scaffold] Metadata version mismatch for %s — regeneration needed", doc_path.name)
        return True
    source_hash = compute_sources_hash(sources)
    if existing.get("source_hash") != source_hash:
        LOGGER.info("[scaffold] Source hash changed for %s — regeneration needed", doc_path.name)
        return True
    LOGGER.info("[scaffold] %s is up to date — no regeneration needed", doc_path.name)
    return False


def build_metadata(
    *,
    source_hash: str,
    agent_version: str,
    doc_type: str,
    sources: Iterable[Path],
    generated_at: str,
) -> dict:
    return {
        "metadata_version": METADATA_VERSION,
        "generated_at": generated_at,
        "source_hash": source_hash,
        "agent_version": agent_version,
        "doc_type": doc_type,
        "sources": [str(path.resolve()) for path in sources],
    }


def write_if_changed(doc_path: Path, content: str) -> None:
    if doc_path.exists() and doc_path.read_text(encoding="utf-8") == content:
        LOGGER.debug("[scaffold] %s content unchanged — skipping write", doc_path.name)
        return
    LOGGER.info("[scaffold] Writing %s (%d chars)", doc_path, len(content))
    doc_path.write_text(content, encoding="utf-8")


def render_backend_root_document(repo_root: Path) -> DocRenderResult:
    backend_root = _resolve_backend_root(repo_root)
    tree = render_directory_tree(
        backend_root,
        max_depth=3,
        exclude_dirs=["__pycache__", ".venv", ".git"],
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
    source_hash = compute_sources_hash([backend_root])
    return DocRenderResult(content=content, source_hash=source_hash)


def render_frontend_root_document(repo_root: Path) -> DocRenderResult:
    frontend_root = _resolve_frontend_root(repo_root)
    tree = render_directory_tree(
        frontend_root,
        max_depth=3,
        exclude_dirs=["node_modules", "dist", ".git"],
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
    source_hash = compute_sources_hash([frontend_root])
    return DocRenderResult(content=content, source_hash=source_hash)


def render_backend_endpoint_document(endpoint_path: Path) -> DocRenderResult:
    endpoint_path = endpoint_path.resolve()
    overview = (
        "Describe the endpoint purpose, request/response shapes, and any "
        "validation or authorization requirements."
    )
    sections = [
        generate_section("Overview", overview),
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
    source_hash = compute_sources_hash([endpoint_path])
    return DocRenderResult(content=content, source_hash=source_hash)


def render_frontend_feature_document(feature_dir: Path) -> DocRenderResult:
    feature_dir = feature_dir.resolve()
    overview = (
        "Describe the feature purpose, main components, state management, "
        "and API interactions."
    )
    sections = [
        generate_section("Overview", overview),
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
    source_hash = compute_sources_hash([feature_dir])
    return DocRenderResult(content=content, source_hash=source_hash)


def _resolve_backend_root(repo_root: Path) -> Path:
    repo_root = repo_root.resolve()
    backend_root = repo_root / "backend"
    if backend_root.exists():
        return backend_root.resolve()
    return repo_root


def _resolve_frontend_root(repo_root: Path) -> Path:
    repo_root = repo_root.resolve()
    frontend_root = repo_root / "frontend"
    if frontend_root.exists():
        return frontend_root.resolve()
    return repo_root

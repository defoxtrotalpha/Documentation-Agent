"""Utilities for documentation agents."""

from .doc_generator import (
    format_mermaid_diagram,
    generate_document,
    generate_section,
    render_directory_tree,
)
from .doc_scaffold import (
    DETAIL_DOC_FILENAME,
    DOC_METADATA_FILENAME,
    METADATA_VERSION,
    ROOT_DOC_FILENAME,
    DocRenderResult,
    build_metadata,
    compute_sources_hash,
    compute_structure_fingerprint,
    load_metadata,
    render_backend_endpoint_document,
    render_backend_root_document,
    render_frontend_feature_document,
    render_frontend_root_document,
    save_metadata,
    should_regenerate,
    should_regenerate_root,
    write_if_changed,
)
from .git_analyzer import ChangeSet, get_changed_files, get_staged_files
from .llm_client import (
    LLMConfig,
    generate_markdown,
    generate_markdown_sync,
    is_llm_configured,
    load_llm_config,
)
from .prompt_loader import load_prompt

__all__ = [
    "ChangeSet",
    "DETAIL_DOC_FILENAME",
    "DOC_METADATA_FILENAME",
    "DocRenderResult",
    "LLMConfig",
    "METADATA_VERSION",
    "ROOT_DOC_FILENAME",
    "build_metadata",
    "compute_sources_hash",
    "compute_structure_fingerprint",
    "format_mermaid_diagram",
    "generate_document",
    "generate_markdown",
    "generate_markdown_sync",
    "generate_section",
    "get_changed_files",
    "get_staged_files",
    "is_llm_configured",
    "load_llm_config",
    "load_metadata",
    "load_prompt",
    "render_backend_endpoint_document",
    "render_backend_root_document",
    "render_directory_tree",
    "render_frontend_feature_document",
    "render_frontend_root_document",
    "save_metadata",
    "should_regenerate",
    "should_regenerate_root",
    "write_if_changed",
]

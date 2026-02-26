"""Utilities for documentation agents."""

from .doc_generator import format_mermaid_diagram, generate_document, generate_section, render_directory_tree
from .doc_scaffold import (
	DETAIL_DOC_FILENAME,
	DOC_METADATA_FILENAME,
	ROOT_DOC_FILENAME,
	METADATA_VERSION,
	DocRenderResult,
	build_metadata,
	compute_sources_hash,
	load_metadata,
	render_backend_endpoint_document,
	render_backend_root_document,
	render_frontend_feature_document,
	render_frontend_root_document,
	save_metadata,
	should_regenerate,
	write_if_changed,
)
from .git_analyzer import ChangeSet, get_changed_files
from .llm_client import LLMConfig, generate_markdown_sync, is_llm_configured, load_llm_config
from .prompt_loader import load_prompt

__all__ = [
	"ChangeSet",
	"DETAIL_DOC_FILENAME",
	"DOC_METADATA_FILENAME",
	"METADATA_VERSION",
	"DocRenderResult",
	"ROOT_DOC_FILENAME",
	"build_metadata",
	"compute_sources_hash",
	"format_mermaid_diagram",
	"generate_document",
	"generate_section",
	"get_changed_files",
	"generate_markdown_sync",
	"is_llm_configured",
	"load_llm_config",
	"load_prompt",
	"LLMConfig",
	"load_metadata",
	"render_backend_endpoint_document",
	"render_backend_root_document",
	"render_frontend_feature_document",
	"render_frontend_root_document",
	"render_directory_tree",
	"save_metadata",
	"should_regenerate",
	"write_if_changed",
]

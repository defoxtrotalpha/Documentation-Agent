from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

if __package__ is None:  # Allow running as a script without -m
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(repo_root))

from backend.documentation_agent.backend_doc_agent import generate_backend_docs
from backend.documentation_agent.frontend_doc_agent import generate_frontend_docs
from backend.documentation_agent.utils import get_changed_files, get_staged_files

LOGGER = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────


def run_documentation_agents(
    repo_root: Path,
    from_ref: str = "HEAD~1",
    to_ref: str = "HEAD",
    full_scan: bool = False,
    staged: bool = False,
) -> None:
    """
    Entry point — resolves changes, then launches async orchestration.

    Modes:
      --full-scan   Evaluate every doc regardless of changes.
      --staged      Diff against git index (use in pre-commit hooks).
      (default)     Diff between --from-ref and --to-ref.
    """
    LOGGER.info("=" * 60)
    LOGGER.info("  Documentation Agent — Starting")
    LOGGER.info("=" * 60)
    mode = (
        "full-scan"
        if full_scan
        else ("staged" if staged else f"diff {from_ref}..{to_ref}")
    )
    LOGGER.info("  repo_root : %s", repo_root)
    LOGGER.info("  mode      : %s", mode)

    # Load .env once at startup so LLM config is available to both agents
    _load_env(repo_root)

    if full_scan:
        LOGGER.info("  Full-scan mode — all docs will be evaluated")
        backend_changes = None
        frontend_changes = None
    elif staged:
        LOGGER.info("  Staged mode — reading git index")
        change_set = get_staged_files(repo_root)
        if not change_set.has_changes:
            LOGGER.info("  No staged changes — nothing to do")
            return
        backend_changes = list(change_set.backend_files)
        frontend_changes = list(change_set.frontend_files)
        _log_change_summary(change_set)
    else:
        LOGGER.info("  Diff mode — comparing %s..%s", from_ref, to_ref)
        change_set = get_changed_files(repo_root, from_ref=from_ref, to_ref=to_ref)
        if not change_set.has_changes:
            LOGGER.info("  No changes detected — nothing to do")
            return
        backend_changes = list(change_set.backend_files)
        frontend_changes = list(change_set.frontend_files)
        _log_change_summary(change_set)

    asyncio.run(_orchestrate(repo_root, backend_changes, frontend_changes))


# ── Async orchestration ──────────────────────────────────────────────


async def _orchestrate(
    repo_root: Path,
    backend_changes: list[Path] | None,
    frontend_changes: list[Path] | None,
) -> None:
    """Run backend and frontend agents concurrently."""
    LOGGER.info("Launching backend + frontend agents in parallel...")
    t0 = time.monotonic()

    results = await asyncio.gather(
        generate_backend_docs(repo_root, backend_changes),
        generate_frontend_docs(repo_root, frontend_changes),
        return_exceptions=True,
    )

    elapsed = time.monotonic() - t0
    for i, label in enumerate(["backend", "frontend"]):
        if isinstance(results[i], Exception):
            LOGGER.error(
                "Agent '%s' raised an exception: %s",
                label,
                results[i],
                exc_info=results[i],
            )

    LOGGER.info("=" * 60)
    LOGGER.info("  Documentation Agent — Complete (%.1fs)", elapsed)
    LOGGER.info("=" * 60)


# ── Helpers ───────────────────────────────────────────────────────────


def _load_env(repo_root: Path) -> None:
    """Load .env from backend/ or repo root (first found wins)."""
    for candidate in [
        repo_root / "backend" / ".env",
        repo_root / ".env",
    ]:
        if candidate.exists():
            LOGGER.info("Loading environment from %s", candidate)
            load_dotenv(candidate)
            return
    LOGGER.warning("No .env file found — LLM generation may be disabled")


def _log_change_summary(change_set) -> None:
    other = (
        len(change_set.all_files)
        - len(change_set.backend_files)
        - len(change_set.frontend_files)
    )
    LOGGER.info(
        "  Changes — backend=%d  frontend=%d  other=%d",
        len(change_set.backend_files),
        len(change_set.frontend_files),
        other,
    )


# ── CLI ───────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run documentation agents.")
    parser.add_argument(
        "--repo-root", default=".", help="Path to the repository root"
    )
    parser.add_argument(
        "--from-ref", default="HEAD~1", help="Git ref to diff from"
    )
    parser.add_argument("--to-ref", default="HEAD", help="Git ref to diff to")
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Regenerate all docs regardless of changes",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Use staged (cached) files — for pre-commit hooks",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = _build_parser()
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    LOGGER.info("CLI invoked — repo_root=%s", repo_root)

    if repo_root.name == "backend" and (repo_root / "api").exists():
        repo_root = repo_root.parent
        LOGGER.info("Adjusted repo_root to %s", repo_root)

    run_documentation_agents(
        repo_root,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        full_scan=args.full_scan,
        staged=args.staged,
    )


if __name__ == "__main__":
    main()

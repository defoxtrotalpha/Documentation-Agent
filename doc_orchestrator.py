from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

if __package__ is None:  # Allow running as a script without -m
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(repo_root))

from backend.documentation_agent.backend_doc_agent import generate_backend_docs
from backend.documentation_agent.frontend_doc_agent import generate_frontend_docs
from backend.documentation_agent.utils import get_changed_files

LOGGER = logging.getLogger(__name__)


def run_documentation_agents(
    repo_root: Path,
    from_ref: str = "HEAD~1",
    to_ref: str = "HEAD",
    full_scan: bool = False,
) -> None:
    LOGGER.info("[orchestrator] Starting documentation generation (repo_root=%s, full_scan=%s)", repo_root, full_scan)
    if full_scan:
        LOGGER.info("[orchestrator] Full scan mode — processing all files")
        backend_changes = None
        frontend_changes = None
    else:
        LOGGER.info("[orchestrator] Incremental mode — diffing %s..%s", from_ref, to_ref)
        change_set = get_changed_files(repo_root, from_ref=from_ref, to_ref=to_ref)
        backend_changes = list(change_set.backend_files)
        frontend_changes = list(change_set.frontend_files)
        LOGGER.info(
            "[orchestrator] Detected changes — backend=%d files, frontend=%d files, total=%d files",
            len(backend_changes), len(frontend_changes), len(change_set.all_files),
        )

    asyncio.run(
        _run_parallel(
            repo_root,
            backend_changes=backend_changes,
            frontend_changes=frontend_changes,
        )
    )
    LOGGER.info("[orchestrator] Documentation generation complete")


async def _run_parallel(
    repo_root: Path,
    backend_changes: list[Path],
    frontend_changes: list[Path],
) -> None:
    LOGGER.info("[orchestrator] Launching parallel doc generation (backend + frontend)")
    await asyncio.gather(
        asyncio.to_thread(generate_backend_docs, repo_root, backend_changes),
        asyncio.to_thread(generate_frontend_docs, repo_root, frontend_changes),
    )
    LOGGER.info("[orchestrator] Both agents finished")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run documentation agents.")
    parser.add_argument("--repo-root", default=".", help="Path to the repository root")
    parser.add_argument("--from-ref", default="HEAD~1", help="Git ref to diff from")
    parser.add_argument("--to-ref", default="HEAD", help="Git ref to diff to")
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Regenerate all docs regardless of changes",
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
    LOGGER.info("[orchestrator] CLI invoked — raw repo_root=%s, resolved=%s", args.repo_root, repo_root)
    if repo_root.name == "backend" and (repo_root / "api").exists():
        repo_root = repo_root.parent
        LOGGER.info("[orchestrator] Detected backend dir passed as root — adjusted to %s", repo_root)
    run_documentation_agents(
        repo_root,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        full_scan=args.full_scan,
    )


if __name__ == "__main__":
    main()

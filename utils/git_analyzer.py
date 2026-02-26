from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeSet:
    """Categorized set of changed files from git."""

    all_files: tuple[Path, ...]
    backend_files: tuple[Path, ...]
    frontend_files: tuple[Path, ...]

    @property
    def has_changes(self) -> bool:
        return len(self.all_files) > 0

    @property
    def has_backend_changes(self) -> bool:
        return len(self.backend_files) > 0

    @property
    def has_frontend_changes(self) -> bool:
        return len(self.frontend_files) > 0


# ── Public API ────────────────────────────────────────────────────────


def get_changed_files(
    repo_root: Path,
    from_ref: str = "HEAD~1",
    to_ref: str = "HEAD",
) -> ChangeSet:
    """Return files changed between two git refs, categorized by area."""
    repo_root = repo_root.resolve()
    LOGGER.info("[git] Diffing refs %s..%s in %s", from_ref, to_ref, repo_root)
    if not _is_git_repo(repo_root):
        LOGGER.warning("[git] Not a git repository: %s", repo_root)
        return ChangeSet((), (), ())

    diff_files = _git_diff_refs(repo_root, from_ref, to_ref)
    if not diff_files:
        LOGGER.info("[git] Empty diff — falling back to git show %s", to_ref)
        diff_files = _git_show_name_only(repo_root, to_ref)

    change_set = _categorize(repo_root, diff_files)
    LOGGER.info(
        "[git] Ref diff — total=%d  backend=%d  frontend=%d",
        len(change_set.all_files),
        len(change_set.backend_files),
        len(change_set.frontend_files),
    )
    return change_set


def get_staged_files(repo_root: Path) -> ChangeSet:
    """Return files in the git staging area (for pre-commit hooks)."""
    repo_root = repo_root.resolve()
    LOGGER.info("[git] Detecting staged changes in %s", repo_root)
    if not _is_git_repo(repo_root):
        LOGGER.warning("[git] Not a git repository: %s", repo_root)
        return ChangeSet((), (), ())

    result = _run_git(
        repo_root, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    )
    if result.returncode != 0:
        LOGGER.warning("[git] git diff --cached failed (rc=%d)", result.returncode)
        return ChangeSet((), (), ())

    files = _paths_from_lines(repo_root, result.stdout.splitlines())
    change_set = _categorize(repo_root, files)
    LOGGER.info(
        "[git] Staged — total=%d  backend=%d  frontend=%d",
        len(change_set.all_files),
        len(change_set.backend_files),
        len(change_set.frontend_files),
    )
    return change_set


# ── Internal helpers ──────────────────────────────────────────────────


def _is_git_repo(repo_root: Path) -> bool:
    return _run_git(repo_root, ["rev-parse", "--git-dir"]).returncode == 0


def _git_diff_refs(
    repo_root: Path, from_ref: str, to_ref: str
) -> tuple[Path, ...]:
    result = _run_git(
        repo_root, ["diff", "--name-only", "--diff-filter=ACMR", from_ref, to_ref]
    )
    if result.returncode != 0:
        return ()
    return _paths_from_lines(repo_root, result.stdout.splitlines())


def _git_show_name_only(repo_root: Path, ref: str) -> tuple[Path, ...]:
    result = _run_git(repo_root, ["show", "--name-only", "--pretty=", ref])
    if result.returncode != 0:
        return ()
    return _paths_from_lines(repo_root, result.stdout.splitlines())


def _paths_from_lines(repo_root: Path, lines: Iterable[str]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            paths.append((repo_root / stripped).resolve())
    return tuple(paths)


def _categorize(repo_root: Path, files: Iterable[Path]) -> ChangeSet:
    backend_root = (repo_root / "backend").resolve()
    frontend_root = (repo_root / "frontend").resolve()
    all_f: list[Path] = []
    back: list[Path] = []
    front: list[Path] = []
    for f in files:
        all_f.append(f)
        if _is_child(f, backend_root):
            back.append(f)
        elif _is_child(f, frontend_root):
            front.append(f)
    return ChangeSet(tuple(all_f), tuple(back), tuple(front))


def _is_child(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _run_git(
    repo_root: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo_root), *args]
    LOGGER.debug("[git] %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        LOGGER.debug(
            "[git] rc=%d  stderr=%s", result.returncode, result.stderr.strip()
        )
    return result

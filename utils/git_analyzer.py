from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import subprocess
from typing import Iterable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeSet:
    all_files: tuple[Path, ...]
    backend_files: tuple[Path, ...]
    frontend_files: tuple[Path, ...]


def get_changed_files(
    repo_root: Path,
    from_ref: str = "HEAD~1",
    to_ref: str = "HEAD",
) -> ChangeSet:
    """Return changed files between two refs, categorized by backend/frontend."""
    repo_root = repo_root.resolve()
    LOGGER.info("[git_analyzer] Detecting changes in %s (%s..%s)", repo_root, from_ref, to_ref)
    if not _is_git_repo(repo_root):
        LOGGER.warning("[git_analyzer] Not a git repo: %s", repo_root)
        return ChangeSet((), (), ())

    diff_files = _git_name_only(repo_root, from_ref, to_ref)
    if not diff_files:
        LOGGER.info("[git_analyzer] No diff output — falling back to git show")
        diff_files = _git_show_name_only(repo_root, to_ref)

    change_set = _categorize_changes(repo_root, diff_files)
    LOGGER.info(
        "[git_analyzer] Changes detected — total=%d, backend=%d, frontend=%d",
        len(change_set.all_files), len(change_set.backend_files), len(change_set.frontend_files),
    )
    return change_set


def _is_git_repo(repo_root: Path) -> bool:
    result = _run_git(repo_root, ["rev-parse", "--git-dir"])
    return result.returncode == 0


def _git_name_only(repo_root: Path, from_ref: str, to_ref: str) -> tuple[Path, ...]:
    result = _run_git(repo_root, ["diff", "--name-only", from_ref, to_ref])
    if result.returncode != 0:
        return ()
    return _paths_from_lines(repo_root, result.stdout.splitlines())


def _git_show_name_only(repo_root: Path, to_ref: str) -> tuple[Path, ...]:
    result = _run_git(repo_root, ["show", "--name-only", "--pretty=", to_ref])
    if result.returncode != 0:
        return ()
    return _paths_from_lines(repo_root, result.stdout.splitlines())


def _paths_from_lines(repo_root: Path, lines: Iterable[str]) -> tuple[Path, ...]:
    files: list[Path] = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        files.append((repo_root / value).resolve())
    return tuple(files)


def _categorize_changes(repo_root: Path, files: Iterable[Path]) -> ChangeSet:
    backend: list[Path] = []
    frontend: list[Path] = []
    all_files: list[Path] = []
    backend_root = (repo_root / "backend").resolve()
    frontend_root = (repo_root / "frontend").resolve()

    for file_path in files:
        all_files.append(file_path)
        if _is_relative_to(file_path, backend_root):
            backend.append(file_path)
        elif _is_relative_to(file_path, frontend_root):
            frontend.append(file_path)

    return ChangeSet(tuple(all_files), tuple(backend), tuple(frontend))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo_root), *args]
    LOGGER.debug("[git_analyzer] Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        LOGGER.debug("[git_analyzer] Git command failed (rc=%d): %s", result.returncode, result.stderr.strip())
    return result

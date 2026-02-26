from __future__ import annotations

from pathlib import Path
from typing import Iterable


def generate_section(title: str, body: str) -> str:
    return f"## {title}\n\n{body.strip()}\n"


def generate_document(title: str, sections: Iterable[str]) -> str:
    content = [f"# {title}\n"]
    content.extend(sections)
    return "\n".join(content).rstrip() + "\n"


def render_directory_tree(
    root: Path,
    max_depth: int = 3,
    exclude_dirs: Iterable[str] | None = None,
) -> str:
    root = root.resolve()
    excluded = {name.lower() for name in (exclude_dirs or [])}
    lines: list[str] = [str(root.name)]

    for line in _walk_tree(root, prefix="", depth=0, max_depth=max_depth, excluded=excluded):
        lines.append(line)

    return "\n".join(lines)


def format_mermaid_diagram(title: str, diagram: str) -> str:
    diagram = diagram.strip("\n")
    return f"### {title}\n\n```mermaid\n{diagram}\n```\n"


def _walk_tree(
    root: Path,
    prefix: str,
    depth: int,
    max_depth: int,
    excluded: set[str],
):
    if depth >= max_depth:
        return

    entries = [p for p in sorted(root.iterdir(), key=lambda p: p.name.lower())]
    visible = [p for p in entries if p.name.lower() not in excluded]

    for index, entry in enumerate(visible):
        connector = "└── " if index == len(visible) - 1 else "├── "
        yield f"{prefix}{connector}{entry.name}"

        if entry.is_dir():
            extension = "    " if index == len(visible) - 1 else "│   "
            yield from _walk_tree(
                entry,
                prefix=prefix + extension,
                depth=depth + 1,
                max_depth=max_depth,
                excluded=excluded,
            )

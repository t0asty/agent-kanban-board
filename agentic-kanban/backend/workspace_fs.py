"""Sandboxed filesystem helpers for agent workspace (paths must stay under root)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_READ_BYTES = 512 * 1024
MAX_WRITE_BYTES = 2 * 1024 * 1024


def _user_path_to_relative(workspace_root: Path, user_path: str) -> str:
    """
    Turn a user-supplied path into a POSIX path relative to workspace_root.
    Accepts either a relative path (recommended) or an absolute path that lies
    inside the workspace (models often echo the full root + file).
    """
    root = workspace_root.resolve()
    raw = (user_path or ".").strip() or "."
    path_obj = Path(raw)
    try:
        if path_obj.is_absolute():
            resolved = path_obj.expanduser().resolve()
            rel = resolved.relative_to(root)
            return rel.as_posix()
        rel = (root / raw).resolve().relative_to(root)
        return rel.as_posix()
    except (ValueError, OSError) as e:
        raise ValueError(
            f"Path must be inside the workspace root ({root}). "
            f"Use relative paths such as '.' or 'kanban-agent-output/<card-id>/RUN.md'. "
            f"Original path: {raw!r}"
        ) from e


def _resolve_under_root(workspace_root: Path, relative_path: str) -> Path:
    root = workspace_root.resolve()
    rel = _user_path_to_relative(workspace_root, relative_path)
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise ValueError("Path escapes workspace root") from e
    return candidate


def workspace_list(workspace_root: Path, relative_path: str = ".") -> str:
    """Return a JSON string listing names and whether each entry is a directory."""
    try:
        rel_display = _user_path_to_relative(workspace_root, relative_path)
        target = _resolve_under_root(workspace_root, relative_path)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    if not target.exists():
        return json.dumps({"error": f"Not found: {rel_display}"})
    if not target.is_dir():
        return json.dumps({"error": f"Not a directory: {rel_display}"})
    root = workspace_root.resolve()
    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            try:
                entries.append(
                    {
                        "name": child.name,
                        "is_dir": child.is_dir(),
                        "path": child.resolve().relative_to(root).as_posix(),
                    }
                )
            except OSError as e:
                logger.warning("Skipping unreadable entry %s: %s", child, e)
    except OSError as e:
        return json.dumps({"error": f"Cannot read directory {rel_display}: {e}"})
    return json.dumps({"entries": entries})


def workspace_read(workspace_root: Path, relative_path: str) -> str:
    """Read a text file under the workspace (UTF-8, with replacement for invalid bytes)."""
    try:
        rel_display = _user_path_to_relative(workspace_root, relative_path)
        path = _resolve_under_root(workspace_root, relative_path)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    if not path.exists() or not path.is_file():
        return json.dumps({"error": f"Not a file: {rel_display}"})
    try:
        size = path.stat().st_size
    except OSError as e:
        return json.dumps({"error": f"Cannot stat file: {e}"})
    if size > MAX_READ_BYTES:
        return json.dumps(
            {"error": f"File too large ({size} bytes); max {MAX_READ_BYTES}"}
        )
    try:
        data = path.read_bytes()
    except OSError as e:
        return json.dumps({"error": f"Cannot read file: {e}"})
    text = data.decode("utf-8", errors="replace")
    return json.dumps({"path": rel_display, "content": text})


def workspace_write(workspace_root: Path, relative_path: str, content: str) -> str:
    """Write text to a file under the workspace (creates parent directories)."""
    raw = (relative_path or "").strip()
    if not raw or raw == ".":
        return json.dumps(
            {"error": "Path must be a file (not '.' or empty). Example: kanban-agent-output/<id>/RUN.md"}
        )
    try:
        encoded = content.encode("utf-8")
    except Exception as e:
        return json.dumps({"error": f"Invalid text content: {e}"})
    if len(encoded) > MAX_WRITE_BYTES:
        return json.dumps(
            {"error": f"Content too large ({len(encoded)} bytes); max {MAX_WRITE_BYTES}"}
        )
    try:
        rel_display = _user_path_to_relative(workspace_root, relative_path)
        path = _resolve_under_root(workspace_root, relative_path)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    if path.exists() and path.is_dir():
        return json.dumps({"error": f"Path is a directory: {rel_display}"})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
    except OSError as e:
        return json.dumps({"error": f"Cannot write file: {e}"})
    return json.dumps({"ok": True, "path": rel_display, "bytes_written": len(encoded)})

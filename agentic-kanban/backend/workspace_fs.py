"""Sandboxed filesystem helpers for agent workspace (paths must stay under root)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_READ_BYTES = 512 * 1024
MAX_WRITE_BYTES = 2 * 1024 * 1024


def _resolve_under_root(workspace_root: Path, relative_path: str) -> Path:
    root = workspace_root.resolve()
    rel = (relative_path or ".").strip() or "."
    if rel.startswith("/"):
        raise ValueError("relative_path must be relative to the workspace root")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise ValueError("Path escapes workspace root") from e
    return candidate


def workspace_list(workspace_root: Path, relative_path: str = ".") -> str:
    """Return a JSON string listing names and whether each entry is a directory."""
    target = _resolve_under_root(workspace_root, relative_path)
    if not target.exists():
        return json.dumps({"error": f"Not found: {relative_path}"})
    if not target.is_dir():
        return json.dumps({"error": f"Not a directory: {relative_path}"})
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        try:
            entries.append(
                {"name": child.name, "is_dir": child.is_dir(), "path": str(child.relative_to(workspace_root.resolve()))}
            )
        except OSError as e:
            logger.warning("Skipping unreadable entry %s: %s", child, e)
    return json.dumps({"entries": entries})


def workspace_read(workspace_root: Path, relative_path: str) -> str:
    """Read a text file under the workspace (UTF-8, with replacement for invalid bytes)."""
    path = _resolve_under_root(workspace_root, relative_path)
    if not path.exists() or not path.is_file():
        return json.dumps({"error": f"Not a file: {relative_path}"})
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        return json.dumps(
            {"error": f"File too large ({size} bytes); max {MAX_READ_BYTES}"}
        )
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    return json.dumps({"path": relative_path, "content": text})


def workspace_write(workspace_root: Path, relative_path: str, content: str) -> str:
    """Write text to a file under the workspace (creates parent directories)."""
    rel = (relative_path or "").strip()
    if not rel or rel == ".":
        return json.dumps({"error": "relative_path must be a file path, not the workspace root"})
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        return json.dumps(
            {"error": f"Content too large ({len(encoded)} bytes); max {MAX_WRITE_BYTES}"}
        )
    path = _resolve_under_root(workspace_root, relative_path)
    if path.exists() and path.is_dir():
        return json.dumps({"error": f"Path is a directory: {relative_path}"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return json.dumps({"ok": True, "path": relative_path, "bytes_written": len(encoded)})

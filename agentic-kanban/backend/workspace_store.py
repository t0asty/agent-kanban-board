"""Process-local workspace root for agent file tools (set from the UI via API)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_workspace_path: Optional[str] = None


def set_workspace(path: str) -> str:
    """Resolve and store workspace root. Raises ValueError if invalid."""
    global _workspace_path
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"Path does not exist: {p}")
    if not p.is_dir():
        raise ValueError(f"Not a directory: {p}")
    resolved = str(p)
    with _lock:
        _workspace_path = resolved
    return resolved


def clear_workspace() -> None:
    global _workspace_path
    with _lock:
        _workspace_path = None


def get_workspace_path() -> Optional[str]:
    with _lock:
        return _workspace_path

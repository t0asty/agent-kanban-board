"""
Neutral workspace artifacts for each card-agent run (session notes + machine-readable summary).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from workspace_fs import workspace_write

logger = logging.getLogger(__name__)

OUTPUT_PREFIX = "kanban-agent-output"


def write_agent_run_artifacts(
    workspace_root: Path,
    card_id: str,
    run_id: str,
    *,
    outcome: str,
    summary_excerpt: str,
    extra_sections: str = "",
) -> List[str]:
    """
    Write session notes (markdown) and a small JSON summary under kanban-agent-output/<card_id>/.
    Returns relative paths successfully written.
    """
    root = workspace_root.resolve()
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    base = f"{OUTPUT_PREFIX}/{card_id}"

    excerpt = (summary_excerpt or "").strip()
    if len(excerpt) > 6000:
        excerpt = excerpt[:3000] + "\n\n…\n\n" + excerpt[-2500:]

    md_path = f"{base}/session-notes.md"
    md_body = f"""# Working session notes

**Card:** `{card_id}`  
**Run:** `{run_id}`  
**Recorded (UTC):** {ts}  
**Outcome:** {outcome}

## Executive summary

{excerpt if excerpt else "No textual summary was returned for this run; see the kanban card for the latest description and status."}

## Context

This file is written automatically at the end of a card-agent run so there is a durable record next to the repository. It complements updates on the board (status, description, and tags) and does not replace human review of any code or documents the model may have touched.

## Workspace artifacts

If the agent used file tools during this run, additional paths may appear in the model summary on the card. The paths listed below are always created for this session:

- This note: `{md_path}`
- Companion metadata: `{base}/run-summary.json`

{extra_sections.strip()}

## Suggested follow-up

- Skim the card on the board for the appended **Agent update** section in the description.
- Open any files the agent claims to have modified under this workspace and run your usual tests or review.
- If something looks wrong, move the card back to *Planned* or *Blocked* and narrow the task scope before the next run.
"""

    json_path = f"{base}/run-summary.json"
    json_body = json.dumps(
        {
            "card_id": card_id,
            "run_id": run_id,
            "finished_at_utc": ts,
            "outcome": outcome,
            "summary_excerpt_chars": len(excerpt),
        },
        indent=2,
        ensure_ascii=False,
    )

    written: List[str] = []
    for rel, body in ((md_path, md_body), (json_path, json_body)):
        try:
            raw = workspace_write(root, rel, body)
            meta = json.loads(raw)
            if meta.get("ok") and meta.get("path"):
                written.append(str(meta["path"]))
        except Exception as e:
            logger.warning("Could not write agent artifact %s: %s", rel, e)
    return written

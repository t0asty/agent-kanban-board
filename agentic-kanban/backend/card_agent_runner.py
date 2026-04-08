"""
Per-card agent runs: Gemini with get_card / update_card tools (+ optional workspace FS tools).
Registry and concurrency limits are in-process (single API instance).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from agent_interaction_log import (
    json_preview,
    log_card_agent_end,
    log_card_agent_llm_prompt_full,
    log_card_agent_llm_request,
    log_card_agent_llm_response,
    log_card_agent_start,
    log_card_agent_tool,
)
from agent_run_artifacts import write_agent_run_artifacts
from workspace_fs import workspace_list, workspace_read, workspace_write

logger = logging.getLogger(__name__)


def _format_session_description_append(
    *,
    run_id: str,
    recorded_at: datetime,
    outcome_line: str,
    model_excerpt: str,
    artifact_paths: List[str],
) -> str:
    paths_block = ""
    if artifact_paths:
        paths_block = (
            "\n**Recorded under the workspace:**\n\n"
            + "\n".join(f"- `{p}`" for p in artifact_paths)
            + "\n"
        )
    excerpt = (model_excerpt or "").strip()
    if len(excerpt) > 5000:
        excerpt = excerpt[:2400] + "\n\n…\n\n" + excerpt[-2400:]
    body = excerpt if excerpt else "_No model text was captured for this run._"
    return (
        f"\n\n---\n\n"
        f"### Agent update · {recorded_at.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
        f"**Run id:** `{run_id}`\n\n"
        f"**Outcome:** {outcome_line}\n\n"
        f"#### Transcript excerpt\n\n{body}\n"
        f"{paths_block}"
        f"---\n"
    )


def _merge_agent_tags(existing: Any, *, success: bool) -> List[str]:
    tags = [str(t).lower() for t in (existing or []) if t is not None]
    for t in ("board-agent",):
        if t not in tags:
            tags.append(t)
    if success:
        if "agent-completed" not in tags:
            tags.append("agent-completed")
    else:
        if "agent-needs-review" not in tags:
            tags.append("agent-needs-review")
    return tags[:40]


def _verbose_last_agent_summary(
    *,
    run_id: str,
    outcome_line: str,
    tool_calls: int,
    artifact_paths: List[str],
    excerpt: str,
) -> str:
    parts = [
        f"Session `{run_id}` finished — {outcome_line}. "
        f"The model invoked backend tools {tool_calls} time(s). ",
    ]
    if artifact_paths:
        parts.append(
            "Session notes and metadata were written next to the project: "
            + ", ".join(f"`{p}`" for p in artifact_paths)
            + ". "
        )
    parts.append(
        "The description on this card now includes a dated block with a longer excerpt of what the model produced, "
        "so you can skim the board without opening the repo first. "
        "Treat any claimed file edits as unverified until you inspect them."
    )
    ex = (excerpt or "").strip()
    if ex:
        cap = 2000
        tail = "…" if len(ex) > cap else ""
        parts.append(f" Lead-in from the model: {ex[:cap]}{tail}")
    return "".join(parts)[:7500]


def _persist_failed_run_card(
    db: Any,
    card_id: str,
    CardUpdate: Any,
    run_id: str,
    err_text: str,
    workspace_root: Optional[Path],
    *,
    timed_out: bool,
) -> None:
    now = datetime.utcnow()
    outcome_key = "timed_out" if timed_out else "error"
    paths: List[str] = []
    if workspace_root is not None:
        paths = write_agent_run_artifacts(
            workspace_root,
            card_id,
            run_id,
            outcome=outcome_key,
            summary_excerpt=err_text[:8000],
            extra_sections="",
        )
    card = db.get_card_by_id(card_id)
    existing = (getattr(card, "description", None) or "").rstrip() if card else ""
    outcome_line = (
        "The run **timed out** before the agent could finish; card set to **Blocked**."
        if timed_out
        else "The run **failed with an error**; card set to **Blocked**."
    )
    append = _format_session_description_append(
        run_id=run_id,
        recorded_at=now,
        outcome_line=outcome_line,
        model_excerpt=err_text,
        artifact_paths=paths,
    )
    new_desc = (existing + append).strip()
    if len(new_desc) > 16000:
        new_desc = "...[earlier description trimmed for size]\n\n" + new_desc[-15500:]
    tags = (
        _merge_agent_tags(getattr(card, "tags", None), success=False)
        if card
        else ["board-agent", "agent-needs-review"]
    )
    summary = _verbose_last_agent_summary(
        run_id=run_id,
        outcome_line="stopped early — see the appended session on the card",
        tool_calls=0,
        artifact_paths=paths,
        excerpt=err_text,
    )
    db.update_card(
        card_id,
        CardUpdate(
            agentStatus="error",
            status="blocked",
            completedAt=None,
            lastAgentRunAt=now,
            lastAgentSummary=summary,
            description=new_desc,
            tags=tags,
        ),
    )


def _function_calling_mode_any():
    """Gemini tool_config mode that requires at least function-call predictions (not text-only)."""
    enum_cls = getattr(types, "FunctionCallingConfigMode", None)
    if enum_cls is not None and hasattr(enum_cls, "ANY"):
        return enum_cls.ANY
    return "ANY"


def _card_agent_tool_config():
    """
    Prefer forcing tool use: flash-lite often replies with plain text and skips tools (tool_round_trips=0).
    Set AGENT_TOOL_MODE=AUTO to restore default model behavior if ANY causes issues.
    """
    mode = (os.environ.get("AGENT_TOOL_MODE") or "ANY").strip().upper()
    if mode == "AUTO":
        enum_cls = getattr(types, "FunctionCallingConfigMode", None)
        auto = getattr(enum_cls, "AUTO", "AUTO") if enum_cls else "AUTO"
        return types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode=auto),
        )
    if mode == "NONE":
        return None
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=_function_calling_mode_any(),
        )
    )


VALID_CARD_STATUS = frozenset(
    {"research", "in-progress", "done", "blocked", "planned"}
)
VALID_AGENT_STATUS = frozenset({"idle", "running", "error"})

# At most this many card-agent runs at once globally
MAX_CONCURRENT_CARD_AGENTS = 3

_global_agent_slots = asyncio.Semaphore(MAX_CONCURRENT_CARD_AGENTS)


def _card_to_snapshot_dict(card: Any) -> Dict[str, Any]:
    d = card.dict()
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


@dataclass
class CardAgentRunState:
    run_id: str
    card_id: str
    status: str  # running | completed | failed | idle (unused for running path)
    step_count: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    summary: Optional[str] = None


class CardAgentRegistry:
    """Latest run state per card (in-memory)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_card: Dict[str, CardAgentRunState] = {}
        self._running_cards: set[str] = set()

    async def start_run(self, card_id: str) -> Optional[CardAgentRunState]:
        async with self._lock:
            if card_id in self._running_cards:
                return None
            self._running_cards.add(card_id)
            run_id = str(uuid.uuid4())
            st = CardAgentRunState(
                run_id=run_id,
                card_id=card_id,
                status="running",
                started_at=datetime.utcnow(),
            )
            self._by_card[card_id] = st
            return st

    async def finish_run(
        self,
        card_id: str,
        status: str,
        error: Optional[str] = None,
        summary: Optional[str] = None,
        step_count: Optional[int] = None,
    ) -> None:
        async with self._lock:
            self._running_cards.discard(card_id)
            st = self._by_card.get(card_id)
            if st:
                st.status = status
                st.finished_at = datetime.utcnow()
                st.error = error
                st.summary = summary
                if step_count is not None:
                    st.step_count = step_count

    async def get_state(self, card_id: str) -> Optional[CardAgentRunState]:
        async with self._lock:
            return self._by_card.get(card_id)

    def is_running(self, card_id: str) -> bool:
        return card_id in self._running_cards


card_agent_registry = CardAgentRegistry()


def _run_card_agent_sync(
    *,
    card_id: str,
    run_id: str,
    goal: Optional[str],
    max_steps: int,
    api_key: str,
    model_name: str,
    db: Any,
    CardUpdate: Any,
    workspace_root: Optional[Path],
    workspace_path_for_log: Optional[str],
) -> Tuple[str, int]:
    """Blocking Gemini + tools; invoked via asyncio.to_thread. Returns (summary, tool_calls)."""
    log_card_agent_start(
        run_id=run_id,
        card_id=card_id,
        model=model_name,
        max_steps=max_steps,
        workspace_path=workspace_path_for_log,
        goal_preview=goal or "",
    )
    client = genai.Client(api_key=api_key)
    tool_calls = {"n": 0}

    def bump() -> None:
        tool_calls["n"] += 1

    def get_card() -> str:
        bump()
        t0 = time.perf_counter()
        card = db.get_card_by_id(card_id)
        if not card:
            out = json.dumps({"error": "card_not_found", "card_id": card_id})
        else:
            out = json.dumps(_card_to_snapshot_dict(card))
        log_card_agent_tool(
            run_id=run_id,
            card_id=card_id,
            tool="get_card",
            arguments_summary="{}",
            result=out,
            duration_ms=(time.perf_counter() - t0) * 1000,
        )
        return out

    def update_kanban_card(
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        tags_json: Any = None,
        order: Any = None,
        completed_at: Optional[str] = None,
        last_agent_summary: Any = None,
        agent_status: Optional[str] = None,
    ) -> str:
        bump()
        t0 = time.perf_counter()
        arg_d = {
            k: v
            for k, v in [
                ("title", title),
                ("description", description),
                ("status", status),
                ("tags_json", tags_json),
                ("order", order),
                ("completed_at", completed_at),
                ("last_agent_summary", last_agent_summary),
                ("agent_status", agent_status),
            ]
            if v is not None
        }

        def _finish(result: str) -> str:
            log_card_agent_tool(
                run_id=run_id,
                card_id=card_id,
                tool="update_kanban_card",
                arguments_summary=json_preview(arg_d, 3000),
                result=result,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return result

        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = str(title)
        if description is not None:
            payload["description"] = str(description)
        if status is not None:
            status = str(status).strip()
            if status not in VALID_CARD_STATUS:
                return _finish(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "invalid_status",
                            "allowed": list(VALID_CARD_STATUS),
                        }
                    )
                )
            payload["status"] = status
        if tags_json is not None:
            try:
                if isinstance(tags_json, (list, tuple)):
                    tags = list(tags_json)
                else:
                    raw = tags_json if isinstance(tags_json, str) else str(tags_json)
                    tags = json.loads(raw)
                if not isinstance(tags, list):
                    raise ValueError("tags must be a JSON array")
                payload["tags"] = [str(t) for t in tags]
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                return _finish(
                    json.dumps({"ok": False, "error": "invalid_tags_json", "detail": str(e)})
                )
        if order is not None:
            try:
                payload["order"] = int(order)
            except (TypeError, ValueError) as e:
                return _finish(
                    json.dumps({"ok": False, "error": "invalid_order", "detail": str(e)})
                )
        if completed_at is not None:
            payload["completedAt"] = str(completed_at)
        if last_agent_summary is not None:
            payload["lastAgentSummary"] = str(last_agent_summary)[:8000]
        if agent_status is not None:
            agent_status = str(agent_status).strip()
            if agent_status not in VALID_AGENT_STATUS:
                return _finish(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "invalid_agent_status",
                            "allowed": list(VALID_AGENT_STATUS),
                        }
                    )
                )
            payload["agentStatus"] = agent_status

        if payload.get("status") == "done" and "completedAt" not in payload:
            payload["completedAt"] = datetime.utcnow().isoformat()

        if not payload:
            return _finish(json.dumps({"ok": False, "error": "no_fields_to_update"}))

        try:
            updates = CardUpdate(**payload)
        except Exception as e:
            logger.warning("CardUpdate validation failed: %s payload_keys=%s", e, list(payload))
            return _finish(
                json.dumps(
                    {"ok": False, "error": "validation_failed", "detail": str(e)[:800]}
                )
            )
        try:
            updated = db.update_card(card_id, updates)
        except Exception as e:
            logger.exception("db.update_card failed for %s", card_id)
            return _finish(
                json.dumps({"ok": False, "error": "database_error", "detail": str(e)[:800]})
            )
        if not updated:
            return _finish(
                json.dumps(
                    {
                        "ok": False,
                        "error": "update_failed",
                        "detail": "Card not found in DB or update produced no fields (check card_id).",
                    }
                )
            )
        return _finish(json.dumps({"ok": True, "card": _card_to_snapshot_dict(updated)}))

    tools: List[Any] = [get_card, update_kanban_card]

    files_written: List[str] = []

    effective_root: Optional[Path] = None
    if workspace_root is not None:
        try:
            r = workspace_root.expanduser().resolve()
            if r.is_dir():
                effective_root = r
            else:
                logger.warning(
                    "Card agent: workspace path is not a directory (file tools disabled): %s",
                    r,
                )
        except OSError as e:
            logger.warning("Card agent: workspace path unusable: %s", e)

    if effective_root is not None:
        root = effective_root.resolve()

        def list_workspace_directory(relative_path: str = ".") -> str:
            bump()
            t0 = time.perf_counter()
            try:
                out = workspace_list(root, relative_path)
            except Exception as e:
                logger.exception("list_workspace_directory")
                out = json.dumps({"error": str(e)})
            log_card_agent_tool(
                run_id=run_id,
                card_id=card_id,
                tool="list_workspace_directory",
                arguments_summary=json_preview({"relative_path": relative_path}),
                result=out,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return out

        def read_workspace_file(relative_path: str) -> str:
            bump()
            t0 = time.perf_counter()
            try:
                out = workspace_read(root, relative_path)
            except Exception as e:
                logger.exception("read_workspace_file")
                out = json.dumps({"error": str(e)})
            log_card_agent_tool(
                run_id=run_id,
                card_id=card_id,
                tool="read_workspace_file",
                arguments_summary=json_preview({"relative_path": relative_path}),
                result=out,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return out

        def write_workspace_file(relative_path: str, content: str) -> str:
            bump()
            t0 = time.perf_counter()
            try:
                out = workspace_write(root, relative_path, content)
                try:
                    meta = json.loads(out)
                    if meta.get("ok") and meta.get("path"):
                        files_written.append(str(meta["path"]))
                except (json.JSONDecodeError, TypeError):
                    pass
            except Exception as e:
                logger.exception("write_workspace_file")
                out = json.dumps({"error": str(e)})
            log_card_agent_tool(
                run_id=run_id,
                card_id=card_id,
                tool="write_workspace_file",
                arguments_summary=json_preview(
                    {"relative_path": relative_path, "content_chars": len(content or "")}
                ),
                result=out,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
            return out

        tools.extend(
            [list_workspace_directory, read_workspace_file, write_workspace_file]
        )

    card = db.get_card_by_id(card_id)
    if not card:
        raise ValueError(f"card_not_found:{card_id}")

    snapshot = _card_to_snapshot_dict(card)
    goal_text = (goal or "").strip() or "Advance this task: do the work implied by the title and description, then update the card and move it to the appropriate column (status)."

    workspace_note = ""
    if effective_root is not None:
        root_display = str(effective_root.resolve())
        out_dir = f"kanban-agent-output/{card_id}"
        workspace_note = f"""
FILESYSTEM WORKSPACE (tools are sandboxed to this directory only):
{root_display}

Paths: You may use EITHER relative paths (recommended), e.g. "{out_dir}/RUN.md", OR a full absolute path as long as it is inside the directory above (the tools will normalize it).

The user expects visible work on disk whenever the task is not purely “edit the card text only”.
Workflow:
1. Call list_workspace_directory(".") first to inspect the repository layout. If you see {{"error":...}}, read the error and fix the path — do not claim the workspace is broken without retrying with "." .
2. Use read_workspace_file on paths you need to understand or change.
3. Persist deliverables with write_workspace_file. Always create a human-visible log for this run at:
   {out_dir}/RUN.md
   (Markdown: what you did, files touched, and any commands or follow-ups). Create parent folders as needed.
4. If the card implies code, config, or docs, write or patch real files under sensible paths inside the workspace (not only RUN.md).
5. Before finishing, call update_kanban_card with last_agent_summary listing every relative path you created or updated (including RUN.md). If update_kanban_card returns ok:false, read the "detail" field and retry with valid fields — do not give up without fixing the payload.

Pure meta tasks (only moving the card / rewriting title) may skip new files, but say so in last_agent_summary.
"""
    elif workspace_root is not None:
        workspace_note = f"""
A workspace path was configured ({workspace_root}) but it is NOT usable on this server right now (missing, not a directory, or permission error). You do NOT have file tools.
Use get_card and update_kanban_card only. Explain in last_agent_summary that the server workspace path must exist and be readable by the backend process.
"""
    else:
        workspace_note = """
NO FILESYSTEM WORKSPACE is configured on the server — you do NOT have list/read/write file tools.
You can only use get_card and update_kanban_card. If the user expected files in a project folder, state clearly in last_agent_summary that the workspace path must be set on the app Home page.
"""

    system_prompt = f"""You are a single-task agent bound to one kanban card. Your card id is: {card_id}

You MUST use the provided tools. A plain-text-only answer is invalid and does nothing — the board only changes via tool calls.
Your FIRST action must be a tool call: call get_card() immediately (do not write an apology or explanation first).

Rules:
- Call get_card when you need the latest card (e.g. after edits or to refresh).
- Use update_kanban_card to change title, description, status (column), tags, order, completed_at, last_agent_summary, or agent_status.
- Valid status values: {", ".join(sorted(VALID_CARD_STATUS))}.
- Valid agent_status values: {", ".join(sorted(VALID_AGENT_STATUS))}. Set agent_status to running when you start substantive work and to idle when you are done. Use error if you cannot complete the task.
- When moving to done, set status to done (completed_at will be set automatically if omitted).
- Prefer concise last_agent_summary when you finish describing what you did.

Current card snapshot (may be stale; use get_card to refresh):
{json.dumps(snapshot, indent=2)}
{workspace_note}
User goal for this run:
{goal_text}
"""

    _tool_cfg = _card_agent_tool_config()
    config_kw: Dict[str, Any] = dict(
        temperature=0.5,
        max_output_tokens=8192,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=max(1, max_steps),
        ),
    )
    if _tool_cfg is not None:
        config_kw["tool_config"] = _tool_cfg
    config = types.GenerateContentConfig(**config_kw)

    tool_names = [getattr(f, "__name__", repr(f)) for f in tools]
    log_card_agent_llm_request(
        run_id=run_id,
        card_id=card_id,
        model=model_name,
        prompt_chars=len(system_prompt),
        max_tool_rounds=max(1, max_steps),
        tool_names=tool_names,
    )
    log_card_agent_llm_prompt_full(run_id=run_id, prompt=system_prompt)

    response = client.models.generate_content(
        model=model_name,
        contents=system_prompt,
        config=config,
    )

    log_card_agent_llm_response(
        run_id=run_id, card_id=card_id, response_text=response.text
    )

    n_tools = int(tool_calls["n"])
    if n_tools == 0:
        logger.warning(
            "[card_agent] run_id=%s card_id=%s completed with ZERO tool calls — "
            "model returned text only. Using tool_config mode ANY by default; "
            "set AGENT_TOOL_MODE=AUTO if your model misbehaves with forced tools.",
            run_id,
            card_id,
        )

    raw_model_text = (response.text or "").strip()
    combined = raw_model_text
    if files_written:
        unique_fw: List[str] = []
        for p in files_written:
            if p not in unique_fw:
                unique_fw.append(p)
        prefix = "Paths touched by tools in this run:\n" + "\n".join(
            f"- {p}" for p in unique_fw[:40]
        )
        if len(unique_fw) > 40:
            prefix += f"\n- … and {len(unique_fw) - 40} more"
        combined = f"{prefix}\n\n{raw_model_text}".strip()
    if not combined:
        combined = "Run finished without additional model text."

    extra_sections = ""
    if files_written:
        ufw: List[str] = []
        for p in files_written:
            if p not in ufw:
                ufw.append(p)
        extra_sections = "## Paths touched during the run\n\n" + "\n".join(
            f"- `{p}`" for p in ufw[:50]
        )

    artifact_paths: List[str] = []
    if effective_root is not None:
        artifact_paths = write_agent_run_artifacts(
            effective_root,
            card_id,
            run_id,
            outcome="completed",
            summary_excerpt=combined[:8000],
            extra_sections=extra_sections,
        )

    now = datetime.utcnow()
    card_now = db.get_card_by_id(card_id)
    existing_desc = (
        (getattr(card_now, "description", None) or "").rstrip() if card_now else ""
    )
    append = _format_session_description_append(
        run_id=run_id,
        recorded_at=now,
        outcome_line="Completed successfully; card moved to **Done**.",
        model_excerpt=combined,
        artifact_paths=artifact_paths,
    )
    new_desc = (existing_desc + append).strip()
    if len(new_desc) > 16000:
        new_desc = "...[earlier description trimmed for size]\n\n" + new_desc[-15500:]

    tags = (
        _merge_agent_tags(getattr(card_now, "tags", None), success=True)
        if card_now
        else ["board-agent", "agent-completed"]
    )

    verbose_summary = _verbose_last_agent_summary(
        run_id=run_id,
        outcome_line="completed and the card was moved to Done",
        tool_calls=int(tool_calls["n"]),
        artifact_paths=artifact_paths,
        excerpt=combined,
    )

    unique_files: List[str] = []
    for p in files_written:
        if p not in unique_files:
            unique_files.append(p)
    for p in artifact_paths:
        if p not in unique_files:
            unique_files.append(p)
    log_card_agent_end(
        run_id=run_id,
        card_id=card_id,
        tool_round_trips=int(tool_calls["n"]),
        summary_preview=verbose_summary[:1200],
        files_written=unique_files,
    )

    db.update_card(
        card_id,
        CardUpdate(
            agentStatus="idle",
            lastAgentRunAt=now,
            lastAgentSummary=verbose_summary,
            status="done",
            completedAt=now,
            description=new_desc,
            tags=tags,
        ),
    )
    return verbose_summary, int(tool_calls["n"])


async def execute_card_agent_run(
    *,
    card_id: str,
    run_id: str,
    goal: Optional[str],
    max_steps: int,
    max_wall_seconds: float,
    db: Any,
    CardUpdate: Any,
    gemini_api_key: str,
    model_name: str,
    workspace_path: Optional[str],
) -> None:
    """Runs the agent with global and per-card concurrency; updates registry on exit."""
    workspace_root: Optional[Path] = None
    if workspace_path:
        try:
            wp = Path(workspace_path).expanduser().resolve()
            if wp.is_dir():
                workspace_root = wp
        except OSError:
            pass

    async with _global_agent_slots:
        try:
            summary_text, steps = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_card_agent_sync,
                    card_id=card_id,
                    run_id=run_id,
                    goal=goal,
                    max_steps=max_steps,
                    api_key=gemini_api_key,
                    model_name=model_name,
                    db=db,
                    CardUpdate=CardUpdate,
                    workspace_root=workspace_root,
                    workspace_path_for_log=workspace_path,
                ),
                timeout=max_wall_seconds,
            )
            await card_agent_registry.finish_run(
                card_id,
                "completed",
                summary=summary_text,
                step_count=steps,
            )
        except asyncio.TimeoutError:
            err = f"Agent run exceeded max_wall_seconds={max_wall_seconds}"
            logger.warning("%s card_id=%s", err, card_id)
            try:
                _persist_failed_run_card(
                    db,
                    card_id,
                    CardUpdate,
                    run_id,
                    err,
                    workspace_root,
                    timed_out=True,
                )
            except Exception:
                logger.exception("Failed to persist timeout state for card %s", card_id)
            await card_agent_registry.finish_run(
                card_id, "failed", error=err, summary=err
            )
        except Exception as e:
            err = str(e)
            logger.exception("Card agent run failed card_id=%s", card_id)
            try:
                _persist_failed_run_card(
                    db,
                    card_id,
                    CardUpdate,
                    run_id,
                    err,
                    workspace_root,
                    timed_out=False,
                )
            except Exception:
                logger.exception("Failed to persist error state for card %s", card_id)
            await card_agent_registry.finish_run(
                card_id, "failed", error=err, summary=err[:2000]
            )


async def schedule_card_agent_run(
    *,
    card_id: str,
    goal: Optional[str],
    max_steps: int,
    max_wall_seconds: float,
    db: Any,
    CardUpdate: Any,
    gemini_api_key: str,
    model_name: str,
    workspace_path: Optional[str],
) -> Optional[str]:
    """
    Marks card running, registers run, and spawns background task.
    Returns run_id or None if a run is already active for this card.
    """
    st = await card_agent_registry.start_run(card_id)
    if not st:
        return None
    run_id = st.run_id
    try:
        db.update_card(
            card_id,
            CardUpdate(
                agentStatus="running",
                status="in-progress",
                completedAt=None,
                lastAgentSummary=(
                    "An agent run is in progress for this card. Status is now **In progress**; "
                    "completed work will be summarized on the card and under the workspace when the run finishes."
                ),
            ),
        )
    except Exception:
        await card_agent_registry.finish_run(
            card_id, "failed", error="Failed to set running state on card"
        )
        raise

    async def _wrapper() -> None:
        await execute_card_agent_run(
            card_id=card_id,
            run_id=run_id,
            goal=goal,
            max_steps=max_steps,
            max_wall_seconds=max_wall_seconds,
            db=db,
            CardUpdate=CardUpdate,
            gemini_api_key=gemini_api_key,
            model_name=model_name,
            workspace_path=workspace_path,
        )

    asyncio.create_task(_wrapper())
    return run_id

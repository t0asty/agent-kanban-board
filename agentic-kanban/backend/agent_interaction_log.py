"""
Structured logs for Gemini agent runs (card agent + generate-cards).

- Every tool call is logged at INFO on logger ``agentic.agent_interactions``.
- Set ``AGENT_DEBUG=1`` to allow DEBUG-level extras (if the root log level allows it).
- Set ``AGENT_DEBUG_FULL=1`` to log full prompts / large bodies at DEBUG (very verbose).

Filter in your log viewer: name:agentic.agent_interactions
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, List, Optional, Sequence

interaction_logger = logging.getLogger("agentic.agent_interactions")


def agent_debug_full() -> bool:
    return os.environ.get("AGENT_DEBUG_FULL", "").strip().lower() in ("1", "true", "yes", "on")


def truncate(text: Any, max_len: int = 4000) -> str:
    if text is None:
        return ""
    s = text if isinstance(text, str) else repr(text)
    if len(s) <= max_len:
        return s
    half = max(200, max_len // 2)
    return (
        s[:half]
        + f"\n...[truncated total_len={len(s)} max_len={max_len}]...\n"
        + s[-half:]
    )


def log_card_agent_start(
    *,
    run_id: str,
    card_id: str,
    model: str,
    max_steps: int,
    workspace_path: Optional[str],
    goal_preview: str,
) -> None:
    interaction_logger.info(
        "[card_agent] START run_id=%s card_id=%s model=%s max_steps=%d workspace=%s goal_preview=%s",
        run_id,
        card_id,
        model,
        max_steps,
        workspace_path or "(none)",
        truncate(goal_preview, 500),
    )


def log_card_agent_llm_request(
    *,
    run_id: str,
    card_id: str,
    model: str,
    prompt_chars: int,
    max_tool_rounds: int,
    tool_names: Sequence[str],
) -> None:
    interaction_logger.info(
        "[card_agent] LLM_REQUEST run_id=%s card_id=%s model=%s prompt_chars=%d max_tool_rounds=%d tools=[%s]",
        run_id,
        card_id,
        model,
        prompt_chars,
        max_tool_rounds,
        ", ".join(tool_names),
    )


def log_card_agent_llm_prompt_full(*, run_id: str, prompt: str) -> None:
    if agent_debug_full():
        interaction_logger.debug(
            "[card_agent] LLM_PROMPT_FULL run_id=%s\n%s",
            run_id,
            truncate(prompt, 100_000),
        )


def log_card_agent_llm_response(
    *,
    run_id: str,
    card_id: str,
    response_text: Optional[str],
) -> None:
    text = response_text or ""
    interaction_logger.info(
        "[card_agent] LLM_RESPONSE run_id=%s card_id=%s response_chars=%d preview=%s",
        run_id,
        card_id,
        len(text),
        truncate(text, 1200),
    )
    if agent_debug_full() and text:
        interaction_logger.debug(
            "[card_agent] LLM_RESPONSE_FULL run_id=%s\n%s", run_id, truncate(text, 100_000)
        )


def log_card_agent_tool(
    *,
    run_id: str,
    card_id: str,
    tool: str,
    arguments_summary: str,
    result: str,
    duration_ms: float,
) -> None:
    interaction_logger.info(
        "[card_agent] TOOL run_id=%s card_id=%s tool=%s duration_ms=%.1f args=%s result=%s",
        run_id,
        card_id,
        tool,
        duration_ms,
        truncate(arguments_summary, 2500),
        truncate(result, 6000),
    )


def log_card_agent_end(
    *,
    run_id: str,
    card_id: str,
    tool_round_trips: int,
    summary_preview: str,
    files_written: Optional[List[str]] = None,
) -> None:
    fw = ", ".join(files_written[:20]) if files_written else ""
    if files_written and len(files_written) > 20:
        fw += f" …(+{len(files_written) - 20} more)"
    interaction_logger.info(
        "[card_agent] END run_id=%s card_id=%s tool_round_trips=%d files_written=%s summary_preview=%s",
        run_id,
        card_id,
        tool_round_trips,
        fw or "(none)",
        truncate(summary_preview, 800),
    )


def log_generate_cards_start(
    *,
    run_id: str,
    model: str,
    prompt_chars: int,
    workspace: Optional[str],
    max_tool_rounds: Optional[int],
) -> None:
    interaction_logger.info(
        "[generate_cards] START run_id=%s model=%s prompt_chars=%d workspace=%s max_tool_rounds=%s",
        run_id,
        model,
        prompt_chars,
        workspace or "(none)",
        max_tool_rounds if max_tool_rounds is not None else "(n/a)",
    )


def log_generate_cards_llm_request(
    *,
    run_id: str,
    model: str,
    prompt_chars: int,
    tool_names: Sequence[str],
) -> None:
    interaction_logger.info(
        "[generate_cards] LLM_REQUEST run_id=%s model=%s prompt_chars=%d tools=[%s]",
        run_id,
        model,
        prompt_chars,
        ", ".join(tool_names) if tool_names else "(none)",
    )


def log_generate_cards_prompt_full(*, run_id: str, prompt: str) -> None:
    if agent_debug_full():
        interaction_logger.debug(
            "[generate_cards] LLM_PROMPT_FULL run_id=%s\n%s",
            run_id,
            truncate(prompt, 100_000),
        )


def log_generate_cards_tool(
    *,
    run_id: str,
    tool: str,
    arguments_summary: str,
    result: str,
    duration_ms: float,
) -> None:
    interaction_logger.info(
        "[generate_cards] TOOL run_id=%s tool=%s duration_ms=%.1f args=%s result=%s",
        run_id,
        tool,
        duration_ms,
        truncate(arguments_summary, 2500),
        truncate(result, 6000),
    )


def log_generate_cards_response(*, run_id: str, response_text: Optional[str], num_cards: int) -> None:
    text = response_text or ""
    interaction_logger.info(
        "[generate_cards] LLM_RESPONSE run_id=%s response_chars=%d cards_parsed=%d preview=%s",
        run_id,
        len(text),
        num_cards,
        truncate(text, 1200),
    )
    if agent_debug_full() and text:
        interaction_logger.debug(
            "[generate_cards] LLM_RESPONSE_FULL run_id=%s\n%s", run_id, truncate(text, 100_000)
        )


def log_generate_cards_end(*, run_id: str, outcome: str, detail: str = "") -> None:
    interaction_logger.info(
        "[generate_cards] END run_id=%s outcome=%s %s",
        run_id,
        outcome,
        truncate(detail, 500),
    )


def json_preview(obj: Any, max_len: int = 2000) -> str:
    try:
        return truncate(json.dumps(obj, default=str, ensure_ascii=False), max_len)
    except Exception:
        return truncate(repr(obj), max_len)

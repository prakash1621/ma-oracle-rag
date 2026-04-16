"""Contradiction detection layer for the M&A Oracle RAG pipeline.

Compares management claims from earnings transcripts against
facts disclosed in 10-K filings to surface mismatches.

Public API:
    from src.contradiction.detector import detect_contradictions
    result = detect_contradictions("AAPL")
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ── Shared JSON parser ────────────────────────────────────────────────────────

# Matches <think>...</think> blocks emitted by reasoning models
# (qwen3, deepseek-r1, o1-mini, etc.) before the actual JSON answer.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def parse_llm_json(raw: str, caller: str = "") -> list | dict | None:
    """Robustly parse JSON from any LLM response.

    Handles the following output formats in order:
      1. Reasoning-model think blocks  — strips <think>...</think> prefix
      2. Markdown fences               — strips ```json ... ``` wrappers
      3. Plain JSON                    — passes straight through

    Args:
        raw:    The raw string returned by the LLM.
        caller: Optional label for log messages (e.g. "[claim_extractor]").

    Returns:
        Parsed Python object (list or dict), or None on failure.
    """
    if not raw:
        logger.warning("%s Empty LLM response — nothing to parse.", caller)
        return None

    # Step 1: strip <think> … </think> reasoning blocks
    cleaned = _THINK_RE.sub("", raw).strip()

    # Step 2: strip markdown code fences  ``` or ```json
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        # parts[1] is the content between the first pair of fences
        inner = parts[1] if len(parts) > 1 else ""
        if inner.startswith("json"):
            inner = inner[4:]
        cleaned = inner.strip()

    # Step 3: try to find the first JSON structure if there's preamble text
    # (some models write one sentence before the array)
    if cleaned and cleaned[0] not in ("[", "{"):
        # Look for the first '[' or '{'
        bracket_pos = min(
            (cleaned.find(c) for c in ("[", "{") if cleaned.find(c) != -1),
            default=-1,
        )
        if bracket_pos != -1:
            cleaned = cleaned[bracket_pos:]

    if not cleaned:
        logger.warning("%s No JSON content found after stripping think/fences.", caller)
        return None

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("%s JSON parse failed: %s | raw snippet: %.120s", caller, exc, raw)
        return None

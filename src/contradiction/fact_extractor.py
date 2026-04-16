"""Fact extractor — pull disclosed facts from 10-K filing chunks.

Reads output/edgar/chunked_documents.json and uses an LLM to extract
risk factors, financial disclosures, and material facts from 10-K filings
that can be compared against management's earnings call claims.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from src.contradiction import parse_llm_json

logger = logging.getLogger(__name__)

# CIK → ticker mapping (matches subdirectories in output/edgar/)
_CIK_TO_TICKER: dict[str, str] = {
    "0000320193": "AAPL",
    "0000789019": "MSFT",
    "0001045810": "NVDA",
    "0001018724": "AMZN",
    "0001326801": "META",
    "0001652044": "GOOGL",
    "0001318605": "TSLA",
    "0001108524": "CRM",
    "0001640147": "SNOW",
    "0001535527": "CRWD",
    "0001327567": "PANW",
    "0001262039": "FTNT",
}

# Ticker → CIK reverse lookup
_TICKER_TO_CIK: dict[str, str] = {v: k for k, v in _CIK_TO_TICKER.items()}

# ── 3-tier section priority for contradiction detection ──────────────────────
# Tier 1: Risk factors — qualitative contradictions (highest value)
_TIER1_SECTIONS = {"item 1a", "risk factor"}
# Tier 2: Financial statements — quantitative contradiction detection
_TIER2_SECTIONS = {"item 8", "financial statement", "balance sheet",
                   "income statement", "statement of operations", "cash flow"}
# Tier 3: MD&A / management narrative — good secondary source
_TIER3_SECTIONS = {"item 7", "item 7a", "results of operations", "liquidity",
                   "market risk", "quantitative", "qualitative", "management"}

# Max chunks to feed the LLM per call
_MAX_CHUNKS_PER_CALL = 6
# Max LLM calls total
_MAX_LLM_CALLS = 3


def _load_edgar_chunks(ticker: str) -> list[dict[str, Any]]:
    """Load 10-K chunks from output/edgar/chunked_documents.json for a ticker."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, "output", "edgar", "chunked_documents.json")

    if not os.path.exists(path):
        logger.warning("[fact_extractor] EDGAR file not found: %s", path)
        return []

    target_cik = _TICKER_TO_CIK.get(ticker.upper(), "")

    with open(path, encoding="utf-8") as f:
        all_chunks: list[dict] = json.load(f)

    matched: list[dict] = []
    for chunk in all_chunks:
        meta = chunk.get("metadata", {})
        # Match by CIK stored in metadata, falling back to ticker field
        chunk_cik = meta.get("cik", "")
        chunk_ticker = meta.get("ticker", "").upper()
        filing_type = meta.get("filing_type", "").upper()
        if filing_type != "10-K":
            continue
        if (target_cik and chunk_cik == target_cik) or chunk_ticker == ticker.upper():
            matched.append(chunk)

    logger.info("[fact_extractor] Found %d 10-K EDGAR chunks for %s", len(matched), ticker)
    return matched


def _prioritise_chunks(chunks: list[dict]) -> list[dict]:
    """Sort chunks into three priority tiers for contradiction detection.

    Tier 1 (highest): Item 1A Risk Factors    — qualitative contradictions.
    Tier 2:           Item 8 Financial Stmts  — quantitative contradictions.
    Tier 3:           Item 7 MD&A             — management narrative context.
    Tier 4 (rest):    All other sections.
    """
    tier1, tier2, tier3, tier4 = [], [], [], []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        text_lower    = chunk.get("text", "").lower()
        section       = meta.get("section", "").lower()
        item_number   = meta.get("item_number", "").lower()
        item_title    = meta.get("item_title", "").lower()
        combined_meta = f"{section} {item_number} {item_title}"
        if any(kw in text_lower or kw in combined_meta for kw in _TIER1_SECTIONS):
            tier1.append(chunk)
        elif any(kw in text_lower or kw in combined_meta for kw in _TIER2_SECTIONS):
            tier2.append(chunk)
        elif any(kw in text_lower or kw in combined_meta for kw in _TIER3_SECTIONS):
            tier3.append(chunk)
        else:
            tier4.append(chunk)
    return tier1 + tier2 + tier3 + tier4


def _build_llm_client():
    """Build an OpenAI-compatible LLM client from config.yaml / env."""
    from src.contradiction._llm import build_llm_client

    return build_llm_client()


def _sanitise(text: str) -> str:
    """Strip problematic non-ASCII characters from SEC filing text."""
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\ufffd", "?")
    return text


def _extract_facts_from_text(text: str, source_label: str, llm, model: str) -> list[dict]:
    """Ask the LLM to pull material facts from a 10-K text block."""
    system_prompt = (
        "You are a financial due-diligence analyst reviewing a 10-K annual filing. "
        "Extract specific, verifiable FACTS disclosed in the text below. "
        "Focus on: risk factors, financial performance data, customer concentration, "
        "revenue trends, competitive risks, litigation, regulatory issues, "
        "cost pressures, margin disclosures, or any material negative developments.\n\n"
        "Return a JSON array of objects, each with:\n"
        '  "fact":      the specific disclosed fact (one sentence, direct quote or close paraphrase)\n'
        '  "section":   the 10-K section (e.g. "Item 1A Risk Factors", "Item 7 MD&A", '  
        '               "Item 8 Financial Statements")\n'
        '  "topic":     the business topic (e.g. "customer concentration", "revenue trend")\n'
        '  "metric":    the financial or operational metric (e.g. "revenue", "net income") — use "" if none\n'
        '  "direction": the direction as disclosed — "increase" | "decrease" | "stable" | ""\n'
        '  "value":     the numeric value or percentage disclosed (e.g. "8%", "$2.1B") — use "" if none\n\n'
        "Return ONLY the JSON array. If no material facts are found, return []."
    )
    user_content = f"Source: {source_label}\n\nText:\n{_sanitise(text[:2000])}"

    try:
        response = llm.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        result = parse_llm_json(raw, "[fact_extractor]")
        if not isinstance(result, list):
            return []
        for f in result:
            f["source"] = source_label
        return result
    except Exception as exc:
        logger.warning("[fact_extractor] LLM call failed: %s", exc)
        return []


def extract_facts(ticker: str, llm=None, model: str = "") -> list[dict]:
    """Extract material facts from 10-K filing chunks for a ticker.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL"
        llm:    Optional pre-built OpenAI client (created internally if None)
        model:  LLM model name (uses config default if empty)

    Returns:
        List of fact dicts:
            {
                "fact":    "Item 1A discloses significant customer concentration risk with one customer...",
                "section": "Item 1A Risk Factors",
                "topic":   "customer concentration",
                "source":  "Apple Inc. 10-K (2024)"
            }
    """
    if llm is None:
        llm, model = _build_llm_client()

    chunks = _load_edgar_chunks(ticker)
    if not chunks:
        logger.warning("[fact_extractor] No EDGAR chunks found for %s", ticker)
        return []

    # Prioritise high-signal sections
    chunks = _prioritise_chunks(chunks)

    # Group by filing date to avoid repeating the same document
    by_filing: dict[str, list[str]] = {}
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        filing_type = meta.get("filing_type", "10-K")
        filing_date = meta.get("filing_date", "")
        label = f"{filing_type} {filing_date}".strip() or "10-K"
        by_filing.setdefault(label, []).append(chunk.get("text", ""))

    all_facts: list[dict] = []
    calls_made = 0

    for filing_label, texts in list(by_filing.items())[:_MAX_LLM_CALLS]:
        if calls_made >= _MAX_LLM_CALLS:
            break
        combined = "\n\n".join(texts[:_MAX_CHUNKS_PER_CALL])
        facts = _extract_facts_from_text(combined, filing_label, llm, model)
        logger.info("[fact_extractor] Extracted %d facts from '%s'", len(facts), filing_label)
        all_facts.extend(facts)
        calls_made += 1
        time.sleep(1.5)  # throttle: stay within Groq token-per-minute limit

    logger.info("[fact_extractor] Total facts for %s: %d", ticker, len(all_facts))
    return all_facts

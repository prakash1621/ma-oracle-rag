"""Claim extractor — pull management claims from earnings transcript chunks.

Reads output/transcripts/chunked_documents.json and uses an LLM to
extract forward-looking or assertive claims management made about the
business (growth, pipeline, outlook, competitive position, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from src.contradiction import parse_llm_json

logger = logging.getLogger(__name__)

# Ticker → company name substrings (case-insensitive match against metadata)
_TICKER_TO_NAMES: dict[str, list[str]] = {
    "AAPL":  ["apple"],
    "MSFT":  ["microsoft"],
    "NVDA":  ["nvidia"],
    "AMZN":  ["amazon"],
    "META":  ["meta platforms", "meta"],
    "GOOGL": ["alphabet", "google"],
    "TSLA":  ["tesla"],
    "CRM":   ["salesforce"],
    "SNOW":  ["snowflake"],
    "CRWD":  ["crowdstrike"],
    "PANW":  ["palo alto"],
    "FTNT":  ["fortinet"],
}

# Max transcript chunks to send to the LLM per call (keep token budget sane)
_MAX_CHUNKS_PER_CALL = 6
# Max calls total (covers multiple earnings releases)
_MAX_LLM_CALLS = 3


def _load_transcript_chunks(ticker: str) -> list[dict[str, Any]]:
    """Load and filter chunks from output/transcripts/chunked_documents.json."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, "output", "transcripts", "chunked_documents.json")

    if not os.path.exists(path):
        logger.warning("Transcript file not found: %s", path)
        return []

    with open(path, encoding="utf-8") as f:
        all_chunks: list[dict] = json.load(f)

    # Match chunks for this ticker by company name
    name_hints = _TICKER_TO_NAMES.get(ticker.upper(), [ticker.lower()])
    matched: list[dict] = []
    for chunk in all_chunks:
        company = chunk.get("metadata", {}).get("company_name", "").lower()
        if any(hint in company for hint in name_hints):
            matched.append(chunk)

    logger.info("[claim_extractor] Found %d transcript chunks for %s", len(matched), ticker)
    return matched


def _build_llm_client():
    """Build an OpenAI-compatible LLM client from config.yaml / env."""
    from src.contradiction._llm import build_llm_client

    return build_llm_client()


def _sanitise(text: str) -> str:
    """Remove problematic characters from SEC filing text before sending to LLM.

    SEC filings often contain Windows-1252 curly quotes, long dashes, and other
    non-ASCII characters that survive PDF→text extraction as replacement glyphs
    (\ufffd, \u2019, \u2013 etc.). When these get mid-string in a JSON value the
    LLM emits, incomplete unicode escapes can break the JSON parser.
    """
    # Replace common curly quotes and em-dashes with ASCII equivalents
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    # Replace any remaining replacement character
    text = text.replace("\ufffd", "?")
    return text


def _extract_claims_from_text(text: str, source_label: str, llm, model: str) -> list[dict]:
    """Ask the LLM to extract management claims from a block of transcript text."""
    system_prompt = (
        "You are a financial due-diligence analyst. "
        "Extract specific, verifiable CLAIMS that management makes in the following earnings release text. "
        "Focus on: revenue growth, product pipeline, market position, customer demand, profitability outlook, "
        "competitive advantages, or any forward-looking statements. "
        "Ignore boilerplate legal disclaimers and SEC form headers.\n\n"
        "Return a JSON array of objects, each with:\n"
        '  "claim":     the specific claim management made (one sentence, direct quote or close paraphrase)\n'
        '  "topic":     the business topic (e.g. "revenue growth", "product pipeline", "margins")\n'
        '  "metric":    the financial or operational metric referenced '
        '(e.g. "revenue", "gross margin", "customer count") — use "" if none\n'
        '  "direction": the direction of change claimed — "increase" | "decrease" | "stable" | ""\n'
        '  "value":     the specific numeric value or percentage stated (e.g. "22%", "$60B") — use "" if none\n\n'
        "Return ONLY the JSON array. If no meaningful claims are found, return []."
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
        result = parse_llm_json(raw, "[claim_extractor]")
        if not isinstance(result, list):
            return []
        # Attach source label to each claim
        for c in result:
            c["source"] = source_label
        return result
    except Exception as exc:
        logger.warning("[claim_extractor] LLM call failed: %s", exc)
        return []


def _load_edgar_mda_chunks(ticker: str) -> list[dict]:
    """Load MD&A / Results-of-Operations chunks from EDGAR as a claims fallback.

    When earnings releases are bare 8-K wrappers (no actual press release body),
    we pull Item 7 MD&A text where management describes their own view of results.
    """
    import json as _json

    # CIK lookup (mirrors fact_extractor mapping)
    _cik_map = {
        "AAPL": "0000320193", "MSFT": "0000789019", "NVDA": "0001045810",
        "AMZN": "0001018724", "META": "0001326801", "GOOGL": "0001652044",
        "TSLA": "0001318605", "CRM":  "0001108524", "SNOW": "0001640147",
        "CRWD": "0001535527", "PANW": "0001327567", "FTNT": "0001262039",
    }
    target_cik = _cik_map.get(ticker.upper(), "")

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, "output", "edgar", "chunked_documents.json")
    if not os.path.exists(path):
        return []

    with open(path, encoding="utf-8") as f:
        all_chunks = _json.load(f)

    # Management-narrative sections
    mda_keywords = {
        "item 7", "item 2", "results of operations", "management",
        "revenue", "net sales", "operating income", "outlook",
    }
    matched = []
    for chunk in all_chunks:
        meta = chunk.get("metadata", {})
        if target_cik and meta.get("cik", "") != target_cik:
            continue
        item = meta.get("item_number", "").lower()
        title = meta.get("item_title", "").lower()
        text_lower = chunk.get("text", "").lower()
        if any(kw in item or kw in title or kw in text_lower for kw in mda_keywords):
            matched.append(chunk)
    logger.info("[claim_extractor] Found %d EDGAR MD&A chunks for %s (fallback)", len(matched), ticker)
    return matched


def extract_claims(ticker: str, llm=None, model: str = "") -> list[dict]:
    """Extract management claims from earnings transcript chunks for a ticker.

    Primary source: output/transcripts/chunked_documents.json (8-K earnings releases)
    Fallback source: output/edgar/chunked_documents.json (Item 7 MD&A sections)
      — used when the 8-K files are bare SEC form wrappers without substantive content.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL"
        llm:    Optional pre-built OpenAI client (created internally if None)
        model:  LLM model name (uses config default if empty)

    Returns:
        List of claim dicts:
            {
                "claim":  "Management stated revenue grew 6% year-over-year",
                "topic":  "revenue growth",
                "source": "Apple Inc. 8-K Earnings Release (2026-01-29)"
            }
    """
    if llm is None:
        llm, model = _build_llm_client()

    chunks = _load_transcript_chunks(ticker)
    if not chunks:
        logger.warning("[claim_extractor] No transcript chunks found for %s", ticker)

    # ── Try the transcript (8-K) source first ────────────────────────────────
    by_title: dict[str, list[str]] = {}
    for chunk in chunks:
        title = chunk.get("metadata", {}).get("transcript_title", "Unknown Transcript")
        by_title.setdefault(title, []).append(chunk.get("text", ""))

    all_claims: list[dict] = []
    calls_made = 0

    for title, texts in list(by_title.items())[:_MAX_LLM_CALLS]:
        if calls_made >= _MAX_LLM_CALLS:
            break
        combined = "\n\n".join(texts[:_MAX_CHUNKS_PER_CALL])
        claims = _extract_claims_from_text(combined, title, llm, model)
        logger.info("[claim_extractor] Extracted %d claims from '%s'", len(claims), title)
        all_claims.extend(claims)
        calls_made += 1
        time.sleep(1.5)  # throttle: stay within Groq token-per-minute limit

    # ── Fallback: EDGAR MD&A if transcripts yielded nothing substantive ───────
    if not all_claims:
        logger.info(
            "[claim_extractor] 8-K chunks contain no claims (likely bare wrappers). "
            "Falling back to EDGAR MD&A sections."
        )
        mda_chunks = _load_edgar_mda_chunks(ticker)

        # Group by filing date so we batch one filing at a time
        by_filing: dict[str, list[str]] = {}
        for chunk in mda_chunks:
            meta = chunk.get("metadata", {})
            label = f"{meta.get('filing_type','10-K')} {meta.get('filing_date','')}".strip()
            by_filing.setdefault(label, []).append(chunk.get("text", ""))

        for label, texts in list(by_filing.items())[:_MAX_LLM_CALLS]:
            combined = "\n\n".join(texts[:_MAX_CHUNKS_PER_CALL])
            claims = _extract_claims_from_text(combined, label, llm, model)
            logger.info("[claim_extractor] Fallback extracted %d claims from '%s'", len(claims), label)
            all_claims.extend(claims)
            time.sleep(1.5)  # throttle

    logger.info("[claim_extractor] Total claims for %s: %d", ticker, len(all_claims))
    return all_claims

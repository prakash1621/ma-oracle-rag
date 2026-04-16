"""Contradiction detector — main entry point for the insight layer.

Usage:
    from src.contradiction.detector import detect_contradictions
    result = detect_contradictions("AAPL")

Output schema:
    {
        "contradictions": [
            {
                "claim":       "CEO: We see strong pipeline growth (Q3 2024 earnings call)",
                "fact":        "Item 1A: Significant customer concentration risk (10-K 2024)",
                "severity":    "high",
                "explanation": "Management projects growth while filing discloses concentration risk",
                "claim_source": "Apple Inc. 8-K Earnings Release (2026-01-29)",
                "fact_source":  "10-K 2024-09-01"
            }
        ],
        "summary": "Found 3 contradictions for Apple Inc. (2 high, 1 medium)"
    }
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Map known tickers to human-readable company names for the summary line
_TICKER_NAMES: dict[str, str] = {
    "AAPL":  "Apple Inc.",
    "MSFT":  "Microsoft Corporation",
    "NVDA":  "NVIDIA Corporation",
    "AMZN":  "Amazon.com",
    "META":  "Meta Platforms",
    "GOOGL": "Alphabet (Google)",
    "TSLA":  "Tesla Inc.",
    "CRM":   "Salesforce",
    "SNOW":  "Snowflake",
    "CRWD":  "CrowdStrike",
    "PANW":  "Palo Alto Networks",
    "FTNT":  "Fortinet",
}


def _build_llm_client():
    """Build a shared LLM client passed down to sub-modules (avoids triple init).

    Key resolution order:
      1. Environment variables already set in the shell
      2. .env file at the project root (auto-loaded via python-dotenv)
      3. config.yaml defaults
    """
    from src.contradiction._llm import build_llm_client, resolve_llm_config

    resolved = resolve_llm_config()
    llm, model = build_llm_client()
    logger.info(
        "[detector] LLM provider=%s model=%s endpoint=%s",
        resolved.get("provider", ""),
        model,
        resolved.get("base_url", resolved.get("azure_endpoint", "")),
    )
    return llm, model


def _build_summary(ticker: str, contradictions: list[dict], not_supported: list[dict]) -> str:
    """Build a human-readable summary line."""
    company = _TICKER_NAMES.get(ticker.upper(), ticker.upper())
    total = len(contradictions)

    parts = []
    if total > 0:
        high = sum(1 for c in contradictions if c.get("severity") == "high")
        medium = sum(1 for c in contradictions if c.get("severity") == "medium")
        low = sum(1 for c in contradictions if c.get("severity") == "low")
        severity_str = ", ".join(filter(None, [
            f"{high} high" if high else "",
            f"{medium} medium" if medium else "",
            f"{low} low" if low else "",
        ]))
        parts.append(f"Found {total} contradiction{'s' if total != 1 else ''} ({severity_str})")
    else:
        parts.append("No contradictions found")

    if not_supported:
        parts.append(
            f"{len(not_supported)} claim{'s' if len(not_supported) != 1 else ''} "
            "not supported by 10-K disclosures"
        )

    return f"{company}: " + "; ".join(parts)


def detect_contradictions(ticker: str) -> dict:
    """Detect contradictions between earnings call claims and 10-K facts.

    Step 1 — Reads transcript chunks for the ticker and extracts management claims.
    Step 2 — Reads EDGAR 10-K chunks for the ticker and extracts disclosed facts.
    Steps 3-6 — Topic retrieval, rule-based fast path, LLM 3-way classification,
                 deduplication and sorting.

    Args:
        ticker: Stock ticker, e.g. "AAPL"

    Returns:
        {
            "contradictions": [
                {
                    "claim":        str,   # management's statement
                    "fact":         str,   # disclosed filing fact
                    "severity":     str,   # "high" | "medium" | "low"
                    "explanation":  str,   # why they conflict
                    "claim_source": str,   # earnings release label
                    "fact_source":  str,   # 10-K filing label
                }
            ],
            "not_supported": [
                {
                    "claim":        str,   # management's statement
                    "claim_source": str,   # earnings release label
                    "explanation":  str,   # why it cannot be verified
                }
            ],
            "summary": str               # one-line human-readable summary
        }
    """
    from src.contradiction.claim_extractor import extract_claims
    from src.contradiction.fact_extractor import extract_facts
    from src.contradiction.comparator import compare

    ticker = ticker.upper()
    logger.info("[detector] Starting contradiction detection for %s", ticker)

    # Build one shared LLM client for all stages
    llm, model = _build_llm_client()

    # Step 1: Claims
    logger.info("[detector] Step 1 — extracting claims from transcripts")
    claims = extract_claims(ticker, llm=llm, model=model)
    logger.info("[detector] %d claims extracted", len(claims))

    # Step 2: Facts
    logger.info("[detector] Step 2 — extracting facts from 10-K filings")
    facts = extract_facts(ticker, llm=llm, model=model)
    logger.info("[detector] %d facts extracted", len(facts))

    # Steps 3-6: Retrieve → Rule-based → LLM classify → Post-process
    logger.info("[detector] Steps 3-6 — topic retrieval, fast-path, LLM classification")
    contradictions, not_supported = compare(claims, facts, llm=llm, model=model)
    logger.info(
        "[detector] %d contradictions flagged, %d not_supported",
        len(contradictions), len(not_supported),
    )

    summary = _build_summary(ticker, contradictions, not_supported)
    logger.info("[detector] %s", summary)

    return {
        "contradictions": contradictions,
        "not_supported":  not_supported,
        "summary": summary,
    }


# ── CLI smoke-test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"\n{'='*60}")
    print(f"  Contradiction Detector — {ticker_arg}")
    print(f"{'='*60}\n")

    result = detect_contradictions(ticker_arg)

    print(f"\nSummary: {result['summary']}\n")
    for i, c in enumerate(result["contradictions"], 1):
        print(f"--- Contradiction #{i} [{c.get('severity', '?').upper()}] ---")
        print(f"  CLAIM : {c.get('claim', '')}")
        print(f"  FACT  : {c.get('fact', '')}")
        print(f"  WHY   : {c.get('explanation', '')}")
        print(f"  Sources: {c.get('claim_source', '')} vs {c.get('fact_source', '')}")
        print()

    # Also dump the full JSON
    output_path = os.path.join("output", f"contradictions_{ticker_arg}.json")
    os.makedirs("output", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Full result saved to {output_path}")

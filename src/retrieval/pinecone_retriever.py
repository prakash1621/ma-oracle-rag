"""Pinecone vector search with category and ticker filtering.

Searches the ma-oracle-cap index using integrated embedding (search_records).
Filters by category metadata to route to the right document type.
"""

from __future__ import annotations

import os
import logging
from typing import Any

from pinecone import Pinecone, SearchQuery

logger = logging.getLogger(__name__)

# Map route names to actual category values stored in Pinecone metadata
_CATEGORY_MAP = {
    "sec_filing": "sec_filing",
    "transcript": "earnings_transcript",
    "proxy": "proxy_statement",
    "patent": "patent",
}


def _get_index():
    """Get a Pinecone index connection (lazy singleton)."""
    if not hasattr(_get_index, "_index"):
        from nl2sql.app.config import get_settings
        settings = get_settings()
        pc = Pinecone(api_key=settings.pinecone_api_key)
        _get_index._index = pc.Index(settings.pinecone_index_name)
        _get_index._namespace = "default"
    return _get_index._index, _get_index._namespace


def retrieve_from_pinecone(
    query: str,
    category: str,
    top_k: int = 5,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Search Pinecone for relevant chunks filtered by category and optional ticker.

    Args:
        query: Natural language search query.
        category: Route name — "sec_filing", "transcript", "proxy", or "patent".
        top_k: Maximum number of results to return.
        ticker: Optional company ticker to filter by (e.g. "AAPL").

    Returns:
        List of dicts with "text", "metadata", and "score" keys.
    """
    index, namespace = _get_index()

    # Build metadata filter
    pinecone_category = _CATEGORY_MAP.get(category, category)
    filter_dict: dict[str, Any] = {"category": {"$eq": pinecone_category}}
    if ticker:
        # Chunks may store ticker in company_name or a ticker field
        # Use company_name since that's what ingestion stores
        filter_dict["company_name"] = {"$eq": _ticker_to_company(ticker)}

    try:
        response = index.search_records(
            namespace=namespace,
            query=SearchQuery(
                inputs={"text": query},
                top_k=top_k,
                filter=filter_dict,
            ),
        )

        results = []
        for hit in response.result.hits:
            fields = hit.get("fields", {})
            metadata = {k: v for k, v in fields.items() if k != "chunk_text"}
            results.append({
                "text": fields.get("chunk_text", ""),
                "metadata": metadata,
                "score": hit.get("_score", 0.0),
            })
        return results

    except Exception as exc:
        logger.error("Pinecone search failed: %s", exc)
        return []


# Simple ticker → company name mapping for the 12 companies
_TICKER_COMPANY = {
    "AAPL": "Apple Inc.",
    "MSFT": "MICROSOFT CORP",
    "NVDA": "NVIDIA CORP",
    "AMZN": "AMAZON COM INC",
    "META": "Meta Platforms, Inc.",
    "GOOGL": "ALPHABET INC.",
    "TSLA": "Tesla, Inc.",
    "CRM": "Salesforce, Inc.",
    "SNOW": "SNOWFLAKE INC.",
    "CRWD": "CROWDSTRIKE HOLDINGS, INC.",
    "PANW": "Palo Alto Networks Inc",
    "FTNT": "FORTINET, INC.",
}


def _ticker_to_company(ticker: str) -> str:
    """Convert ticker to company name as stored in Pinecone metadata."""
    return _TICKER_COMPANY.get(ticker.upper(), ticker)

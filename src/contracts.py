"""Shared data contracts for the M&A Oracle RAG pipeline.

All persons import from here to ensure consistent data shapes
across router, retrieval, knowledge graph, and contradiction modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryRequest:
    """Incoming user question with optional filters."""
    question: str
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass
class Citation:
    """A single source reference attached to an answer."""
    company_name: str
    filing_type: str          # "10-K", "transcript", "proxy", "patent", "knowledge_graph"
    filing_date: str
    item_number: str = ""     # e.g. "Item 1A"
    source_text: str = ""     # the actual text snippet
    relevance_score: float = 0.0


@dataclass
class QueryResponse:
    """Final response returned by the RAG pipeline."""
    answer: str
    citations: list[Citation]
    route: str                # "sec_filing", "xbrl_financial", "transcript", "patent", "proxy", "knowledge_graph", "contradiction"
    confidence: float
    sources: list[dict[str, Any]] = field(default_factory=list)  # raw retrieved chunks
    extras: dict[str, Any] = field(default_factory=dict)  # route-specific data (e.g. sql, columns, rows for xbrl)

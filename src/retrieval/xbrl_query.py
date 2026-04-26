"""XBRL NL-to-SQL wrapper for the RAG pipeline.

Wraps the existing nl2sql/ service to convert financial questions
to SQL, execute against financials.db, and return structured results.
Includes a reranker that scores results by metric relevance, recency,
value significance, and data quality.
"""

from __future__ import annotations

import re
import asyncio
import logging
from datetime import datetime
from typing import Any

import nest_asyncio
nest_asyncio.apply()

logger = logging.getLogger(__name__)

# ─── Metric mappings for reranker relevance scoring ───
_METRIC_ALIASES = {
    "revenue": ["revenue", "revenues", "net sales", "total revenue"],
    "income": ["net income", "netincomeloss", "operating income", "operatingincomeloss"],
    "profit": ["net income", "netincomeloss", "gross profit"],
    "assets": ["assets", "total assets"],
    "liabilities": ["liabilities", "total liabilities"],
    "equity": ["stockholders equity", "stockholdersequity", "shareholders equity"],
    "cash": ["cash", "cashandcashequivalents"],
    "eps": ["earnings per share", "earningspershare", "eps"],
    "cash flow": ["cash flow", "operating cash flow", "free cash flow"],
}

_pipeline = None


def _get_pipeline():
    """Lazy-init the NL2SQL pipeline (reuses the same instance)."""
    global _pipeline
    if _pipeline is None:
        from nl2sql.app.config import get_settings
        from nl2sql.app.database import DatabaseClient
        from nl2sql.app.llm import SQLGenerator
        from nl2sql.app.memory import create_agent_memory
        from nl2sql.app.pipeline import NL2SQLPipeline
        from nl2sql.app.schema import load_database_schema
        from nl2sql.app.security import SQLValidator

        settings = get_settings()
        database = DatabaseClient(settings.db_path)
        schema = load_database_schema(settings.db_path)
        _pipeline = NL2SQLPipeline(
            settings=settings,
            database=database,
            sql_generator=SQLGenerator(settings=settings, schema=schema),
            sql_validator=SQLValidator(schema=schema, database=database),
            agent_memory=create_agent_memory(settings),
        )
    return _pipeline


def query_xbrl(question: str) -> dict[str, Any]:
    """Convert a financial question to SQL and return results.

    Args:
        question: Natural language financial question.

    Returns:
        Dict with sql, results, columns, and row_count.
    """
    try:
        pipeline = _get_pipeline()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(pipeline.run(question))

        rows = result.rows or []
        columns = result.columns or []

        result_dicts = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                result_dicts.append(dict(zip(columns, row)))
            else:
                result_dicts.append(row)

        return {
            "sql": result.sql_query or "",
            "results": rerank_results(result_dicts, question),
            "columns": columns,
            "row_count": result.row_count or len(rows),
        }
    except Exception as exc:
        logger.error("XBRL query failed: %s", exc)
        return {
            "sql": "",
            "results": [],
            "columns": [],
            "row_count": 0,
            "error": str(exc),
        }


# ─── Reranker ────────────────────────────────────────────────

def rerank_results(results: list[dict], query: str) -> list[dict]:
    """Rerank SQL result rows by relevance to the original query."""
    if not results or len(results) <= 1:
        return results

    query_lower = query.lower()
    weights = _analyze_query_intent(query_lower)
    current_year = datetime.now().year

    scored = []
    for row in results:
        scores = {
            "metric_relevance": _score_metric_relevance(row, query_lower),
            "recency": _score_recency(row, current_year, query_lower),
            "value_significance": _score_value_significance(row),
            "data_quality": _score_data_quality(row),
        }
        composite = sum(scores[k] * weights[k] for k in scores)
        scored.append((composite, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored]


def _analyze_query_intent(query: str) -> dict[str, float]:
    """Adjust scoring weights based on query intent."""
    weights = {
        "metric_relevance": 0.4,
        "recency": 0.25,
        "value_significance": 0.2,
        "data_quality": 0.15,
    }

    # If user specifies a year range, metric matters more than recency
    if re.search(r"\d{4}\s*[-–to]+\s*\d{4}", query):
        weights["recency"] = 0.15
        weights["metric_relevance"] = 0.5

    # Recency-focused queries
    if any(w in query for w in ["latest", "current", "recent", "newest"]):
        weights["recency"] = 0.4
        weights["metric_relevance"] = 0.35

    # Comparison queries
    if any(w in query for w in ["compare", "vs", "versus", "comparison", "trend"]):
        weights["value_significance"] = 0.3
        weights["recency"] = 0.2

    # Normalize
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def _score_metric_relevance(row: dict, query: str) -> float:
    """Score how well a result row matches the queried metric."""
    row_text = " ".join(str(v).lower() for v in row.values())

    for term, aliases in _METRIC_ALIASES.items():
        if term in query:
            if any(alias in row_text for alias in aliases):
                return 1.0
            return 0.5

    # No specific metric in query — neutral score
    return 0.6


def _score_recency(row: dict, current_year: int, query: str) -> float:
    """Score based on how recent the data is."""
    # Try to find a year in the row
    year = None
    for key in ["year", "fy", "fiscal_year", "filing_year", "period"]:
        if key in row:
            try:
                year = int(row[key])
                break
            except (ValueError, TypeError):
                pass

    # Try extracting from date fields
    if year is None:
        for key in ["filed", "filing_date", "end_date", "period_end"]:
            if key in row and row[key]:
                match = re.search(r"(\d{4})", str(row[key]))
                if match:
                    year = int(match.group(1))
                    break

    if year is None:
        return 0.5  # unknown recency

    years_old = current_year - year
    return max(0.2, 1.0 - (years_old * 0.12))


def _score_value_significance(row: dict) -> float:
    """Score based on the magnitude of numeric values (larger = more significant)."""
    max_val = 0
    for v in row.values():
        try:
            num = abs(float(v))
            if num > max_val:
                max_val = num
        except (ValueError, TypeError):
            continue

    if max_val >= 1e11:
        return 1.0
    elif max_val >= 1e9:
        return 0.8
    elif max_val >= 1e6:
        return 0.6
    return 0.4


def _score_data_quality(row: dict) -> float:
    """Score based on completeness of the row (fewer nulls = better)."""
    if not row:
        return 0.3
    non_null = sum(1 for v in row.values() if v is not None and v != "")
    return min(1.0, non_null / len(row))

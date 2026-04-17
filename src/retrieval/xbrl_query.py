"""XBRL NL-to-SQL wrapper for the RAG pipeline.

Wraps the existing nl2sql/ service to convert financial questions
to SQL, execute against financials.db, and return structured results.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import nest_asyncio
nest_asyncio.apply()

logger = logging.getLogger(__name__)

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
            "results": result_dicts,
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

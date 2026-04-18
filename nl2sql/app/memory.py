"""Pinecone-backed agent memory for NL2SQL few-shot examples.

Replaces ChromaDB/DemoAgentMemory with a Pinecone implementation using
the ``ma-oracle-cap`` index and a dedicated ``nl2sql-memory`` namespace.
Records use Pinecone integrated embedding via the ``chunk_text`` field.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pinecone import Pinecone, SearchQuery
from vanna.capabilities.agent_memory import (
    AgentMemory,
    TextMemory,
    TextMemorySearchResult,
    ToolMemory,
    ToolMemorySearchResult,
)
from vanna.core.tool import ToolContext
from vanna.core.user.models import User

from nl2sql.app.config import Settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds


def _deterministic_id(question: str) -> str:
    """Generate a deterministic record ID from a question string."""
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]
    return f"nl2sql-{digest}"


class PineconeAgentMemory(AgentMemory):
    """Pinecone-backed implementation of Vanna's AgentMemory."""

    def __init__(self, settings: Settings) -> None:
        if not settings.pinecone_api_key:
            raise ValueError(
                "PINECONE_API_KEY is required for PineconeAgentMemory. "
                "Set it in .env or as an environment variable."
            )
        self._namespace = settings.memory_namespace
        pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index = pc.Index(settings.pinecone_index_name)

    # ------------------------------------------------------------------
    # save_tool_usage
    # ------------------------------------------------------------------
    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Upsert a question-SQL record into Pinecone with retry on rate-limit."""
        record: Dict[str, Any] = {
            "_id": _deterministic_id(question),
            "text": question,  # Ensure 'text' field is included
            "tool_name": tool_name,
            "sql": args.get("sql", ""),
            "success": success,
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                self._index.upsert_records(
                    namespace=self._namespace,
                    records=[record],
                )
                return
            except Exception as exc:
                last_exc = exc
                # Retry on 429 / rate-limit errors
                if "429" in str(exc) or "rate" in str(exc).lower():
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "Pinecone rate limit hit (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        _MAX_RETRIES,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    logger.warning("Pinecone upsert failed: %s", exc)
                    return
        logger.warning(
            "Pinecone upsert failed after %d retries: %s", _MAX_RETRIES, last_exc
        )

    # ------------------------------------------------------------------
    # search_similar_usage
    # ------------------------------------------------------------------
    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:
        """Search for similar tool usage patterns using Pinecone integrated embedding."""
        try:
            query_filter: Dict[str, Any] | None = None
            if tool_name_filter:
                query_filter = {"tool_name": {"$eq": tool_name_filter}}

            response = self._index.search_records(
                namespace=self._namespace,
                query=SearchQuery(
                    inputs={"text": question},
                    top_k=limit,
                    filter=query_filter,
                ),
            )

            results: List[ToolMemorySearchResult] = []
            for rank, hit in enumerate(response.result.hits, start=1):
                score = hit.get("_score", 0.0)
                if score < similarity_threshold:
                    continue
                fields = hit.get("fields", {})
                results.append(
                    ToolMemorySearchResult(
                        memory=ToolMemory(
                            memory_id=hit.get("_id", ""),
                            question=fields.get("chunk_text", ""),
                            tool_name=fields.get("tool_name", "run_sql"),
                            args={"sql": fields.get("sql", "")},
                            success=fields.get("success", True),
                        ),
                        similarity_score=score,
                        rank=rank,
                    )
                )
            return results
        except Exception as exc:
            logger.warning("Pinecone search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # get_recent_memories
    # ------------------------------------------------------------------
    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:
        """List records from the namespace by listing IDs and fetching them."""
        try:
            all_ids: List[str] = []
            for id_batch in self._index.list(
                namespace=self._namespace, prefix="nl2sql-"
            ):
                all_ids.extend(id_batch)
                if len(all_ids) >= limit:
                    break
            all_ids = all_ids[:limit]
            if not all_ids:
                return []

            fetched = self._index.fetch(ids=all_ids, namespace=self._namespace)
            memories: List[ToolMemory] = []
            for vec_id, vec in fetched.vectors.items():
                meta = vec.metadata or {}
                memories.append(
                    ToolMemory(
                        memory_id=vec_id,
                        question=meta.get("chunk_text", ""),
                        tool_name=meta.get("tool_name", "run_sql"),
                        args={"sql": meta.get("sql", "")},
                        success=meta.get("success", True),
                    )
                )
            return memories
        except Exception as exc:
            logger.warning("Pinecone get_recent_memories failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Text memory stubs (not used by NL2SQL, but required by interface)
    # ------------------------------------------------------------------
    async def save_text_memory(
        self, content: str, context: ToolContext
    ) -> TextMemory:
        """Not used by NL2SQL — returns a stub TextMemory."""
        return TextMemory(memory_id=str(uuid4()), content=content)

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        """Not used by NL2SQL — returns empty list."""
        return []

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        """Not used by NL2SQL — returns empty list."""
        return []

    async def delete_by_id(self, context: ToolContext, memory_id: str) -> bool:
        """Delete a memory record by its ID."""
        try:
            self._index.delete(ids=[memory_id], namespace=self._namespace)
            return True
        except Exception as exc:
            logger.warning("Pinecone delete failed: %s", exc)
            return False

    async def delete_text_memory(
        self, context: ToolContext, memory_id: str
    ) -> bool:
        """Not used by NL2SQL — returns False."""
        return False

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        """Clear all memories in the namespace."""
        try:
            self._index.delete(delete_all=True, namespace=self._namespace)
            return -1  # Pinecone doesn't return count on delete_all
        except Exception as exc:
            logger.warning("Pinecone clear_memories failed: %s", exc)
            return 0


# ------------------------------------------------------------------
# count_memories
# ------------------------------------------------------------------
def count_memories(agent_memory: AgentMemory) -> int:
    """Return the number of vectors in the nl2sql-memory namespace."""
    if isinstance(agent_memory, PineconeAgentMemory):
        try:
            stats = agent_memory._index.describe_index_stats()
            ns_map = stats.get("namespaces", {})
            ns_info = ns_map.get(agent_memory._namespace, {})
            return ns_info.get("vector_count", 0)
        except Exception as exc:
            logger.warning("describe_index_stats failed: %s", exc)
            return 0
    return 0


# ------------------------------------------------------------------
# build_tool_context  (preserved from original)
# ------------------------------------------------------------------
def build_tool_context(agent_memory: AgentMemory) -> ToolContext:
    """Create a ToolContext for pipeline / seed_memory calls."""
    return ToolContext(
        user=User(
            id="default_user",
            email="user@example.com",
            group_memberships=[],
        ),
        conversation_id="nl2sql-api",
        request_id=str(uuid4()),
        agent_memory=agent_memory,
    )


# ------------------------------------------------------------------
# create_agent_memory  (factory function)
# ------------------------------------------------------------------
def create_agent_memory(settings: Settings) -> AgentMemory:
    """Create a PineconeAgentMemory instance from settings."""
    return PineconeAgentMemory(settings)

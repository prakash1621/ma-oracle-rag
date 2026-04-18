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
_BACKOFF_BASE = 1.0


# ---------------------------------------------------------
# Utility
# ---------------------------------------------------------
def _deterministic_id(question: str) -> str:
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]
    return f"nl2sql-{digest}"


# ---------------------------------------------------------
# Main Memory Class
# ---------------------------------------------------------
class PineconeAgentMemory(AgentMemory):
    def __init__(self, settings: Settings) -> None:
        if not settings.pinecone_api_key:
            raise ValueError("PINECONE_API_KEY missing")

        if not settings.pinecone_index_name:
            raise ValueError("PINECONE_INDEX_NAME missing")

        self._namespace = settings.memory_namespace

        pc = Pinecone(api_key=settings.pinecone_api_key)

        # ✅ Ensure index exists
        existing_indexes = [i["name"] for i in pc.list_indexes()]
        if settings.pinecone_index_name not in existing_indexes:
            logger.warning("Index not found. Creating new index...")
            pc.create_index(
                name=settings.pinecone_index_name,
                dimension=1536,
                metric="cosine",
            )

        self._index = pc.Index(settings.pinecone_index_name)

    # ---------------------------------------------------------
    # SAVE MEMORY
    # ---------------------------------------------------------
    async def save_tool_usage(
        self,
        question: str,
        tool_name: str,
        args: Dict[str, Any],
        context: ToolContext,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:

        if not question:
            logger.warning("Skipping empty question")
            return

        record = {
            "_id": _deterministic_id(question),
            "text": question,  # 🔥 REQUIRED for Pinecone
            "tool_name": tool_name,
            "sql": args.get("sql", ""),
            "success": success,
        }

        last_exc = None

        for attempt in range(_MAX_RETRIES):
            try:
                self._index.upsert_records(
                    namespace=self._namespace,
                    records=[record],
                )
                return
            except Exception as exc:
                last_exc = exc

                if "429" in str(exc) or "rate" in str(exc).lower():
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(f"Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error("Upsert failed: %s", exc)
                    return

        logger.error("Failed after retries: %s", last_exc)

    # ---------------------------------------------------------
    # SEARCH MEMORY
    # ---------------------------------------------------------
    async def search_similar_usage(
        self,
        question: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
        tool_name_filter: Optional[str] = None,
    ) -> List[ToolMemorySearchResult]:

        try:
            query_filter = None
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

            results = []

            for rank, hit in enumerate(response.result.hits, start=1):
                score = hit.get("_score", 0.0)
                if score < similarity_threshold:
                    continue

                fields = hit.get("fields", {})

                results.append(
                    ToolMemorySearchResult(
                        memory=ToolMemory(
                            memory_id=hit.get("_id", ""),
                            question=fields.get("text", ""),
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
            logger.error("Search failed: %s", exc)
            return []

    # ---------------------------------------------------------
    # GET RECENT
    # ---------------------------------------------------------
    async def get_recent_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[ToolMemory]:

        try:
            all_ids = []

            for batch in self._index.list(
                namespace=self._namespace, prefix="nl2sql-"
            ):
                all_ids.extend(batch)
                if len(all_ids) >= limit:
                    break

            if not all_ids:
                return []

            fetched = self._index.fetch(
                ids=all_ids[:limit], namespace=self._namespace
            )

            memories = []

            for vec_id, vec in fetched.vectors.items():
                meta = vec.metadata or {}

                memories.append(
                    ToolMemory(
                        memory_id=vec_id,
                        question=meta.get("text", ""),
                        tool_name=meta.get("tool_name", "run_sql"),
                        args={"sql": meta.get("sql", "")},
                        success=meta.get("success", True),
                    )
                )

            return memories

        except Exception as exc:
            logger.error("Fetch failed: %s", exc)
            return []

    # ---------------------------------------------------------
    # DELETE
    # ---------------------------------------------------------
    async def delete_by_id(self, context: ToolContext, memory_id: str) -> bool:
        try:
            self._index.delete(ids=[memory_id], namespace=self._namespace)
            return True
        except Exception as exc:
            logger.error("Delete failed: %s", exc)
            return False

    async def clear_memories(
        self,
        context: ToolContext,
        tool_name: Optional[str] = None,
        before_date: Optional[str] = None,
    ) -> int:
        try:
            self._index.delete(delete_all=True, namespace=self._namespace)
            return -1
        except Exception as exc:
            logger.error("Clear failed: %s", exc)
            return 0

    # ---------------------------------------------------------
    # UNUSED TEXT MEMORY (required by interface)
    # ---------------------------------------------------------
    async def save_text_memory(
        self, content: str, context: ToolContext
    ) -> TextMemory:
        return TextMemory(memory_id=str(uuid4()), content=content)

    async def search_text_memories(
        self,
        query: str,
        context: ToolContext,
        *,
        limit: int = 10,
        similarity_threshold: float = 0.7,
    ) -> List[TextMemorySearchResult]:
        return []

    async def get_recent_text_memories(
        self, context: ToolContext, limit: int = 10
    ) -> List[TextMemory]:
        return []
    
    async def delete_text_memory(
        self, context: ToolContext, memory_id: str
    ) -> bool:
        """Not used in NL2SQL — stub implementation."""
        return False

# ---------------------------------------------------------
# HELPER FUNCTIONS (REQUIRED BY YOUR APP)
# ---------------------------------------------------------
def count_memories(agent_memory: AgentMemory) -> int:
    if isinstance(agent_memory, PineconeAgentMemory):
        try:
            stats = agent_memory._index.describe_index_stats()
            namespaces = stats.get("namespaces", {})
            ns = namespaces.get(agent_memory._namespace, {})
            return ns.get("vector_count", 0)
        except Exception as e:
            logger.warning("count_memories failed: %s", e)
            return 0
    return 0


def build_tool_context(agent_memory: AgentMemory) -> ToolContext:
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


def create_agent_memory(settings: Settings) -> AgentMemory:
    return PineconeAgentMemory(settings)
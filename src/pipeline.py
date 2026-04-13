"""RAG Pipeline — main entry point for the M&A Oracle query system.

Routes questions to the appropriate retrieval source, fetches data,
and generates answers with citations.

Usage:
    from src.pipeline import RAGPipeline
    p = RAGPipeline(use_mocks=True)
    result = p.query("What was Apple's revenue in 2024?")
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from src.contracts import Citation, QueryResponse

logger = logging.getLogger(__name__)

# Valid routes the router can return
VALID_ROUTES = [
    "sec_filing",
    "xbrl_financial",
    "transcript",
    "patent",
    "proxy",
    "knowledge_graph",
    "contradiction",
]

# Routes that use Pinecone retriever (same function, different category filter)
PINECONE_ROUTES = {"sec_filing", "transcript", "proxy", "patent"}


def _build_llm_client():
    """Build an OpenAI-compatible LLM client using config.yaml settings."""
    from openai import OpenAI
    from nl2sql.app.config import get_settings

    settings = get_settings()
    base_url = settings.llm_base_url
    api_key = settings.groq_api_key or os.environ.get("OPENAI_API_KEY", "") or os.environ.get("GROQ_API_KEY", "")
    return OpenAI(base_url=base_url, api_key=api_key), settings.llm_model


def _classify_question(question: str, llm: Any, model: str) -> str:
    """Classify a question into a route. Uses keyword matching first (instant), LLM as fallback."""
    q_lower = question.lower()

    # Keyword-based routing — instant, no LLM call
    financial_keywords = [
        "revenue", "income", "profit", "assets", "liabilities", "cash flow",
        "eps", "earnings per share", "balance sheet", "expenses", "debt",
        "equity", "margin", "ebitda", "gross profit", "net income",
        "total assets", "operating income", "dividend", "fiscal year",
        "how much", "show me the top", "compare", "quarterly",
    ]
    transcript_keywords = [
        "earnings call", "ceo said", "cfo said", "management said",
        "earnings transcript", "call transcript", "what did",
    ]
    patent_keywords = ["patent", "invention", "ip ", "intellectual property"]
    proxy_keywords = ["proxy", "compensation", "governance", "executive pay"]
    kg_keywords = [
        "board member", "board of director", "who serves", "relationship",
        "connected to", "subsidiary", "who are",
    ]
    contradiction_keywords = [
        "contradict", "contradiction", "mismatch", "inconsisten",
        "claims vs", "compare what", "management vs filing",
    ]
    sec_keywords = [
        "risk factor", "10-k", "10k", "filing", "sec filing",
        "business description", "item 1a", "annual report",
    ]

    if any(kw in q_lower for kw in financial_keywords):
        return "xbrl_financial"
    if any(kw in q_lower for kw in transcript_keywords):
        return "transcript"
    if any(kw in q_lower for kw in patent_keywords):
        return "patent"
    if any(kw in q_lower for kw in proxy_keywords):
        return "proxy"
    if any(kw in q_lower for kw in kg_keywords):
        return "knowledge_graph"
    if any(kw in q_lower for kw in contradiction_keywords):
        return "contradiction"
    if any(kw in q_lower for kw in sec_keywords):
        return "sec_filing"

    # Fallback to LLM only for ambiguous questions
    logger.info("No keyword match, using LLM router for: %s", question[:50])
    system_prompt = (
        "You are a question classifier for an M&A financial analysis system. "
        "Classify the user's question into exactly one of these routes:\n"
        "- xbrl_financial: questions asking for specific financial NUMBERS like revenue, assets, income, EPS, cash flow, profit, expenses, balance sheet values, or any quantitative financial data\n"
        "- sec_filing: questions about 10-K filing TEXT content, risk factors, business descriptions, strategies, or qualitative information from filings\n"
        "- transcript: questions about earnings calls, what CEO/CFO said, management commentary\n"
        "- patent: questions about patents, inventions, IP\n"
        "- proxy: questions about proxy statements, board compensation, governance\n"
        "- knowledge_graph: questions about relationships between entities, board members, who serves where\n"
        "- contradiction: questions about contradictions between management claims and filings\n\n"
        "IMPORTANT: If the question asks for a financial number or metric (revenue, assets, income, etc.), ALWAYS classify as xbrl_financial.\n"
        "Respond with ONLY the route name, nothing else."
    )
    response = llm.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        temperature=0,
        max_tokens=20,
    )
    route = response.choices[0].message.content.strip().lower()
    return route if route in VALID_ROUTES else "sec_filing"


def _generate_answer(question: str, chunks: list[dict], llm: Any, model: str) -> str:
    """Use LLM to generate an answer from retrieved chunks."""
    if not chunks:
        return "I couldn't find relevant information to answer your question."

    context = "\n\n".join(
        f"Source {i+1}: {c.get('text', c.get('claim', str(c)))}"
        for i, c in enumerate(chunks[:5])
    )
    response = llm.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a financial analyst assistant. Answer the question based on "
                    "the provided sources. Cite which source number you used. Be concise and factual."
                ),
            },
            {"role": "user", "content": f"Question: {question}\n\nSources:\n{context}"},
        ],
        temperature=0,
    )
    return response.choices[0].message.content.strip()


def _chunks_to_citations(chunks: list[dict], route: str) -> list[Citation]:
    """Convert raw retrieved chunks to Citation objects."""
    citations = []
    for c in chunks:
        meta = c.get("metadata", {})
        citations.append(
            Citation(
                company_name=meta.get("company", meta.get("ticker", "")),
                filing_type=meta.get("filing_type", route),
                filing_date=meta.get("filing_date", ""),
                source_text=c.get("text", c.get("claim", str(c)))[:200],
                relevance_score=c.get("score", 0.0),
            )
        )
    return citations


class RAGPipeline:
    """Main RAG pipeline — routes questions and generates answers.

    Args:
        use_mocks: If True, use mock functions instead of real Person 2/3/4 code.
    """

    def __init__(self, use_mocks: bool = True):
        self.use_mocks = use_mocks
        self._llm = None  # lazy init

        if use_mocks:
            from src.mocks import (
                mock_contradiction,
                mock_kg,
                mock_patents,
                mock_retrieve,
                mock_xbrl,
            )
            self._retrieve = mock_retrieve
            self._query_xbrl = mock_xbrl
            self._query_patents = mock_patents
            self._query_kg = mock_kg
            self._detect_contradictions = mock_contradiction
        else:
            # Real imports from Person 2/3/4 — uncomment on Day 4
            from src.retrieval.pinecone_retriever import retrieve_from_pinecone
            from src.retrieval.xbrl_query import query_xbrl
            from src.retrieval.patent_query import query_patents
            from src.knowledge_graph.query import query_knowledge_graph
            from src.contradiction.detector import detect_contradictions
            self._retrieve = retrieve_from_pinecone
            self._query_xbrl = query_xbrl
            self._query_patents = query_patents
            self._query_kg = query_knowledge_graph
            self._detect_contradictions = detect_contradictions

    @property
    def llm(self):
        if self._llm is None:
            self._llm, self._llm_model = _build_llm_client()
        return self._llm

    @property
    def llm_model(self):
        if self._llm is None:
            self._llm, self._llm_model = _build_llm_client()
        return self._llm_model

    def query(self, question: str, filters: dict | None = None) -> QueryResponse:
        """Run the full RAG pipeline: route → retrieve → generate → respond."""
        import time
        filters = filters or {}
        ticker = filters.get("ticker")

        t0 = time.time()

        # Step 1: Route
        route = _classify_question(question, self.llm, self.llm_model)
        t1 = time.time()
        logger.info("[TIMING] Route: %.2fs → %s for '%s'", t1 - t0, route, question[:50])
        print(f"[TIMING] Route: {t1 - t0:.2f}s → {route} for '{question[:50]}'")

        # Step 2: Retrieve based on route
        chunks, extras = self._fetch(route, question, ticker)
        t2 = time.time()
        logger.info("[TIMING] Fetch: %.2fs (%d chunks)", t2 - t1, len(chunks))
        print(f"[TIMING] Fetch: {t2 - t1:.2f}s ({len(chunks)} chunks)")

        # Step 3: Generate answer
        answer = _generate_answer(question, chunks, self.llm, self.llm_model)
        t3 = time.time()
        logger.info("[TIMING] Generate: %.2fs", t3 - t2)
        print(f"[TIMING] Generate: {t3 - t2:.2f}s")
        print(f"[TIMING] Total: {t3 - t0:.2f}s | Model: {self.llm_model} | Base URL: {self.llm.base_url}")

        # Step 4: Build response
        return QueryResponse(
            answer=answer,
            citations=_chunks_to_citations(chunks, route),
            route=route,
            confidence=0.9 if chunks else 0.3,
            sources=chunks,
            extras=extras,
        )

    def _fetch(self, route: str, question: str, ticker: str | None = None) -> tuple[list[dict], dict]:
        """Dispatch to the right retrieval function based on route. Returns (chunks, extras)."""
        extras: dict = {}
        try:
            if route == "xbrl_financial":
                result = self._query_xbrl(question)
                extras = {
                    "sql_query": result.get("sql", ""),
                    "columns": result.get("columns", []),
                    "rows": result.get("results", []),
                    "row_count": result.get("row_count", len(result.get("results", []))),
                }
                return [
                    {
                        "text": f"SQL: {result['sql']}\nResults: {result['results']}",
                        "metadata": {"filing_type": "XBRL", "company": ticker or ""},
                        "score": 1.0,
                    }
                ], extras

            if route in PINECONE_ROUTES:
                return self._retrieve(question, category=route, top_k=5, ticker=ticker), extras

            if route == "knowledge_graph":
                result = self._query_kg(question, tickers=[ticker] if ticker else None)
                return [
                    {
                        "text": f"Cypher: {result['cypher']}\nResults: {result['results']}",
                        "metadata": {"filing_type": "knowledge_graph", "company": ticker or ""},
                        "score": 1.0,
                    }
                ], extras

            if route == "contradiction":
                result = self._detect_contradictions(ticker or "AAPL")
                return [
                    {
                        "text": c.get("explanation", ""),
                        "metadata": {"filing_type": "contradiction", "company": ticker or ""},
                        "claim": c.get("claim", ""),
                        "fact": c.get("fact", ""),
                        "score": 1.0,
                    }
                    for c in result.get("contradictions", [])
                ], extras

            # Fallback
            return self._retrieve(question, category="sec_filing", top_k=5, ticker=ticker), extras

        except Exception as exc:
            logger.error("Retrieval failed for route '%s': %s", route, exc)
            return [], extras

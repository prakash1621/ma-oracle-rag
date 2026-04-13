"""Mock functions for Person 2/3/4's modules.

Used by Person 1 during Days 1-3 while real implementations are being built.
Swap these out for real imports on Day 4 integration.
"""

from __future__ import annotations


def mock_retrieve(query: str, category: str, top_k: int = 5, ticker: str | None = None) -> list[dict]:
    """Mock for Person 2's retrieve_from_pinecone."""
    return [
        {
            "text": f"Mock chunk for '{query}' in {category}: Apple reported strong revenue growth in FY2024.",
            "metadata": {
                "company": "Apple Inc.",
                "ticker": ticker or "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-09-28",
                "source": category,
            },
            "score": 0.92,
        },
        {
            "text": f"Mock chunk 2 for '{query}': Risk factors include customer concentration.",
            "metadata": {
                "company": "Apple Inc.",
                "ticker": ticker or "AAPL",
                "filing_type": "10-K",
                "filing_date": "2024-09-28",
                "source": category,
            },
            "score": 0.85,
        },
    ][:top_k]


def mock_xbrl(question: str) -> dict:
    """Mock for Person 2's query_xbrl."""
    return {
        "sql": "SELECT c.entity_name, f.value FROM financial_facts f JOIN companies c ON c.cik = f.cik WHERE c.ticker = 'AAPL'",
        "results": [{"entity_name": "Apple Inc.", "value": 391035000000, "label": "Revenue"}],
        "columns": ["entity_name", "value", "label"],
        "row_count": 1,
    }


def mock_patents(question: str, ticker: str | None = None) -> list[dict]:
    """Mock for Person 2's query_patents."""
    return [
        {
            "patent_id": "US11893789",
            "title": "GPU transformer inference optimization",
            "date": "2024-03-15",
            "ticker": ticker or "NVDA",
            "abstract": "A method for optimizing transformer model inference on GPU architectures.",
        },
    ]


def mock_kg(question: str, tickers: list[str] | None = None) -> dict:
    """Mock for Person 3's query_knowledge_graph."""
    return {
        "cypher": "MATCH (c:Company {ticker:'AAPL'})-[:HAS_BOARD_MEMBER]->(b) RETURN b.name, b.title",
        "results": [
            {"name": "Tim Cook", "title": "CEO"},
            {"name": "Jeff Williams", "title": "COO"},
        ],
        "graph_data": {
            "nodes": [
                {"id": "apple", "type": "Company", "label": "Apple Inc."},
                {"id": "tim_cook", "type": "BoardMember", "label": "Tim Cook"},
            ],
            "edges": [
                {"from": "apple", "to": "tim_cook", "type": "HAS_BOARD_MEMBER"},
            ],
        },
    }


def mock_contradiction(ticker: str) -> dict:
    """Mock for Person 4's detect_contradictions."""
    return {
        "contradictions": [
            {
                "claim": "CEO: We see strong pipeline growth (Q3 2024 earnings call)",
                "fact": "Item 1A: Significant customer concentration risk (10-K 2024)",
                "severity": "high",
                "explanation": "Management projects growth while filing discloses concentration risk",
            },
        ],
        "summary": f"Found 1 contradiction for {ticker} (1 high)",
    }

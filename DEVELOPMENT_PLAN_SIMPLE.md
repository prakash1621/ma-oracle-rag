# M&A Oracle — Simple 4-Person Plan (1 Week)

**Deadline:** Sunday, 19 April 2026
**What's done:** Data ingestion (6 sources → Pinecone + SQLite). NL2SQL microservice.
**What's missing:** Everything else — RAG pipeline, API, frontend, evaluation.

---

## Who Does What

```
Person 1 (Prakash) → RAG Pipeline     (the brain — takes a question, returns an answer)
Person 2           → Knowledge Graph   (Neo4j + contradiction detection)
Person 3           → Backend API       (FastAPI + auth + logging)
Person 4           → Frontend + Eval   (Next.js UI + run 30 test queries)
```

---

## How It All Connects

```
User types question
        ↓
   [Frontend]  ←── Person 4 builds this
        ↓
   [FastAPI]   ←── Person 3 builds this
        ↓
   [RAG Pipeline]  ←── Person 1 builds this
        ↓                    ↓
   [Pinecone]          [Knowledge Graph]  ←── Person 2 builds this
   [XBRL SQLite]       [Contradiction]
        ↓
   Answer + Citations returned to user
```

---

## Person 1 — RAG Pipeline (Prakash)

**Branch:** `feature/rag-pipeline`
**Folder:** `src/`

**What you build:**
A Python class `RAGPipeline` with one method: `query(question) → answer + citations`

**How it works:**
1. User asks a question
2. Router (LLM) decides which data source to search
3. Retrieve relevant chunks from Pinecone or query XBRL SQLite
4. LLM generates answer with citations from retrieved chunks
5. Return answer

**Routes (which data source to search):**
| Question type | Route to |
|--------------|----------|
| "What are Apple's risk factors?" | Pinecone → SEC filing chunks |
| "What was Apple's revenue in 2024?" | XBRL SQLite → NL-to-SQL |
| "What did the CEO say about growth?" | Pinecone → Transcript chunks |
| "How many patents does NVIDIA have?" | Pinecone → Patent chunks |
| "Who is on Apple's board?" | Pinecone → Proxy statement chunks |
| "Show relationships between companies" | Neo4j (Person 2's module) |

**Files to create:**
```
src/
├── pipeline.py          # RAGPipeline class (main entry point)
├── router.py            # Classifies question → route
├── retriever.py         # Searches Pinecone
├── xbrl_query.py        # NL-to-SQL for financial data
├── generator.py         # LLM generates answer from retrieved chunks
└── contracts.py         # Shared data classes (everyone imports this)
```

**The main class everyone else calls:**
```python
# src/pipeline.py
class RAGPipeline:
    def query(self, question: str, filters: dict = None) -> dict:
        """
        Input:  "What was Apple's total revenue in fiscal year 2024?"
        Output: {
            "answer": "Apple's total revenue in FY2024 was $391.0 billion...",
            "citations": [{"company": "Apple", "filing": "10-K", "date": "2024-11-01", "section": "Item 8"}],
            "route": "xbrl_financial",
            "confidence": 0.92
        }
        """
```

**Until Person 2 delivers Knowledge Graph, use this mock:**
```python
def mock_kg_query(question):
    return {"results": [], "message": "Knowledge graph not yet connected"}
```

**Test independently:**
```bash
python -c "from src.pipeline import RAGPipeline; p = RAGPipeline(); print(p.query('What was Apple revenue in 2024?'))"
```

---

## Person 2 — Knowledge Graph + Contradiction Detection

**Branch:** `feature/knowledge-graph`
**Folder:** `src/knowledge_graph/` and `src/contradiction/`

**What you build:**
1. A Neo4j graph connecting Companies → Board Members → Patents → Risk Factors
2. A contradiction detector that compares what CEO says on earnings calls vs what 10-K filings say

**Knowledge Graph — step by step:**
1. Install Neo4j Desktop (free) or use Neo4j Aura (free cloud tier)
2. Read the existing JSON chunk files from `output/proxy/` and `output/edgar/`
3. Use LLM to extract entities (company names, board members, subsidiaries)
4. Load entities + relationships into Neo4j
5. Build a function that takes a natural language question → converts to Cypher query → returns results

**Contradiction Detection — step by step:**
1. Read transcript chunks from `output/transcripts/chunked_documents.json`
2. Read 10-K chunks from `output/edgar/chunked_documents.json`
3. For each company, extract "claims" from transcripts (what management says)
4. Extract "facts" from 10-K filings (what's actually disclosed)
5. Use LLM to compare and flag contradictions

**Also:** Integrate 2 additional data sources (CourtListener for litigation + a News API)

**Files to create:**
```
src/
├── knowledge_graph/
│   ├── builder.py       # Extract entities from chunks → load into Neo4j
│   ├── query.py         # Natural language → Cypher → results
│   └── schema.py        # Node/relationship definitions
├── contradiction/
│   ├── detector.py      # Compare transcript claims vs filing facts
│   └── extractor.py     # Extract claims and facts from chunks
└── additional_sources/
    ├── courtlistener.py # Litigation data
    └── news.py          # News API
```

**The function Person 1 will call:**
```python
# src/knowledge_graph/query.py
def query_graph(question: str, tickers: list = None) -> dict:
    """
    Input:  "Who are Apple's board members?"
    Output: {
        "cypher": "MATCH (c:Company {ticker:'AAPL'})-[:HAS_BOARD_MEMBER]->(b) RETURN b",
        "results": [{"name": "Tim Cook", "title": "CEO"}, ...],
        "graph_data": {"nodes": [...], "edges": [...]}  # For frontend visualization
    }
    """

# src/contradiction/detector.py
def detect_contradictions(ticker: str) -> dict:
    """
    Input:  "AAPL"
    Output: {
        "contradictions": [
            {
                "claim": "CEO says strong pipeline growth (Q3 2024 call)",
                "filing": "Item 1A discloses customer concentration risk (10-K 2024)",
                "severity": "high"
            }
        ]
    }
    """
```

**Test independently:** (no dependency on Person 1)
```bash
python -c "from src.knowledge_graph.query import query_graph; print(query_graph('Who are Apple board members?'))"
```

---

## Person 3 — Backend API + Enterprise Features

**Branch:** `feature/enterprise-backend`
**Folder:** `api/`

**What you build:**
A FastAPI server that wraps Person 1's pipeline and adds auth, logging, and notifications.

**API Endpoints:**
| Method | URL | What it does | Who can use |
|--------|-----|-------------|-------------|
| POST | `/api/auth/login` | Login, get JWT token | Everyone |
| POST | `/api/query` | Ask a question, get answer | analyst, admin |
| GET | `/api/documents` | List ingested data | analyst, admin |
| POST | `/api/documents/ingest` | Trigger data ingestion | admin |
| GET | `/api/admin/stats` | System statistics | admin |

**3 User Roles:** viewer (read only), analyst (query + view), admin (everything)

**Files to create:**
```
api/
├── main.py              # FastAPI app
├── routes/
│   ├── auth.py          # Login/register endpoints
│   ├── query.py         # POST /api/query
│   ├── documents.py     # Document management
│   └── admin.py         # Admin stats
├── auth.py              # JWT token creation/verification
├── audit.py             # Log every query to SQLite
├── logging_config.py    # JSON structured logs
├── notifications.py     # Slack webhook
└── observability.py     # LangFuse LLM tracing
```

**The main query endpoint:**
```python
# POST /api/query
# Request:
{"question": "What was Apple's revenue in 2024?"}

# Response:
{
    "query_id": "abc-123",
    "answer": "Apple's total revenue in FY2024 was $391.0 billion...",
    "citations": [{"company": "Apple", "filing": "10-K", "date": "2024-11-01"}],
    "route": "xbrl_financial",
    "confidence": 0.92,
    "latency_ms": 2340
}
```

**Until Person 1 delivers the pipeline, use this mock:**
```python
class MockPipeline:
    def query(self, question, filters=None):
        return {
            "answer": f"Mock answer for: {question}",
            "citations": [{"company": "Apple", "filing": "10-K", "date": "2024-11-01"}],
            "route": "sec_filing",
            "confidence": 0.85
        }
```

**Test independently:**
```bash
uvicorn api.main:app --reload
# Then: curl -X POST http://localhost:8000/api/auth/login -d '{"username":"admin","password":"admin123"}'
```

---

## Person 4 — Frontend + Evaluation

**Branch:** `feature/frontend-eval`
**Folders:** `frontend/` and `evaluation/`

### Frontend (Next.js)

**5 Pages to build:**
| Page | What it shows |
|------|--------------|
| `/` (Chat) | Chat box → type question → see answer with citations |
| `/documents` | List of ingested companies and data sources |
| `/knowledge-graph` | Interactive graph visualization (use cytoscape.js) |
| `/evaluation` | Charts showing eval metrics per tier |
| `/admin` | User management, system stats |

**Files to create:**
```
frontend/
├── app/
│   ├── page.tsx              # Chat UI
│   ├── documents/page.tsx
│   ├── knowledge-graph/page.tsx
│   ├── evaluation/page.tsx
│   └── admin/page.tsx
├── components/
│   ├── ChatBox.tsx
│   ├── CitationCard.tsx
│   └── GraphViewer.tsx
└── lib/
    ├── api.ts                # Calls Person 3's API
    └── mockData.ts           # Mock responses for development
```

**Until Person 3's API is ready, use mock data:**
```typescript
// lib/mockData.ts
export const mockAnswer = {
    answer: "Apple's revenue in FY2024 was $391.0 billion...",
    citations: [{company: "Apple", filing: "10-K", date: "2024-11-01"}],
    route: "xbrl_financial",
    confidence: 0.92
};
```

### Evaluation (Python)

**What you do:**
1. Run all 30 eval queries (from the project spec) through the pipeline
2. Measure: faithfulness, citation accuracy, latency
3. Design a custom "Due Diligence Confidence Score"
4. Run ablation study (disable components one at a time, measure impact)
5. Write a report with charts

**Files to create:**
```
evaluation/
├── queries.json          # All 30 queries (copy from project spec)
├── eval_runner.py        # Run queries, collect results
├── metrics.py            # Calculate RAGAS metrics
├── confidence_score.py   # Custom scoring formula
├── ablation.py           # Ablation study
└── report.md             # Final report with charts
```

**Custom Score Formula (simple version):**
```
Score = 0.30 × (numbers correct?)
      + 0.25 × (citations point to real filings?)
      + 0.20 × (answer based on retrieved docs?)
      + 0.15 × (found contradictions?)
      + 0.10 × (covered all risk factors?)
```

**Also:** Create `Dockerfile`, `docker-compose.yml`, deploy to Vercel + Railway.

---

## Day-by-Day Plan

### Day 1-2: Build Your Module Alone (No Dependencies)

Everyone works independently using mock data. No one waits for anyone.

| Person | Day 1 | Day 2 |
|--------|-------|-------|
| P1 | Set up `src/`. Build router (question → route). Build Pinecone retriever. | Build XBRL query node. Build LLM answer generator. Wire it all together. |
| P2 | Install Neo4j. Extract entities from proxy + edgar JSON files. | Load entities into Neo4j. Build contradiction detector. |
| P3 | Set up FastAPI. Build login + JWT auth. Build `/api/query` with mock pipeline. | Build audit logging. Build Slack notifications. Add structured logging. |
| P4 | Set up Next.js. Build Chat page + Login page with mock data. | Build remaining 3 pages. Set up RAGAS eval framework. |

### Day 3: Finish + Test Your Module

| Person | Tasks |
|--------|-------|
| P1 | Test pipeline end-to-end. All 5 routes working. Answer Tier 1 queries. |
| P2 | Neo4j populated for all 12 companies. NL-to-Cypher working. Contradiction detector tested. |
| P3 | All API endpoints working (with mock pipeline). Auth + RBAC tested. LangFuse integrated. |
| P4 | All 5 frontend pages working (with mock data). Eval runner tested with mock pipeline. |

### Day 4-5: Connect Everything

| Step | Who | What |
|------|-----|------|
| 1 | P1 + P2 | P1 plugs in P2's KG engine + contradiction detector (replace mocks) |
| 2 | P1 + P3 | P3 replaces mock pipeline with P1's real RAGPipeline |
| 3 | P3 + P4 | P4 points frontend to P3's real API (replace mock data) |
| 4 | P4 | Run all 30 eval queries through the real system |

### Day 6: Deploy + Eval Report

| Person | Tasks |
|--------|-------|
| P1 | Fix pipeline bugs. Help with deployment. |
| P2 | Fix KG bugs. Help with deployment. |
| P3 | Deploy backend (Railway). Docker setup. |
| P4 | Deploy frontend (Vercel). Write eval report. Run ablation study. |

### Day 7: Final Test + Demo

| Everyone | Full system test. Fix critical bugs. Record demo. Merge to main. |
|----------|--------------------------------------------------------------|

---

## Git Rules (Keep It Simple)

```
main  ← protected, never push directly
  ├── feature/rag-pipeline        ← Person 1
  ├── feature/knowledge-graph     ← Person 2
  ├── feature/enterprise-backend  ← Person 3
  └── feature/frontend-eval       ← Person 4
```

1. Work on your branch only
2. Push daily
3. Create PR when your module works
4. Merge order: P1 → P2 → P3 → P4
5. Before merging: `git pull --rebase origin main`

---

## Shared Contract (Everyone Uses This)

Create `src/contracts.py` on Day 1. Everyone imports from here:

```python
# src/contracts.py
from dataclasses import dataclass, field

@dataclass
class QueryRequest:
    question: str
    filters: dict = field(default_factory=dict)

@dataclass
class QueryResponse:
    answer: str
    citations: list
    route: str
    confidence: float
    latency_ms: int = 0
    query_id: str = ""
```

This is the glue. Person 1 returns it, Person 3 wraps it in API, Person 4 displays it.

---

## What to Install (Add to requirements.txt)

```
# Person 1
langgraph>=0.2.0
langchain-openai>=0.2.0

# Person 2
neo4j>=5.0.0

# Person 3
fastapi>=0.115.0
uvicorn>=0.30.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
langfuse>=2.0.0

# Person 4
ragas>=0.2.0
matplotlib>=3.8.0
```

Frontend (separate): `npx create-next-app frontend`

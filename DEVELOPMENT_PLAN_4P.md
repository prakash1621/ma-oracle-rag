# M&A Oracle — 4-Person Plan (1 Week, RAG-Focused)

**Deadline:** Sunday, 19 April 2026
**What's done:** Data ingestion (6 sources → Pinecone + SQLite). NL2SQL microservice.
**Focus:** Build the core RAG system — pipeline, routing, KG, contradiction detection.

---

## Who Does What

```
Person 1 → RAG Router + Agentic Pipeline   (question comes in, decides where to send it)
Person 2 → Retrieval Nodes                 (actually fetches data from Pinecone/SQLite)
Person 3 → Knowledge Graph (Neo4j)         (entity relationships + graph queries)
Person 4 → Contradiction Detection          (cross-source analysis)
```

---

## How It Connects

```
User question
      ↓
  [Router]  ←── Person 1
      ↓ (picks a route)
      ├── sec_filing ──────→ [Pinecone Retriever]  ←── Person 2
      ├── xbrl_financial ──→ [XBRL NL-to-SQL]      ←── Person 2
      ├── transcript ──────→ [Pinecone Retriever]   ←── Person 2
      ├── patent ──────────→ [Pinecone + SQLite]    ←── Person 2
      ├── proxy ───────────→ [Pinecone Retriever]   ←── Person 2
      ├── knowledge_graph ─→ [Neo4j Query]          ←── Person 3
      └── contradiction ───→ [Cross-Source Compare]  ←── Person 4
      ↓
  [LLM Generator]  ←── Person 1 (takes retrieved chunks → generates answer + citations)
      ↓
  Answer + Citations
```

---

## Person 1 — Router + Agentic Pipeline + Answer Generator

**Branch:** `feature/rag-pipeline`
**Folder:** `src/`
**Status:** DONE — `src/contracts.py`, `src/pipeline.py`, `src/mocks.py` created.

**What you build:**
1. `RAGPipeline.query(question)` — the single entry point
2. Router — LLM classifies question into a route
3. LangGraph state machine — orchestrates the flow
4. Answer generator — takes retrieved chunks, generates answer with citations
5. Multi-hop logic — for complex queries that need multiple routes

**Files:**
```
src/
├── pipeline.py       # RAGPipeline class (main entry point) ✅
├── mocks.py          # Mock functions for Person 2/3/4 ✅
├── contracts.py      # Shared data classes (everyone imports this) ✅
├── router.py         # LLM classifies question → route name (inline in pipeline.py)
├── graph.py          # LangGraph state machine wiring (optional refactor)
├── state.py          # State definition for LangGraph (optional refactor)
├── generator.py      # LLM answer generation + citation extraction (inline in pipeline.py)
└── config.py         # Load config.yaml (optional refactor)
```

**Your main class:**
```python
class RAGPipeline:
    def query(self, question: str, filters: dict = None) -> QueryResponse:
        # 1. Router decides route
        # 2. Call the right retrieval node (Person 2's code)
        # 3. If route is "knowledge_graph", call Person 3's code
        # 4. If route is "contradiction", call Person 4's code
        # 5. Pass retrieved chunks to generator
        # 6. Return answer + citations
```

**You call other people's code through simple interfaces:**
```python
# Person 2 gives you these functions:
retrieve_from_pinecone(query, category, top_k) → list[dict]
query_xbrl(question) → dict
query_patents(question, ticker) → list[dict]

# Person 3 gives you this function:
query_knowledge_graph(question, tickers) → dict

# Person 4 gives you this function:
detect_contradictions(ticker) → dict
```

**Auto-detection:** The pipeline automatically detects whether Person 2/3/4's real modules exist. If they do, it uses them. If not, it falls back to mocks. No manual switching needed.

**Test:**
```bash
python -c "from src.pipeline import RAGPipeline; p = RAGPipeline(); print(p.query('What was Apple revenue in 2024?'))"
```

---

## Person 2 — Retrieval Nodes (Pinecone + XBRL + Patents)

**Branch:** `feature/retrieval-nodes`
**Folder:** `src/retrieval/`

**You build all the data-fetching functions.** When Person 1's router decides "this is a financial question", your code runs to get the data.

**What you build:**
1. Pinecone vector search — search by category (sec_filing, transcript, proxy, patent)
2. XBRL NL-to-SQL — convert financial questions to SQL, query SQLite
3. Patent SQL queries — search patent SQLite database
4. Reranking — reorder retrieved chunks by relevance

**Files:**
```
src/retrieval/
├── __init__.py
├── pinecone_retriever.py   # Search Pinecone with metadata filters
├── xbrl_query.py           # NL-to-SQL for financial data (wrap existing NL2SQL)
├── patent_query.py         # SQL queries against patents.db
└── reranker.py             # LLM-based reranking of retrieved chunks
```

**The functions Person 1 will call:**
```python
# src/retrieval/pinecone_retriever.py
def retrieve_from_pinecone(query: str, category: str, top_k: int = 5, ticker: str = None) -> list[dict]:
    """
    Input:  query="Apple risk factors", category="sec_filing", top_k=5
    Output: [
        {"text": "Item 1A Risk Factors: The Company...", "metadata": {...}, "score": 0.92},
        {"text": "Customer concentration risk...", "metadata": {...}, "score": 0.87},
    ]
    """

# src/retrieval/xbrl_query.py
def query_xbrl(question: str) -> dict:
    """
    Input:  "What was Apple's total revenue in fiscal year 2024?"
    Output: {
        "sql": "SELECT ... FROM financial_facts ...",
        "results": [{"entity_name": "Apple Inc.", "value": 391035000000, "label": "Revenue"}],
        "columns": ["entity_name", "value", "label"]
    }
    """

# src/retrieval/patent_query.py
def query_patents(question: str, ticker: str = None) -> list[dict]:
    """
    Input:  "How many patents does NVIDIA have?", ticker="NVDA"
    Output: [{"patent_id": "US11893789", "title": "GPU transformer inference", ...}]
    """
```

**No dependency on anyone.** You just need:
- Pinecone API key (already in `.env`)
- `output/xbrl/financials.db` (already generated by ingestion)
- `output/patents/patents.db` (already generated by ingestion)

**Test:**
```bash
python -c "from src.retrieval.pinecone_retriever import retrieve_from_pinecone; print(retrieve_from_pinecone('Apple risk factors', 'sec_filing'))"
python -c "from src.retrieval.xbrl_query import query_xbrl; print(query_xbrl('Apple revenue 2024'))"
python -c "from src.retrieval.patent_query import query_patents; print(query_patents('GPU patents', ticker='NVDA'))"
```

---

## Person 3 — Knowledge Graph (Neo4j)

**Branch:** `feature/knowledge-graph`
**Folder:** `src/knowledge_graph/`

**You build the entity relationship layer.** Companies, board members, patents, subsidiaries — all connected in a graph.

**What you build:**
1. Neo4j setup + schema (nodes and relationships)
2. Entity extraction — read existing JSON chunks, use LLM to pull out entities
3. Graph population — load extracted entities into Neo4j
4. NL-to-Cypher — convert natural language questions to Cypher queries
5. Graph data export — return data in a format the frontend can visualize later

**Files:**
```
src/knowledge_graph/
├── __init__.py
├── schema.py          # Define node types + relationship types
├── extractor.py       # LLM extracts entities from chunk JSON files
├── builder.py         # Load entities into Neo4j
├── query.py           # NL → Cypher → results
└── export.py          # Export graph data as JSON (nodes + edges)
```

**Graph Schema (keep it simple):**
```
(:Company {name, ticker, cik})
(:BoardMember {name, title})
(:Patent {patent_id, title, date})
(:RiskFactor {text, category})

(:Company)-[:HAS_BOARD_MEMBER]->(:BoardMember)
(:Company)-[:OWNS_PATENT]->(:Patent)
(:Company)-[:HAS_RISK]->(:RiskFactor)
(:BoardMember)-[:ALSO_SERVES_AT]->(:Company)
```

**The function Person 1 will call:**
```python
# src/knowledge_graph/query.py
def query_knowledge_graph(question: str, tickers: list = None) -> dict:
    """
    Input:  "Who are Apple's board members?"
    Output: {
        "cypher": "MATCH (c:Company {ticker:'AAPL'})-[:HAS_BOARD_MEMBER]->(b) RETURN b.name, b.title",
        "results": [{"name": "Tim Cook", "title": "CEO"}, {"name": "Jeff Williams", "title": "COO"}],
        "graph_data": {"nodes": [...], "edges": [...]}
    }
    """
```

**No dependency on anyone.** You read from:
- `output/proxy/chunked_documents.json` (board members, compensation)
- `output/edgar/chunked_documents.json` (risk factors, subsidiaries)
- `output/patents/chunked_documents.json` (patent data)

**Setup:**
1. Install Neo4j Desktop (free) or sign up for Neo4j Aura (free cloud)
2. `pip install neo4j`
3. Add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` to `.env`

**Test:**
```bash
python -c "from src.knowledge_graph.builder import build_graph; build_graph(['AAPL'])"
python -c "from src.knowledge_graph.query import query_knowledge_graph; print(query_knowledge_graph('Who are Apple board members?'))"
```

---

## Person 4 — Contradiction Detection

**Branch:** `feature/contradiction`
**Folder:** `src/contradiction/`

**You build the "insight" layer.** The most valuable part of due diligence is finding where management says one thing but filings say another.

**What you build:**
1. Claim extractor — pull claims from earnings transcript chunks
2. Fact extractor — pull facts from 10-K filing chunks
3. Contradiction comparator — LLM compares claims vs facts, flags mismatches

**Files:**
```
src/contradiction/
├── __init__.py
├── claim_extractor.py    # Extract claims from transcript chunks
├── fact_extractor.py     # Extract facts from 10-K chunks
├── comparator.py         # LLM compares claims vs facts
└── detector.py           # Main function: detect_contradictions(ticker)
```

**How contradiction detection works:**
```
Step 1: Read transcript chunks for AAPL
        → Extract claims: ["CEO says strong pipeline", "Revenue growth accelerating"]

Step 2: Read 10-K chunks for AAPL
        → Extract facts: ["Item 1A: customer concentration risk", "Item 7: revenue declined 2%"]

Step 3: LLM compares each claim against relevant facts
        → Flag: "CEO says strong pipeline" vs "customer concentration risk" = HIGH contradiction
```

**The function Person 1 will call:**
```python
# src/contradiction/detector.py
def detect_contradictions(ticker: str) -> dict:
    """
    Input:  "AAPL"
    Output: {
        "contradictions": [
            {
                "claim": "CEO: We see strong pipeline growth (Q3 2024 earnings call)",
                "fact": "Item 1A: Significant customer concentration risk (10-K 2024)",
                "severity": "high",
                "explanation": "Management projects growth while filing discloses concentration risk"
            }
        ],
        "summary": "Found 3 contradictions for Apple (2 high, 1 medium)"
    }
    """
```

**No dependency on anyone.** You read from:
- `output/transcripts/chunked_documents.json` (earnings call text)
- `output/edgar/chunked_documents.json` (10-K filing text)

**Test:**
```bash
python -c "from src.contradiction.detector import detect_contradictions; print(detect_contradictions('AAPL'))"
```

---

## Shared Contract (already created)

```python
# src/contracts.py — Everyone imports from here
from dataclasses import dataclass, field

@dataclass
class QueryRequest:
    question: str
    filters: dict = field(default_factory=dict)

@dataclass
class Citation:
    company_name: str
    filing_type: str
    filing_date: str
    item_number: str = ""
    source_text: str = ""
    relevance_score: float = 0.0

@dataclass
class QueryResponse:
    answer: str
    citations: list       # list of Citation
    route: str            # which route was used
    confidence: float
    sources: list = field(default_factory=list)  # raw retrieved chunks
```

---

## Day-by-Day Plan

### Day 1-2: Build Alone (Everyone Independent)

| Person | Day 1 | Day 2 |
|--------|-------|-------|
| P1 | Create `src/` skeleton + `contracts.py`. Build router. Set up pipeline. | Build answer generator. Wire router + generator together. |
| P2 | Build Pinecone retriever with category filters. Test search across all 4 chunk types. | Build XBRL NL-to-SQL. Build patent SQL query. Build reranker. |
| P3 | Install Neo4j. Define schema. Start extracting entities from proxy + edgar chunks. | Load entities into Neo4j for all 12 companies. Build NL-to-Cypher. |
| P4 | Build claim extractor from transcript chunks. Build fact extractor from 10-K chunks. | Build LLM comparator. |

### Day 3: Finish + Test Your Module

| Person | What should work |
|--------|-----------------|
| P1 | `RAGPipeline.query()` works end-to-end with mock retrieval. Router correctly classifies 10+ test questions. |
| P2 | All retrieval functions work. Pinecone returns relevant chunks. XBRL returns correct numbers. |
| P3 | Neo4j has entities for all 12 companies. `query_knowledge_graph()` answers graph questions. |
| P4 | `detect_contradictions("AAPL")` returns real contradictions. |

### Day 4: Connect Everything

| Step | Who | What |
|------|-----|------|
| 1 | P1 + P2 | P2 merges branch. Pipeline auto-detects real retrieval functions. |
| 2 | P1 + P3 | P3 merges branch. Pipeline auto-detects real `query_knowledge_graph()`. |
| 3 | P1 + P4 | P4 merges branch. Pipeline auto-detects real `detect_contradictions()`. |
| 4 | ALL | Test 10 queries across all routes. |

### Day 5: Test All 30 Eval Queries

| Person | Tasks |
|--------|-------|
| P1 | Run Tier 1 (7 basic queries) + Tier 4 (7 agentic queries). Fix routing issues. |
| P2 | Run Tier 2 (8 version/specificity queries). Fix retrieval quality. Tune reranking. |
| P3 | Run KG-related queries from Tier 3. Fix Cypher generation. Add missing entities. |
| P4 | Run contradiction-related queries from Tier 3. Fix detection quality. |

### Day 6-7: Polish + Document

| Person | Tasks |
|--------|-------|
| ALL | Fix bugs. Improve answer quality. Write documentation. Final merge to main. |

---

## Git Rules

```
main  ← protected
  ├── feature/rag-pipeline          ← Person 1
  ├── feature/retrieval-nodes       ← Person 2
  ├── feature/knowledge-graph       ← Person 3
  └── feature/contradiction         ← Person 4
```

Merge order: P2 → P3 → P4 → P1 (P1 merges last since they import everyone else's code)

---

## What to Install

```
# Person 1 (already installed via requirements.txt)
langgraph>=0.2.0
langchain-openai>=0.2.0
langchain-core>=0.3.0
openai>=1.0.0             # used for Groq (OpenAI-compatible API)

# Person 2
pinecone-client>=3.0.0    # already installed
openai>=1.0.0             # for reranker LLM calls via Groq

# Person 3
neo4j>=5.0.0
openai>=1.0.0             # for NL-to-Cypher via Groq

# Person 4
openai>=1.0.0             # for claim/fact extraction via Groq
```

**LLM Config:** All LLM calls use Groq (`llama-3.3-70b-versatile`) via the OpenAI-compatible API. Config is in `config.yaml` under `nl2sql` section. API key is `GROQ_API_KEY` in `.env`.

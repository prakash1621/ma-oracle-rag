# M&A Oracle — 4-Person Development Plan (1-Week Sprint)

**Deadline:** Sunday, 19 April 2026 — 11:59 PM IST
**Team Size:** 4 engineers
**Current State:** Data ingestion pipeline complete (6 sources + Pinecone indexing). NL2SQL microservice built. No RAG pipeline, no agentic layer, no frontend, no enterprise features.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                          │
│  Chat UI │ Doc Mgmt │ KG Viewer │ Eval Dashboard │ Admin Panel     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ REST + SSE
┌────────────────────────────▼────────────────────────────────────────┐
│                     API GATEWAY (FastAPI)                           │
│  Auth (JWT/RBAC) │ Audit Trail │ Structured Logging │ Observability│
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                   AGENTIC RAG PIPELINE (LangGraph)                 │
│                                                                     │
│  ┌──────────┐   ┌──────────────┐   ┌────────────┐   ┌───────────┐ │
│  │  Router   │──▶│  Retrieval   │──▶│  Reasoning │──▶│  Response  │ │
│  │  (LLM)   │   │  (4+ routes) │   │  (LLM)     │   │  + Cite    │ │
│  └──────────┘   └──────────────┘   └────────────┘   └───────────┘ │
│       │              │                    │                         │
│       ▼              ▼                    ▼                         │
│  ┌─────────┐  ┌───────────┐  ┌──────────────────┐                 │
│  │ Contra-  │  │ Knowledge │  │ XBRL NL-to-SQL   │                 │
│  │ diction  │  │ Graph     │  │ (existing module) │                 │
│  │ Detector │  │ (Neo4j)   │  └──────────────────┘                 │
│  └─────────┘  └───────────┘                                        │
└─────────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                    DATA LAYER (Already Built)                       │
│  Pinecone (vectors) │ SQLite (XBRL+Patents) │ JSON (chunks)        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module Division (4 Engineers)

### Module A — Agentic RAG Pipeline & Router (Person 1: Prakash)
### Module B — Knowledge Graph & Contradiction Detection (Person 2)
### Module C — Enterprise Backend API & Infrastructure (Person 3)
### Module D — Frontend & Evaluation Framework (Person 4)

---

## MODULE A — Agentic RAG Pipeline & Router

**Owner:** Person 1 (Prakash)
**Branch:** `feature/rag-pipeline`
**Complexity:** High (core system backbone)

### Responsibilities
- Build the LangGraph-based agentic pipeline (the "brain" of the system)
- Implement the RAG router that classifies queries into 5+ routes
- Build retrieval nodes for each route (Pinecone vector search, XBRL SQL, patent SQL)
- Implement the response generation node with citation tracking
- Wire in the existing NL2SQL module as the XBRL route

### Directory Structure
```
src/
├── __init__.py
├── pipeline.py              # RAGPipeline class — main entry point
├── config.py                # Shared config loader
├── agentic/
│   ├── __init__.py
│   ├── state.py             # LangGraph state definition
│   ├── graph.py             # LangGraph graph builder
│   ├── nodes.py             # All node functions (router, retriever, generator)
│   ├── router.py            # Query classification logic
│   ├── retriever.py         # Pinecone retrieval + reranking
│   ├── xbrl_node.py         # XBRL NL-to-SQL node (wraps existing NL2SQL)
│   └── generator.py         # LLM response generation with citations
└── providers.py             # LLM + embedding factory (extend existing)
```

### Input/Output Contract

**RAGPipeline.query() — Main Entry Point:**
```python
# Input
@dataclass
class QueryRequest:
    question: str
    tenant_id: str = "default"
    user_id: str = "anonymous"
    filters: dict = field(default_factory=dict)  # e.g., {"ticker": "AAPL", "filing_type": "10-K"}

# Output
@dataclass
class QueryResponse:
    answer: str
    citations: list[Citation]
    route_taken: str                # "sec_filing" | "xbrl_financial" | "transcript" | "patent" | "proxy" | "knowledge_graph"
    confidence_score: float
    sources_retrieved: list[dict]   # Raw retrieved chunks with scores
    tokens_used: int
    latency_ms: int
    query_id: str                   # UUID for audit trail

@dataclass
class Citation:
    company_name: str
    filing_type: str
    filing_date: str
    item_number: str
    item_title: str
    source_text: str                # Relevant excerpt
    relevance_score: float
```

### Router Routes (minimum 5)
| Route | Trigger Keywords | Retrieval Strategy |
|-------|-----------------|-------------------|
| `sec_filing` | risk factors, MD&A, business description, 10-K, 10-Q | Pinecone vector search with `category=sec_filing` filter |
| `xbrl_financial` | revenue, income, assets, financial metrics, ratios | NL-to-SQL against XBRL SQLite DB |
| `transcript` | earnings call, CEO said, management guidance, sentiment | Pinecone vector search with `category=earnings_transcript` filter |
| `patent` | patent, IP, technology, claims, assignee | Pinecone + SQLite patent DB |
| `proxy` | board members, compensation, related-party, governance | Pinecone vector search with `category=proxy_statement` filter |
| `knowledge_graph` | relationships, connections, subsidiaries, board overlap | Neo4j Cypher query (depends on Module B) |
| `contradiction` | contradicts, inconsistent, says vs filed, discrepancy | Cross-source comparison (depends on Module B) |
| `multi_hop` | due diligence, full analysis, compare companies | Agentic multi-step (chains multiple routes) |

### Mock/Stub Strategy for Independent Development
```python
# Person 1 can mock the KG and contradiction nodes until Person 2 delivers them
class MockKnowledgeGraphNode:
    def query(self, cypher: str) -> list[dict]:
        return [{"entity": "Apple Inc.", "relationship": "has_subsidiary", "target": "Beats Electronics"}]

class MockContradictionNode:
    def detect(self, company: str) -> list[dict]:
        return [{"claim": "CEO: strong pipeline", "filing": "Item 1A: customer concentration risk", "severity": "high"}]
```

### Tech Stack
- `langgraph>=0.2.0` — State machine for agentic pipeline
- `langchain-core>=0.3.0` — Base abstractions
- `langchain-openai>=0.2.0` — OpenAI LLM provider
- `pinecone-client>=3.0.0` — Vector retrieval (already installed)
- `langchain-pinecone>=0.1.0` — LangChain Pinecone integration

### Unit Testing Strategy
```python
# tests/test_router.py — Test query classification
def test_router_classifies_financial_query():
    router = QueryRouter(llm=MockLLM())
    route = router.classify("What was Apple's revenue in 2024?")
    assert route == "xbrl_financial"

def test_router_classifies_risk_query():
    router = QueryRouter(llm=MockLLM())
    route = router.classify("What are Tesla's risk factors?")
    assert route == "sec_filing"

# tests/test_retriever.py — Test Pinecone retrieval
def test_retriever_returns_relevant_chunks():
    retriever = PineconeRetriever(index=mock_pinecone_index)
    results = retriever.search("Apple revenue", top_k=5, filter={"category": "sec_filing"})
    assert len(results) <= 5
    assert all("text" in r and "score" in r for r in results)

# tests/test_pipeline.py — End-to-end with mocks
def test_pipeline_tier1_query():
    pipeline = RAGPipeline(config=test_config, kg_node=MockKGNode(), contradiction_node=MockContradictionNode())
    response = pipeline.query(QueryRequest(question="What was Apple's total revenue in fiscal year 2024?"))
    assert response.route_taken == "xbrl_financial"
    assert response.answer  # Non-empty
    assert response.confidence_score > 0
```

### Deliverables
1. `src/pipeline.py` — Working RAGPipeline class with `.query()` method
2. `src/agentic/` — Complete LangGraph pipeline with router + 5 retrieval routes
3. `tests/test_pipeline.py` — Unit tests for router, retriever, generator
4. All Tier 1 eval queries answerable end-to-end

---

## MODULE B — Knowledge Graph & Contradiction Detection

**Owner:** Person 2
**Branch:** `feature/knowledge-graph`
**Complexity:** High (novel components, entity extraction)

### Responsibilities
- Set up Neo4j and define the knowledge graph schema
- Build entity extraction pipeline (LLM-based) from 10-K filings + proxy statements
- Implement NL-to-Cypher query generation for graph queries
- Build contradiction detection engine (earnings call vs. 10-K comparison)
- Integrate 2 additional data sources (CourtListener litigation + News API)

### Directory Structure
```
src/
├── knowledge_graph/
│   ├── __init__.py
│   ├── schema.py            # Neo4j schema definition (nodes, relationships)
│   ├── entity_extractor.py  # LLM-based entity extraction from filings
│   ├── graph_builder.py     # Populate Neo4j from extracted entities
│   ├── query_engine.py      # NL-to-Cypher query generation
│   └── visualizer.py        # Export graph data for frontend visualization
├── contradiction/
│   ├── __init__.py
│   ├── claim_extractor.py   # Extract claims from transcripts
│   ├── fact_extractor.py    # Extract facts from 10-K filings
│   ├── comparator.py        # LLM-based contradiction detection
│   └── detector.py          # Main ContradictionDetector class
└── additional_sources/
    ├── __init__.py
    ├── courtlistener.py     # CourtListener/RECAP litigation data
    └── news_api.py          # News API for sentiment/event correlation
```

### Input/Output Contracts

**KnowledgeGraphEngine — Called by Module A's pipeline:**
```python
# Input
@dataclass
class GraphQueryRequest:
    question: str
    company_tickers: list[str] = field(default_factory=list)

# Output
@dataclass
class GraphQueryResponse:
    cypher_query: str
    results: list[dict]          # Raw Neo4j results
    entities: list[GraphEntity]
    relationships: list[GraphRelationship]
    visualization_data: dict     # JSON for frontend graph rendering

@dataclass
class GraphEntity:
    id: str
    label: str                   # "Company", "BoardMember", "Patent", "RiskFactor"
    properties: dict

@dataclass
class GraphRelationship:
    source_id: str
    target_id: str
    type: str                    # "HAS_BOARD_MEMBER", "FILED", "OWNS_PATENT"
    properties: dict
```

**ContradictionDetector — Called by Module A's pipeline:**
```python
# Input
@dataclass
class ContradictionRequest:
    company_ticker: str
    time_range: str = "last_2_years"

# Output
@dataclass
class ContradictionResponse:
    contradictions: list[Contradiction]
    summary: str

@dataclass
class Contradiction:
    claim_source: str            # "Earnings Call Q3 2024"
    claim_text: str              # "CEO: We see strong pipeline growth"
    filing_source: str           # "10-K 2024 Item 1A"
    filing_text: str             # "Significant customer concentration risk"
    severity: str                # "high" | "medium" | "low"
    explanation: str             # LLM-generated explanation of the contradiction
```

### Neo4j Graph Schema
```
(:Company {cik, name, ticker, sic, state})
(:BoardMember {name, title, tenure_start})
(:Executive {name, title, compensation_total})
(:Patent {patent_id, title, date, cpc_codes})
(:Filing {accession_number, type, date, period})
(:RiskFactor {text_hash, category, first_appeared})
(:Subsidiary {name, jurisdiction})
(:Litigation {case_id, court, status, amount})

(:Company)-[:HAS_BOARD_MEMBER]->(:BoardMember)
(:Company)-[:HAS_EXECUTIVE]->(:Executive)
(:Company)-[:OWNS_PATENT]->(:Patent)
(:Company)-[:FILED]->(:Filing)
(:Filing)-[:CONTAINS_RISK]->(:RiskFactor)
(:Company)-[:HAS_SUBSIDIARY]->(:Subsidiary)
(:Company)-[:INVOLVED_IN]->(:Litigation)
(:BoardMember)-[:ALSO_SERVES_AT]->(:Company)
(:Patent)-[:CITES]->(:Patent)
```

### Mock/Stub Strategy
```python
# Person 2 can work independently using the existing chunked JSON files
# No dependency on Module A — just reads from output/ directory and Neo4j

# Mock for Module A to use before KG is ready:
class MockKnowledgeGraphEngine:
    def query(self, request: GraphQueryRequest) -> GraphQueryResponse:
        return GraphQueryResponse(
            cypher_query="MATCH (c:Company {ticker:'AAPL'})-[:HAS_BOARD_MEMBER]->(b) RETURN b",
            results=[{"name": "Tim Cook", "title": "CEO"}],
            entities=[], relationships=[], visualization_data={}
        )

# Mock for Module A to use before contradiction detection is ready:
class MockContradictionDetector:
    def detect(self, request: ContradictionRequest) -> ContradictionResponse:
        return ContradictionResponse(contradictions=[], summary="No contradictions found (mock)")
```

### Tech Stack
- `neo4j>=5.0.0` — Neo4j Python driver
- `py2neo>=2021.2.0` — Higher-level Neo4j ORM (optional)
- `langchain-openai>=0.2.0` — LLM for entity extraction + NL-to-Cypher
- `courtlistener` — CourtListener API client (or raw requests)
- `newsapi-python>=0.2.7` — News API client

### Unit Testing Strategy
```python
# tests/test_entity_extractor.py
def test_extracts_board_members_from_proxy():
    extractor = EntityExtractor(llm=MockLLM())
    with open("output/proxy/chunked_documents.json") as f:
        chunks = json.load(f)[:5]
    entities = extractor.extract_from_proxy(chunks)
    assert any(e.label == "BoardMember" for e in entities)

# tests/test_contradiction.py
def test_detects_contradiction():
    detector = ContradictionDetector(llm=MockLLM())
    claim = "CEO says strong pipeline growth"
    filing = "Item 1A discloses significant customer concentration risk"
    result = detector.compare(claim, filing)
    assert result.severity in ("high", "medium", "low")

# tests/test_graph_query.py
def test_nl_to_cypher():
    engine = KnowledgeGraphEngine(llm=MockLLM(), driver=mock_neo4j)
    response = engine.query(GraphQueryRequest(question="Who are Apple's board members?"))
    assert "MATCH" in response.cypher_query
```

### Deliverables
1. `src/knowledge_graph/` — Working Neo4j integration with entity extraction
2. `src/contradiction/` — Contradiction detection engine
3. `src/additional_sources/` — 2 additional data sources integrated
4. `tests/` — Unit tests for all components
5. Neo4j populated with entities from all 12 companies

---

## MODULE C — Enterprise Backend API & Infrastructure

**Owner:** Person 3
**Branch:** `feature/enterprise-backend`
**Complexity:** Medium-High (many features, well-defined patterns)

### Responsibilities
- Build FastAPI REST API wrapping the RAG pipeline
- Implement JWT authentication with role-based access control (RBAC)
- Build multi-tenant architecture with data isolation
- Implement audit trail, structured logging, observability (LangFuse)
- Implement Slack/webhook notifications
- Docker + deployment setup

### Directory Structure
```
api/
├── __init__.py
├── main.py                  # FastAPI app entry point
├── routes/
│   ├── __init__.py
│   ├── query.py             # POST /api/query
│   ├── documents.py         # GET/POST /api/documents
│   ├── eval.py              # GET /api/eval
│   ├── admin.py             # GET /api/admin/stats
│   └── auth.py              # POST /api/auth/login, /api/auth/register
├── middleware/
│   ├── __init__.py
│   ├── auth.py              # JWT verification middleware
│   ├── tenant.py            # Tenant context middleware
│   ├── logging.py           # Correlation ID + structured logging
│   └── rate_limit.py        # Per-tenant rate limiting
├── models/
│   ├── __init__.py
│   ├── request.py           # Pydantic request models
│   ├── response.py          # Pydantic response models
│   └── db.py                # SQLAlchemy/SQLite models for users, audit
├── services/
│   ├── __init__.py
│   ├── auth_service.py      # JWT creation/validation, user management
│   ├── audit_service.py     # Query audit logging
│   ├── notification.py      # Slack webhook integration
│   └── observability.py     # LangFuse integration
├── config.py                # API configuration
└── deps.py                  # FastAPI dependency injection
```

### Input/Output Contracts (API Endpoints)

**POST /api/auth/login**
```json
// Request
{ "username": "analyst1", "password": "..." }
// Response
{ "access_token": "eyJ...", "token_type": "bearer", "role": "analyst", "tenant_id": "tenant-abc" }
```

**POST /api/query** (Core endpoint — wraps Module A's RAGPipeline)
```json
// Request (Authorization: Bearer <token>)
{
  "question": "What was Apple's total revenue in fiscal year 2024?",
  "filters": { "ticker": "AAPL" }
}
// Response
{
  "query_id": "uuid-123",
  "answer": "Apple's total revenue in fiscal year 2024 was $391.0 billion...",
  "citations": [
    {
      "company_name": "Apple Inc.",
      "filing_type": "10-K",
      "filing_date": "2024-11-01",
      "item_number": "8",
      "item_title": "Financial Statements",
      "source_text": "Net sales: $391,035 million...",
      "relevance_score": 0.95
    }
  ],
  "route_taken": "xbrl_financial",
  "confidence_score": 0.92,
  "tokens_used": 4521,
  "latency_ms": 2340
}
```

**GET /api/documents**
```json
// Response
{
  "documents": [
    { "source": "edgar", "company": "AAPL", "chunks": 1234, "last_ingested": "2026-04-10" },
    { "source": "xbrl", "company": "AAPL", "facts": 5678, "last_ingested": "2026-04-10" }
  ]
}
```

**POST /api/documents/ingest**
```json
// Request
{ "tickers": ["AAPL"], "sources": ["edgar", "xbrl"] }
// Response
{ "job_id": "uuid-456", "status": "started", "message": "Ingestion started for AAPL" }
```

**GET /api/admin/stats**
```json
// Response
{
  "total_queries": 1234,
  "total_documents": 23534,
  "active_tenants": 3,
  "avg_latency_ms": 2100,
  "total_tokens_used": 1500000,
  "routes_distribution": { "sec_filing": 45, "xbrl_financial": 30, "transcript": 15, "patent": 10 }
}
```

### RBAC Roles
| Role | /api/query | /api/documents | /api/documents/ingest | /api/eval | /api/admin/stats |
|------|-----------|---------------|----------------------|----------|-----------------|
| viewer | ✅ read | ✅ read | ❌ | ✅ read | ❌ |
| analyst | ✅ read | ✅ read | ✅ | ✅ read | ❌ |
| admin | ✅ read | ✅ read | ✅ | ✅ read/write | ✅ |

### Mock/Stub Strategy
```python
# Person 3 can mock the RAG pipeline until Module A delivers it
class MockRAGPipeline:
    def query(self, request: QueryRequest) -> QueryResponse:
        return QueryResponse(
            answer="Apple's total revenue in FY2024 was $391.0 billion.",
            citations=[Citation(company_name="Apple Inc.", filing_type="10-K", ...)],
            route_taken="xbrl_financial",
            confidence_score=0.92,
            sources_retrieved=[],
            tokens_used=1500,
            latency_ms=800,
            query_id=str(uuid4()),
        )

# This lets Person 3 build and test the entire API independently
```

### Tech Stack
- `fastapi>=0.115.0` — Web framework
- `uvicorn>=0.30.0` — ASGI server
- `python-jose[cryptography]>=3.3.0` — JWT tokens
- `passlib[bcrypt]>=1.7.4` — Password hashing
- `python-multipart>=0.0.9` — Form data parsing
- `langfuse>=2.0.0` — LLM observability
- `httpx>=0.27.0` — Slack webhook calls

### Unit Testing Strategy
```python
# tests/test_auth.py
def test_login_returns_jwt():
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_unauthorized_without_token():
    response = client.post("/api/query", json={"question": "test"})
    assert response.status_code == 401

def test_viewer_cannot_ingest():
    response = client.post("/api/documents/ingest", json={"tickers": ["AAPL"]}, headers=viewer_headers)
    assert response.status_code == 403

# tests/test_audit.py
def test_query_creates_audit_entry():
    client.post("/api/query", json={"question": "test"}, headers=analyst_headers)
    audits = audit_service.get_recent(limit=1)
    assert len(audits) == 1
    assert audits[0]["query"] == "test"

# tests/test_api_query.py (with mock pipeline)
def test_query_endpoint_returns_citations():
    response = client.post("/api/query", json={"question": "Apple revenue?"}, headers=analyst_headers)
    data = response.json()
    assert "answer" in data
    assert "citations" in data
    assert data["route_taken"] in VALID_ROUTES
```

### Deliverables
1. `api/` — Complete FastAPI application with all endpoints
2. JWT auth with 3 roles working
3. Audit trail logging every query to SQLite
4. LangFuse integration for LLM tracing
5. Slack webhook notifications
6. Structured JSON logging with correlation IDs
7. `Dockerfile` + `docker-compose.yml`
8. `tests/` — API endpoint tests

---

## MODULE D — Frontend & Evaluation Framework

**Owner:** Person 4
**Branch:** `feature/frontend-eval`
**Complexity:** Medium-High (breadth of work: UI + eval + deployment)

### Responsibilities
- Build React/Next.js frontend with 5 pages
- Implement evaluation framework (RAGAS/DeepEval) with 30 queries
- Design custom Due Diligence Confidence Score metric
- Run ablation study
- CI/CD pipeline + deployment

### Directory Structure
```
frontend/
├── package.json
├── next.config.js
├── app/
│   ├── layout.tsx
│   ├── page.tsx                 # Chat UI (default page)
│   ├── documents/page.tsx       # Document management
│   ├── knowledge-graph/page.tsx # KG visualization
│   ├── evaluation/page.tsx      # Eval dashboard
│   ├── admin/page.tsx           # Admin panel
│   └── login/page.tsx           # Login page
├── components/
│   ├── ChatInterface.tsx
│   ├── CitationCard.tsx
│   ├── GraphViewer.tsx          # Cytoscape.js wrapper
│   ├── EvalChart.tsx
│   └── Sidebar.tsx
├── lib/
│   ├── api.ts                   # API client (calls Module C endpoints)
│   ├── auth.ts                  # JWT token management
│   └── types.ts                 # TypeScript types matching API contracts
└── public/

evaluation/
├── __init__.py
├── eval_runner.py               # Run all 30 queries through pipeline
├── metrics.py                   # RAGAS + custom metrics
├── confidence_score.py          # Due Diligence Confidence Score
├── ablation.py                  # Ablation study runner
├── queries.json                 # All 30 eval queries (4 tiers)
├── results/
│   └── results.json             # Eval results
└── report.md                    # Final evaluation report
```

### Input/Output Contracts

**Frontend → API (TypeScript types matching Module C's API):**
```typescript
// lib/types.ts
interface QueryRequest {
  question: string;
  filters?: { ticker?: string; filing_type?: string };
}

interface QueryResponse {
  query_id: string;
  answer: string;
  citations: Citation[];
  route_taken: string;
  confidence_score: number;
  tokens_used: number;
  latency_ms: number;
}

interface Citation {
  company_name: string;
  filing_type: string;
  filing_date: string;
  item_number: string;
  item_title: string;
  source_text: string;
  relevance_score: number;
}

interface GraphData {
  nodes: { id: string; label: string; type: string; properties: Record<string, any> }[];
  edges: { source: string; target: string; type: string }[];
}

interface EvalResult {
  query: string;
  tier: number;
  answer: string;
  route_taken: string;
  latency_ms: number;
  context_precision: number;
  context_recall: number;
  faithfulness: number;
  answer_relevance: number;
  confidence_score: number;
}
```

**Evaluation Framework Output:**
```python
# evaluation/results.json structure
{
  "run_id": "eval-2026-04-15",
  "timestamp": "2026-04-15T10:00:00Z",
  "total_queries": 30,
  "metrics_summary": {
    "avg_context_precision": 0.82,
    "avg_faithfulness": 0.91,
    "avg_answer_relevance": 0.87,
    "avg_confidence_score": 0.78,
    "avg_latency_ms": 2100
  },
  "per_tier": {
    "tier_1": { "count": 7, "avg_faithfulness": 0.95, ... },
    "tier_2": { "count": 8, "avg_faithfulness": 0.88, ... },
    "tier_3": { "count": 8, "avg_faithfulness": 0.82, ... },
    "tier_4": { "count": 7, "avg_faithfulness": 0.72, ... }
  },
  "ablation": {
    "full_system": { ... },
    "without_router": { ... },
    "without_kg": { ... },
    "without_reranking": { ... },
    "without_xbrl": { ... },
    "without_contradiction": { ... }
  },
  "results": [ ... ]  // Per-query results
}
```

### Due Diligence Confidence Score Formula
```
DDCS = 0.30 × NumericalAccuracy
     + 0.25 × CitationAccuracy
     + 0.20 × Faithfulness
     + 0.15 × ContradictionDetectionRate
     + 0.10 × Completeness

Where:
- NumericalAccuracy: 1.0 if all numbers match source, 0.0 if any hallucinated
- CitationAccuracy: % of claims that trace to a specific filing + section + date
- Faithfulness: RAGAS faithfulness score (is answer grounded in retrieved docs?)
- ContradictionDetectionRate: % of known contradictions the system found
- Completeness: % of material risk factors surfaced vs. total in filing
```

### Mock/Stub Strategy
```typescript
// Frontend can be built entirely against mock API responses
// lib/mockApi.ts
export const mockQueryResponse: QueryResponse = {
  query_id: "mock-123",
  answer: "Apple's total revenue in FY2024 was $391.0 billion, representing a 2% increase...",
  citations: [{
    company_name: "Apple Inc.",
    filing_type: "10-K",
    filing_date: "2024-11-01",
    item_number: "8",
    item_title: "Financial Statements",
    source_text: "Net sales: $391,035 million...",
    relevance_score: 0.95
  }],
  route_taken: "xbrl_financial",
  confidence_score: 0.92,
  tokens_used: 4521,
  latency_ms: 2340
};

// Toggle between mock and real API with env variable
const api = process.env.NEXT_PUBLIC_USE_MOCK === "true" ? mockApi : realApi;
```

```python
# Evaluation can run against mock pipeline until Module A is ready
class MockPipelineForEval:
    """Returns canned responses for eval queries to test the eval framework itself."""
    def query(self, request):
        return QueryResponse(answer="Mock answer", citations=[], ...)
```

### Tech Stack
**Frontend:**
- `next@14` — React framework
- `@ai-sdk/react` — Streaming chat UI
- `cytoscape` — Knowledge graph visualization
- `recharts` — Evaluation charts
- `tailwindcss` — Styling

**Evaluation:**
- `ragas>=0.2.0` — RAG evaluation metrics
- `deepeval>=0.21.0` — Additional eval metrics
- `matplotlib>=3.8.0` — Ablation study charts

### Unit Testing Strategy
```typescript
// Frontend: Jest + React Testing Library
test("renders chat interface", () => {
  render(<ChatInterface />);
  expect(screen.getByPlaceholderText("Ask a question...")).toBeInTheDocument();
});

test("displays citations after query", async () => {
  render(<ChatInterface />);
  // Submit query
  // Assert citation cards appear
});
```

```python
# tests/test_eval_metrics.py
def test_confidence_score_calculation():
    score = calculate_ddcs(
        numerical_accuracy=1.0,
        citation_accuracy=0.8,
        faithfulness=0.9,
        contradiction_rate=0.5,
        completeness=0.7
    )
    expected = 0.30*1.0 + 0.25*0.8 + 0.20*0.9 + 0.15*0.5 + 0.10*0.7
    assert abs(score - expected) < 0.001

# tests/test_eval_runner.py
def test_eval_runner_processes_all_tiers():
    runner = EvalRunner(pipeline=MockPipeline())
    results = runner.run_all()
    assert len(results) == 30
    assert all(r["tier"] in [1, 2, 3, 4] for r in results)
```

### Deliverables
1. `frontend/` — Working Next.js app with 5 pages
2. `evaluation/` — Complete eval framework with 30 queries
3. `evaluation/report.md` — Evaluation report with charts
4. `Dockerfile` for frontend
5. `docker-compose.yml` (updated with frontend service)
6. `.github/workflows/ci.yml` — CI/CD pipeline
7. Live deployed URL (Vercel for frontend, Railway for backend)

---

## INTEGRATION STRATEGY

### Contract-First Approach
All 4 modules communicate through well-defined contracts (above). The integration points are:

```
Module A (RAG Pipeline) ←── called by ──→ Module C (API)
Module A (RAG Pipeline) ←── calls ──→ Module B (KG + Contradiction)
Module C (API) ←── called by ──→ Module D (Frontend)
Module D (Eval) ←── calls ──→ Module A (RAG Pipeline) directly
```

### Integration Order (Step-by-Step)

**Phase 1 (Day 5): A + C Integration**
- Person 3 replaces `MockRAGPipeline` with Person 1's real `RAGPipeline`
- Test: `POST /api/query` returns real answers from Pinecone/XBRL
- Validation: Run 5 Tier 1 queries through the API

**Phase 2 (Day 5): A + B Integration**
- Person 1 replaces `MockKnowledgeGraphEngine` and `MockContradictionDetector` with Person 2's real implementations
- Test: Knowledge graph route returns real Neo4j results
- Test: Contradiction detection returns real comparisons

**Phase 3 (Day 6): D + C Integration**
- Person 4 points frontend from mock API to Person 3's real FastAPI
- Test: Chat UI sends query → API → Pipeline → Response displayed
- Test: Login flow works with JWT

**Phase 4 (Day 6): D + A Integration (Eval)**
- Person 4 runs evaluation framework against real pipeline
- Run all 30 queries, collect metrics
- Run ablation study

**Phase 5 (Day 7): Full System Test**
- All 4 modules connected
- Run all 30 eval queries end-to-end through the deployed system
- Fix any integration issues
- Generate final evaluation report

### Shared Contracts File
Create `src/contracts.py` that all modules import:
```python
# src/contracts.py — Shared data classes used across all modules
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class QueryRequest:
    question: str
    tenant_id: str = "default"
    user_id: str = "anonymous"
    filters: dict = field(default_factory=dict)

@dataclass
class Citation:
    company_name: str
    filing_type: str
    filing_date: str
    item_number: str = ""
    item_title: str = ""
    source_text: str = ""
    relevance_score: float = 0.0

@dataclass
class QueryResponse:
    answer: str
    citations: list
    route_taken: str
    confidence_score: float
    sources_retrieved: list
    tokens_used: int
    latency_ms: int
    query_id: str

@dataclass
class GraphQueryRequest:
    question: str
    company_tickers: list = field(default_factory=list)

@dataclass
class GraphQueryResponse:
    cypher_query: str
    results: list
    entities: list
    relationships: list
    visualization_data: dict = field(default_factory=dict)

@dataclass
class ContradictionRequest:
    company_ticker: str
    time_range: str = "last_2_years"

@dataclass
class ContradictionResponse:
    contradictions: list
    summary: str = ""
```

---

## 1-WEEK EXECUTION PLAN

### Day 1 (Sunday Apr 13) — Setup & Skeleton

| Person | Tasks | Deliverable |
|--------|-------|-------------|
| **P1 (Prakash)** | Create `src/` skeleton. Set up LangGraph. Implement `QueryRouter` with LLM classification. Test router with 10 sample queries. | Router classifies queries into correct routes |
| **P2** | Install Neo4j (Aura free tier or Desktop). Define graph schema. Start entity extraction from proxy statement chunks. | Neo4j running with schema created |
| **P3** | Create `api/` skeleton with FastAPI. Implement JWT auth (login, register, token verify). Set up SQLite for users + audit. | `/api/auth/login` working, returns JWT |
| **P4** | Create `frontend/` with Next.js. Build chat UI page + login page. Set up mock API. Create `evaluation/queries.json` with all 30 queries. | Frontend skeleton running locally |

**Daily Checkpoint:** Everyone pushes skeleton code. Verify `src/contracts.py` is shared.

### Day 2 (Monday Apr 14) — Core Implementation

| Person | Tasks | Deliverable |
|--------|-------|-------------|
| **P1** | Implement Pinecone retrieval node (sec_filing, transcript, proxy, patent routes). Implement XBRL NL-to-SQL node (wrap existing NL2SQL). Build response generator with citation extraction. | 5 retrieval routes working individually |
| **P2** | Build entity extraction pipeline for 10-K filings (Company, RiskFactor, Subsidiary). Start populating Neo4j for 3 companies (AAPL, MSFT, NVDA). | Entities extracted and loaded into Neo4j |
| **P3** | Implement `POST /api/query` (with mock pipeline). Implement `GET /api/documents`. Add RBAC middleware. Implement audit trail logging. | API endpoints working with mock data |
| **P4** | Build Document Management page. Build Citation display component. Set up RAGAS evaluation framework. Write `eval_runner.py` skeleton. | 3 frontend pages working with mock data |

**Daily Checkpoint:** P1 demos router + retrieval. P3 demos API auth flow.

### Day 3 (Tuesday Apr 15) — Feature Completion

| Person | Tasks | Deliverable |
|--------|-------|-------------|
| **P1** | Wire all nodes into LangGraph state machine. Implement multi-hop agentic flow. Test end-to-end: question → route → retrieve → generate → respond. | Full pipeline answers Tier 1 queries |
| **P2** | Build NL-to-Cypher query engine. Build contradiction detection (claim extractor + comparator). Populate Neo4j for all 12 companies. Integrate CourtListener + News API. | KG queryable. Contradiction detector working. |
| **P3** | Implement structured logging (JSON + correlation IDs). Integrate LangFuse for LLM tracing. Implement Slack webhook notifications. Build `POST /api/documents/ingest`. | Observability + notifications working |
| **P4** | Build Knowledge Graph Viewer page (Cytoscape.js). Build Evaluation Dashboard page. Implement Due Diligence Confidence Score. | All 5 frontend pages built |

**Daily Checkpoint:** P1 demos full pipeline with real queries. P2 demos KG query.

### Day 4 (Wednesday Apr 16) — Integration Day 1

| Person | Tasks | Deliverable |
|--------|-------|-------------|
| **P1** | Integrate Person 2's KG engine + contradiction detector into pipeline. Add `knowledge_graph` and `contradiction` routes. Test Tier 2 + Tier 3 queries. | Pipeline handles all route types |
| **P2** | Help P1 integrate KG. Fix entity extraction issues. Add graph visualization export for frontend. | KG integrated into pipeline |
| **P3** | Replace mock pipeline with P1's real RAGPipeline. Test all API endpoints end-to-end. Add multi-tenant support. | API serves real answers |
| **P4** | Connect frontend to real API (replace mocks). Run first batch of eval queries (Tier 1 + 2). Start ablation study. | Frontend shows real data. Eval started. |

**Daily Checkpoint:** Full query flow works: Frontend → API → Pipeline → Answer.

### Day 5 (Thursday Apr 17) — Integration Day 2 + Polish

| Person | Tasks | Deliverable |
|--------|-------|-------------|
| **P1** | Fix pipeline bugs from integration. Optimize retrieval (reranking, better prompts). Test Tier 4 queries. | All 30 eval queries runnable |
| **P2** | Fix KG integration bugs. Improve entity extraction quality. Add more relationships. | KG quality improved |
| **P3** | Fix API integration bugs. Add rate limiting. Polish error handling. Create Docker setup. | Docker-compose running full stack |
| **P4** | Run all 30 eval queries. Run ablation study (6 configurations). Generate charts. | Eval results collected |

**Daily Checkpoint:** All 30 queries run. Docker-compose works.

### Day 6 (Friday Apr 18) — Deployment + Eval Report

| Person | Tasks | Deliverable |
|--------|-------|-------------|
| **P1** | Final pipeline tuning. Help with deployment issues. Write pipeline documentation. | Pipeline stable |
| **P2** | Final KG tuning. Help with deployment. Write KG documentation. | KG stable |
| **P3** | Deploy backend (Railway/AWS). Set up CI/CD. Final API testing. | Backend deployed with live URL |
| **P4** | Deploy frontend (Vercel). Write evaluation report. Create ablation charts. | Frontend deployed. Eval report done. |

**Daily Checkpoint:** Live URLs working. Eval report drafted.

### Day 7 (Saturday Apr 19) — Final Testing + Demo

| Person | Tasks | Deliverable |
|--------|-------|-------------|
| **ALL** | Full system test on deployed URLs. Fix critical bugs. Record demo video. Final README update. Merge all branches to main. | Everything working. Demo ready. |

---

## VERSION CONTROL STRATEGY

### Branch Structure
```
main (protected — no direct pushes)
├── feature/rag-pipeline        (Person 1)
├── feature/knowledge-graph     (Person 2)
├── feature/enterprise-backend  (Person 3)
└── feature/frontend-eval       (Person 4)
```

### Rules
1. Each person works exclusively on their branch
2. `src/contracts.py` is the shared interface — changes require team agreement
3. PR to main requires 1 reviewer
4. Merge order on integration days: P1 → P2 → P3 → P4
5. Rebase from main before creating PR: `git pull --rebase origin main`

### Shared Files (coordinate changes)
- `config.yaml` — Add new config sections, don't modify existing
- `requirements.txt` — Append new deps, don't remove existing
- `src/contracts.py` — Shared data classes (change requires team discussion)
- `.env.example` — Add new env vars with comments

---

## DEPENDENCY MAP (What Blocks What)

```
Nothing blocks Day 1-3 work (everyone uses mocks)

Day 4+ dependencies:
  P3 needs P1's RAGPipeline class (interface only, can use mock until real is ready)
  P1 needs P2's KG engine + contradiction detector (interface only, can use mock)
  P4 needs P3's API endpoints (interface only, can use mock)
  P4's eval needs P1's pipeline (can run eval framework with mock first)
```

**Key insight:** Because all contracts are defined upfront and everyone has mocks, no one is blocked for the first 3 days. Integration happens on Days 4-5 when all modules are individually working.

---

## REQUIREMENTS ADDITIONS TO requirements.txt

```
# === Module A: RAG Pipeline ===
langgraph>=0.2.0
langchain-openai>=0.2.0

# === Module B: Knowledge Graph ===
neo4j>=5.0.0
newsapi-python>=0.2.7

# === Module C: Enterprise Backend ===
fastapi>=0.115.0
uvicorn>=0.30.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.9
langfuse>=2.0.0
httpx>=0.27.0

# === Module D: Evaluation ===
ragas>=0.2.0
deepeval>=0.21.0
matplotlib>=3.8.0
```

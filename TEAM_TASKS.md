# M&A Oracle — Team Task Assignments

**Project:** M&A Oracle — Corporate Due Diligence Intelligence
**Deadline:** Sunday, 19 April 2026 — 11:59 PM IST
**Team Size:** 3 members
**Repo:** Push to your own branch, merge via Pull Request. Never push directly to main.

---

## Getting Started (Everyone)

1. Clone the repo
2. Create your branch: `git checkout -b feature/your-task-name`
3. Read `shared/INSTRUCTIONS.md` for data pipeline setup
4. Create `.env` from `.env.example` (never commit `.env`)
5. Run the data pipeline: `cd shared && python run_ingestion.py --tickers AAPL`
6. Start your assigned tasks below

---

## Person 1 — Core RAG Pipeline & Integration

**Branch:** `feature/core-pipeline`
**Focus:** Make the RAG system smart — routing, knowledge graph, contradiction detection

### Tasks

1. **Finish FAISS Indexing**
   - Run `python scripts/merge_and_index.py` to index all 23,534 chunks
   - Verify search works across all data sources

2. **Wire New Routes into Agentic Pipeline**
   - Add `earnings_transcript` route — queries about management statements, guidance, sentiment
   - Add `patent` route — queries about IP portfolio, patent claims, technology
   - Add `proxy_statement` route — queries about board members, compensation, related-party transactions
   - Update `src/agentic/nodes.py` router prompt and `src/agentic/graph.py` graph edges
   - Files: `src/agentic/nodes.py`, `src/agentic/graph.py`

3. **Contradiction Detection Engine**
   - Build a pipeline that compares earnings call claims vs. 10-K filing text
   - Extract claims from transcripts (e.g., "CEO says strong pipeline")
   - Extract facts from filings (e.g., "Item 1A says customer concentration risk")
   - Use LLM to compare and flag contradictions
   - New file: `src/agentic/contradiction_node.py`

4. **Knowledge Graph (Neo4j)**
   - Set up Neo4j (Desktop or Aura free tier)
   - Define schema: Company → Board Member → Subsidiary → Patent → Filing → Risk Factor
   - Build entity extraction from 10-K filings + proxy statements using LLM
   - Add `knowledge_graph` route with NL-to-Cypher query generation
   - New folder: `src/knowledge_graph/`

5. **Integration Testing**
   - Test all routes end-to-end with sample queries
   - Verify Tier 1-4 eval queries work

### Key Files
- `src/agentic/nodes.py` — router + retrieval nodes
- `src/agentic/graph.py` — LangGraph state machine
- `src/agentic/xbrl_node.py` — XBRL NL-to-SQL (reference for new nodes)
- `app/providers.py` — embedding/LLM provider factory
- `config.yaml` — all configuration

---

## Person 2 — Enterprise Backend & API

**Branch:** `feature/enterprise-backend`
**Focus:** Build the production backend — API, auth, audit, observability

### Tasks

1. **FastAPI REST API**
   - Create `api/` folder with FastAPI app
   - Endpoints:
     - `POST /api/query` — send question, get answer with citations
     - `GET /api/documents` — list ingested documents
     - `POST /api/documents/ingest` — trigger ingestion for a company
     - `GET /api/eval` — get evaluation results
     - `GET /api/admin/stats` — system statistics
   - Wrap the existing `RAGPipeline` from `src/pipeline.py`
   - Add request/response models with Pydantic

2. **Authentication & RBAC**
   - JWT token-based login
   - Three roles: admin (full access), analyst (query + view), viewer (query only)
   - Protect API endpoints by role
   - Suggested: `python-jose` for JWT, simple user table in SQLite

3. **Multi-Tenant Architecture**
   - Add `tenant_id` to all queries and documents
   - Data isolation — tenants only see their own data
   - Per-tenant configuration (which companies, which sources)
   - Usage tracking per tenant

4. **Audit Trail**
   - Log every query with full context to SQLite:
     ```json
     {
       "query_id": "uuid",
       "tenant_id": "tenant-abc",
       "user_id": "user-123",
       "timestamp": "2026-04-10T10:30:00Z",
       "query": "original user query",
       "route_taken": "sec_filing",
       "sources_retrieved": ["10-K-AAPL-2024-Item1A"],
       "generated_answer": "...",
       "confidence_score": 0.82,
       "tokens_used": 4521,
       "latency_ms": 2340
     }
     ```
   - New file: `src/enterprise/audit.py`

5. **Structured Logging**
   - JSON-formatted logs with correlation IDs
   - Every request traceable end-to-end: query → route → retrieve → generate → respond
   - New file: `src/enterprise/logging_config.py`

6. **Observability**
   - Integrate LangFuse (open-source, self-hostable) for LLM tracing
   - Track: latency, token usage, cost per query
   - Metrics dashboard: latency P50/P95, error rate, retrieval precision
   - New file: `src/enterprise/observability.py`

7. **Notifications**
   - Slack webhook integration for:
     - Document ingestion complete
     - Evaluation run complete
     - Error alerts
     - Anomaly detected (M&A Oracle specific)
   - New file: `src/enterprise/notifications.py`

### Key Files to Read First
- `src/pipeline.py` — existing RAG pipeline (wrap this in API)
- `src/agentic/graph.py` — agentic pipeline (understand the flow)
- `app/providers.py` — how LLM/embeddings are created
- `config.yaml` — all configuration

### Dependencies to Add
```
fastapi>=0.100.0
uvicorn>=0.23.0
python-jose>=3.3.0
python-multipart>=0.0.6
langfuse>=2.0.0
```

---

## Person 3 — Frontend & Evaluation

**Branch:** `feature/frontend-eval`
**Focus:** Build the React UI and prove the system works with rigorous evaluation

### Tasks — Frontend

1. **React/Next.js Application**
   - Create `frontend/` folder with Next.js app
   - Use Vercel AI SDK for streaming responses
   - Pages:
     - **Query Chat** — chat interface with streaming answers + filing citations
     - **Document Management** — list ingested companies, trigger ingestion, view status
     - **Knowledge Graph Viewer** — interactive graph visualization (use react-sigma or cytoscape.js)
     - **Evaluation Dashboard** — show metrics, per-query results, ablation charts
     - **Admin Panel** — user management, tenant config, system stats

2. **Citation Display**
   - Show inline citations: [Company, Filing Type, Date, Item]
   - Collapsible source cards below each answer
   - Link to original SEC filing when possible

3. **Connect to Backend API**
   - Call Person 2's FastAPI endpoints
   - Handle auth (JWT token in headers)
   - Stream responses using Server-Sent Events (SSE)

### Tasks — Evaluation

4. **Set Up Evaluation Framework**
   - Install RAGAS or DeepEval
   - Create `evaluation/` folder
   - New files: `evaluation/metrics.py`, `evaluation/eval_runner.py`

5. **Run 30 Evaluation Queries**
   - All 30 queries are defined in the project spec (4 tiers)
   - Run each query through the pipeline
   - Record: answer, retrieval sources, latency, route taken
   - Save results to `evaluation/results.json`

6. **Retrieval Metrics**
   - Context precision, context recall, MRR, NDCG
   - Measure per-tier (Tier 1 should score highest, Tier 4 lowest)

7. **Generation Metrics**
   - Faithfulness (is answer grounded in retrieved docs?)
   - Answer relevance (does answer address the question?)
   - Hallucination rate

8. **Custom Metric: Due Diligence Confidence Score**
   - Design a scoring rubric that weights:
     - Numerical accuracy (zero tolerance for wrong numbers)
     - Citation accuracy (every claim traces to a filing)
     - Contradiction detection rate
     - Completeness (did it surface all material risk factors?)
   - Document the formula and rationale

9. **Ablation Study**
   - Run eval queries with each component disabled:
     - Without router (everything to vectorstore)
     - Without knowledge graph
     - Without reranking
     - Without XBRL NL-to-SQL
     - Without contradiction detection
     - Without 3-tier caching
   - Record metrics for each configuration
   - Create comparison charts

10. **Evaluation Report**
    - Write `evaluation/report.md` with:
      - Per-tier metric breakdown
      - Ablation study results with charts
      - Custom metric analysis
      - Key findings and recommendations

### Tasks — Deployment

11. **Docker**
    - Create `Dockerfile` for backend
    - Create `docker-compose.yml` (backend + frontend + Neo4j)

12. **CI/CD**
    - GitHub Actions workflow: lint → test → build → deploy
    - Run eval suite in CI as quality gate

13. **Deploy**
    - Frontend: Vercel
    - Backend: Railway or AWS
    - Get a live public URL working

### Dependencies to Add
```
# Frontend (in frontend/package.json)
next, react, @ai-sdk/react, react-sigma, cytoscape

# Evaluation (in requirements.txt)
ragas>=0.1.0
deepeval>=0.20.0
```

---

## Timeline

| Week | Person 1 | Person 2 | Person 3 |
|------|----------|----------|----------|
| Apr 3-7 | FAISS index + wire routes | FastAPI skeleton + auth | Next.js skeleton + eval setup |
| Apr 7-12 | Knowledge graph + contradiction detection | Audit trail + observability + notifications | Run 30 eval queries + ablation study |
| Apr 12-17 | Integration testing + bug fixes | Multi-tenant + polish API | Frontend polish + deployment |
| Apr 17-19 | Final testing + demo prep | Final testing + demo prep | Eval report + demo prep |

---

## Git Workflow

1. Always work on your own branch
2. Push regularly: `git push origin feature/your-branch`
3. Create Pull Request when a task is done
4. Get at least 1 review before merging to main
5. Pull latest main before starting new work: `git pull origin main`

## Communication

- Daily standup: share what you did, what you're doing, any blockers
- Use PR comments for code review
- Tag teammates in PRs that affect their work

---

## Project Spec Reference

Full spec: https://fnusatvik07.github.io/rag-architect-capstone/#/project/ma-oracle

Scoring: 500 marks total
- RAG Architecture: 150 marks (30%)
- Evaluation Framework: 100 marks (20%)
- System Architecture: 100 marks (20%)
- Frontend & UX: 75 marks (15%)
- Deployment & Demo: 75 marks (15%)

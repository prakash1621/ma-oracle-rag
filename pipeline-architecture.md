# M&A Oracle — End-to-End Pipeline Architecture

## Overview

The system has 3 stages: Ingestion → Indexing → RAG Query. All settings are centralized in `config.yaml` and provider selection is handled by `app/providers.py`.

```
config.yaml (all settings)
       │
       ▼
app/providers.py (factory: creates LLM + Embeddings + VectorDB)
       │
       ├── Embeddings: Pinecone Inference (multilingual-e5-large)
       ├── LLM: OpenAI (gpt-4o-mini)
       └── VectorDB: Pinecone (ma-oracle index)
```

---

## Stage 1: Data Ingestion (Offline)

**Script:** `scripts/ingest_all.py` or `run_ingestion.py`

Pulls raw data from external APIs, parses documents, chunks them, and saves as JSON.

```
External APIs                    Ingestion Pipeline                Output
┌──────────────┐                ┌─────────────────────┐          ┌──────────────────────┐
│ SEC EDGAR    │───────────────▶│ ingestion/           │         │ data/                │
│ XBRL API     │                │ ├── edgar/client.py  │────────▶│ ├── edgar/chunked_documents.json
│ USPTO API    │                │ ├── edgar/parser.py  │         │ ├── transcripts/chunked_documents.json
│ Earnings     │                │ ├── xbrl/pipeline.py │         │ ├── proxy/chunked_documents.json
│ Proxy Stmt   │                │ └── patents/         │         │ ├── patents/chunked_documents.json
└──────────────┘                └─────────────────────┘          │ └── xbrl/financials.db
                                                                  └──────────────────────┘
```

**Output format (JSON):**
```json
[
  {
    "text": "chunk content...",
    "metadata": {
      "category": "sec_filing",
      "company_name": "Meta Platforms, Inc.",
      "filing_type": "10-K",
      "filing_date": "2025-01-30",
      "item_number": "7",
      "item_title": "MD&A",
      "cik": "0001326801"
    }
  }
]
```

---

## Stage 2: Embedding & Indexing (Offline)

**Script:** `scripts/merge_and_index.py`

Reads all chunked JSON files, embeds them using Pinecone Inference, and stores in Pinecone vector DB.

```
data/*.json                     Indexing Pipeline                 Pinecone Cloud
┌──────────────────┐           ┌──────────────────┐             ┌──────────────┐
│ chunked_documents│──────────▶│ merge_and_index.py│            │  ma-oracle   │
│ .json files      │           │       │           │            │  index       │
└──────────────────┘           │       ▼           │            │              │
                               │ app/embedding.py  │───────────▶│  23,534      │
                               │       │           │  embed +   │  vectors     │
                               │       ▼           │  upsert    │  + metadata  │
                               │ app/providers.py  │            │              │
                               │ (Pinecone embed)  │            │  1024 dims   │
                               └──────────────────┘             └──────────────┘
```

---

## Stage 3: RAG Query Pipeline (Online)

**Script:** `streamlit run main.py`

### Query Flow

```
User Question
     │
     ▼
main.py (Streamlit UI)
     │
     ▼
src/pipeline.py :: RAGPipeline.agentic_query()
     │
     ├──▶ CACHE CHECK (src/caching/)
     │    ├── Tier 1: exact_cache.py    → exact hash match
     │    ├── Tier 2: semantic_cache.py → cosine similarity ≥ 0.95
     │    └── Tier 3: retrieval_cache.py→ cosine similarity ≥ 0.90
     │
     │    HIT? → return cached answer (skip entire pipeline)
     │    MISS ▼
     │
     └──▶ AGENTIC RAG (src/agentic/graph.py — LangGraph State Machine)
```

### LangGraph Pipeline (12 Nodes)

```
┌──────────────────────────────────────────────────────────────────┐
│                    src/agentic/state.py                           │
│         (AgenticRAGState — carries data between all nodes)       │
└──────────────────────────────────────────────────────────────────┘

                         ┌─────────┐
                         │ ROUTER  │  src/agentic/nodes.py :: route_query()
                         │         │  LLM classifies: sec_filing | xbrl |
                         │         │  vectorstore | direct_llm
                         └────┬────┘
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         direct_llm      rewriter       xbrl_financials
         nodes.py        nodes.py       xbrl_node.py
         (no retrieval)  (resolve       (NL → SQL → SQLite
              │           follow-ups)    → format results)
             END              │               │
                              ▼              END
                          retrieve
                     src/retrieval/retriever.py
                     (search Pinecone with metadata filters)
                              │
                              ▼
                        grade_docs
                     nodes.py :: grade_documents()
                     (LLM grades each doc: relevant?)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                 rerank           corrective_rewrite
            src/retrieval/        nodes.py
            reranker.py           (rewrite query, retry)
            (top 3 by cosine)          │
                    │                  ▼
                    ▼              retrieve (retry)
                generate               │
           src/generation/              ▼
           generator.py            fallback
           (LLM generates          nodes.py
            answer from docs)      ("info not available")
                    │                   │
                    ▼                  END
            hallucination_check
            nodes.py :: check_hallucination()
            (LLM: is answer grounded in sources?)
                    │
               ┌────┴────┐
               ▼         ▼
           grounded   hallucinated → retry generate (max 3)
               │
               ▼
          grade_answer
          nodes.py :: grade_answer()
          (LLM: does answer address the question?)
               │
          ┌────┴────┐
          ▼         ▼
        useful   not useful → retry generate (max 3)
          │
          ▼
     Return answer + trace + source citations
          │
          ▼
     main.py displays in Streamlit UI
```

---

## File Dependency Map

```
config.yaml
  └──▶ src/utils/config_loader.py (reads YAML)
         └──▶ app/providers.py (creates LLM + Embeddings based on config)
                ├──▶ app/embedding.py (Pinecone vector store create/load/save)
                ├──▶ src/generation/generator.py (LLM answer generation)
                └──▶ src/utils/embeddings.py (embedding wrapper)

src/agentic/
  ├── state.py      → TypedDict with Annotated reducers (shared state)
  ├── graph.py      → LangGraph StateGraph (wires 12 nodes + conditional edges)
  ├── nodes.py      → all node implementations (router, grader, generator, etc.)
  └── xbrl_node.py  → NL-to-SQL for structured financial queries

src/retrieval/
  ├── retriever.py  → Pinecone search + category/company filtering
  └── reranker.py   → embedding cosine similarity reranking

src/caching/
  ├── cache_manager.py   → orchestrates 3-tier fallthrough
  ├── exact_cache.py     → Tier 1: hash match (SQLite)
  ├── semantic_cache.py  → Tier 2: cosine ≥ 0.95 (SQLite)
  ├── retrieval_cache.py → Tier 3: cosine ≥ 0.90 (SQLite)
  └── cache_factory.py   → creates cache instances from config

src/chunking/
  ├── parent_child.py    → parent (3000 chars) + child (500 chars)
  └── semantic_chunker.py→ embedding-based boundary detection

src/pipeline.py → RAGPipeline class (ties cache + agentic graph)
main.py         → Streamlit UI entry point
```

---

## Key Connections Between Stages

| From | To | Connection |
|------|-----|-----------|
| Stage 1 output | Stage 2 input | JSON files in `data/` folder |
| Stage 2 output | Stage 3 input | Pinecone index (`ma-oracle`) loaded via `app/embedding.py` |
| Metadata | All stages | `category`, `company_name`, `filing_type` flow from ingestion → indexing → retrieval → answer citations |
| config.yaml | All stages | Single source of truth for providers, settings, paths |
| app/providers.py | All stages | Factory pattern — swap providers by changing config, no code changes |

---

## Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| Embeddings | Pinecone Inference (multilingual-e5-large) | Free tier |
| Vector DB | Pinecone (cloud) | Free tier (2GB, 2M read/write units) |
| LLM | OpenAI gpt-4o-mini | ~$0.002/query |
| Orchestration | LangGraph | Open source |
| Caching | SQLite (3-tier) | Free (local) |
| Structured Data | SQLite (XBRL financials) | Free (local) |
| UI | Streamlit | Free |

---

## Commands

```bash
# Stage 1: Ingest data
python scripts/ingest_all.py

# Stage 2: Index into Pinecone
python scripts/merge_and_index.py

# Stage 3: Run RAG app
streamlit run main.py
```

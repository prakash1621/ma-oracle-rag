# M&A Oracle — Financial Due Diligence System

A RAG-powered financial analysis platform that ingests SEC filings, financial data, earnings transcripts, patents, and proxy statements for 12 S&P 500 tech companies. Ask questions in natural language — get answers with citations.

## Architecture

```
User question
      ↓
  [RAG Router]  → classifies question type
      ↓
      ├── sec_filing ──────→ Pinecone vector search
      ├── xbrl_financial ──→ NL-to-SQL (SQLite)
      ├── transcript ──────→ Pinecone vector search
      ├── patent ──────────→ Pinecone + SQLite
      ├── proxy ───────────→ Pinecone vector search
      ├── knowledge_graph ─→ Neo4j (TODO)
      └── contradiction ───→ Cross-source compare (TODO)
      ↓
  [LLM Generator]  → answer + citations
```

## Components

| Component | Status | Description |
|-----------|--------|-------------|
| Data Ingestion | ✅ Done | 6 sources → Pinecone + SQLite |
| NL2SQL Service | ✅ Done | Natural language → SQL queries against XBRL data |
| RAG Pipeline | ✅ Done | Router + generator with mock retrieval |
| Retrieval Nodes | 🔲 TODO | Pinecone + XBRL + Patent queries (Person 2) |
| Knowledge Graph | 🔲 TODO | Neo4j entity relationships (Person 3) |
| Contradiction Detection | 🔲 TODO | Cross-source analysis (Person 4) |

## Quick Start

### 1. Install

```bash
git clone https://github.com/prakash1621/ma-oracle-rag.git
cd ma-oracle-rag
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your keys:
```
SEC_USER_AGENT=MAOracle yourname@gmail.com
GROQ_API_KEY=your_groq_api_key
PINECONE_API_KEY=your_pinecone_api_key
```

### 3. Run data ingestion

```bash
python run_ingestion.py                        # All sources, all companies
python run_ingestion.py --tickers AAPL MSFT    # Specific companies
python run_ingestion.py --sources edgar xbrl   # Specific sources
python run_ingestion.py --stats                # Show data summary
python run_ingestion.py --index                # Build Pinecone index only
```

### 4. Start the NL2SQL + RAG service

```bash
python -m nl2sql.main
```

Open `http://localhost:8000/` — two modes available:
- SQL Mode — direct financial queries against SQLite
- RAG Mode — routes to the best data source automatically


## API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/` | Web UI |
| GET | `/health` | System status + memory count |
| POST | `/chat` | NL2SQL (SQL mode) |
| POST | `/query` | RAG pipeline (routes to best source) |

## Data Sources

| # | Source | What It Provides |
|---|--------|-----------------|
| 1 | SEC EDGAR 10-K/10-Q | Annual/quarterly reports — risk factors, MD&A, financials |
| 2 | SEC EDGAR 8-K | Material events, earnings releases |
| 3 | XBRL Financial Data | Structured metrics — revenue, income, assets, etc. |
| 4 | Earnings Transcripts | CEO/CFO remarks + analyst Q&A (via 8-K fallback) |
| 5 | USPTO Patents | Patent titles, abstracts, assignees |
| 6 | DEF 14A Proxy | Board members, executive compensation |
| 7 | Company Facts | Company metadata (SIC codes, state, fiscal year) |

## Output Data

```
output/
├── edgar/chunked_documents.json       ← 10-K filing text chunks
├── xbrl/financials.db                 ← Financial numbers (SQLite)
├── transcripts/chunked_documents.json ← Earnings release text chunks
├── patents/patents.db + JSON          ← Patent data
├── proxy/chunked_documents.json       ← Proxy statement text chunks
└── company_facts/companies.json       ← Company metadata
```

## Project Structure

```
ma-oracle-rag/
├── config.yaml              ← Unified config (LLM, Pinecone, embedding, NL2SQL)
├── .env                     ← API keys (never commit)
├── requirements.txt         ← Python dependencies
├── run_ingestion.py         ← Data ingestion entry point
├── ingestion/               ← Data pipeline modules
│   ├── edgar/               ← SEC EDGAR client + parser
│   ├── xbrl/                ← XBRL financial data
│   ├── transcripts/         ← Earnings transcripts
│   ├── patents/             ← USPTO patents
│   └── proxy/               ← DEF 14A proxy statements
├── nl2sql/                  ← NL2SQL FastAPI service
│   ├── main.py              ← Entry point: python -m nl2sql.main
│   ├── app/                 ← API, config, pipeline, memory, security
│   └── static/              ← Web UI (HTML, CSS, JS)
└── src/                     ← RAG pipeline
    ├── contracts.py          ← Shared data classes
    ├── pipeline.py           ← RAG router + generator
    ├── mocks.py              ← Mock functions for Person 2/3/4
    ├── retrieval/            ← Person 2: Pinecone + XBRL + Patents (TODO)
    ├── knowledge_graph/      ← Person 3: Neo4j (TODO)
    └── contradiction/        ← Person 4: Cross-source analysis (TODO)
```

## Companies Tracked

AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, CRM, SNOW, CRWD, PANW, FTNT

## Configuration

All settings in `config.yaml`:
- `embedding` — provider (Pinecone integrated, HuggingFace, Bedrock, OpenAI)
- `llm` — provider (Groq default, Bedrock, OpenAI, Ollama)
- `vector_store` — Pinecone index settings
- `nl2sql` — NL2SQL service settings
- `companies` — tickers to ingest

## Team Development

See `DEVELOPMENT_PLAN_4P.md` for the full 4-person development plan with task assignments, function signatures, and timeline.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "SEC_USER_AGENT not set" | Create `.env` with your email |
| "Incorrect API key" | Check `.env` — Groq keys start with `gsk_` |
| "PINECONE_API_KEY is required" | Add Pinecone key to `.env` |
| Ingestion is slow | SEC rate limit (10 req/sec) — normal |
| NL2SQL not responding | Run ingestion first to create `financials.db` |
| RAG shows mock data | Expected — Person 2/3/4 modules not built yet |

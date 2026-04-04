# M&A Oracle — Data Pipeline (Shared Module)

This is the standalone data ingestion, parsing, and indexing pipeline for the M&A Oracle project. It downloads, parses, and indexes SEC filings, financial data, earnings transcripts, patents, and proxy statements for corporate due diligence analysis.

## What This Does

```
SEC EDGAR API  ──→  10-K/10-Q/8-K filings  ──→  Parsed sections  ──→  Chunked text  ──→  FAISS index
XBRL API       ──→  Financial facts         ──→  SQLite database
Motley Fool    ──→  Earnings transcripts    ──→  Chunked text      ──→  FAISS index
USPTO          ──→  Patent records          ──→  SQLite + chunks   ──→  FAISS index
EDGAR          ──→  DEF 14A proxy           ──→  Chunked text      ──→  FAISS index
```

## Quick Start (5 minutes)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

Edit `.env`:
```
SEC_USER_AGENT=MAOracle your_email@example.com
```

If using AWS Bedrock for embeddings (default), also set AWS credentials.
If you want free local embeddings, change `config.yaml`:
```yaml
embedding:
  provider: "huggingface"   # change from "bedrock" to "huggingface"
```
Then install: `pip install sentence-transformers langchain-huggingface`

### 3. Run ingestion

```bash
# Ingest everything for default companies
python run_ingestion.py

# Ingest specific companies only
python run_ingestion.py --tickers AAPL MSFT NVDA

# Ingest specific sources only
python run_ingestion.py --sources edgar xbrl

# Just show stats (no ingestion)
python run_ingestion.py --stats
```

### 4. View your data

After ingestion, your data is in:

| Data | Location | How to View |
|------|----------|-------------|
| SEC filing chunks | `output/edgar/chunked_documents.json` | Open in any text editor |
| XBRL financials | `output/xbrl/financials.db` | SQLite viewer or `--stats` flag |
| Transcripts | `output/transcripts/chunked_documents.json` | Open in any text editor |
| Patents | `output/patents/patents.db` + JSON | SQLite viewer |
| Proxy statements | `output/proxy/chunked_documents.json` | Open in any text editor |
| Company metadata | `output/company_facts/companies.json` | Open in any text editor |
| FAISS vector index | `output/vector_store/` | Used by the RAG pipeline |

## Data Sources

| # | Source | What It Provides |
|---|--------|-----------------|
| 1 | SEC EDGAR 10-K/10-Q | Annual/quarterly reports with risk factors, MD&A, financial statements |
| 2 | SEC EDGAR 8-K | Material events, earnings releases |
| 3 | XBRL Financial Data | Structured financial metrics (revenue, income, assets, etc.) |
| 4 | Earnings Transcripts | CEO/CFO remarks + analyst Q&A (via 8-K fallback) |
| 5 | USPTO Patents | Patent titles, abstracts, assignees |
| 6 | DEF 14A Proxy | Board members, executive compensation, related-party transactions |
| 7 | Company Facts | Company metadata (SIC codes, state, fiscal year end) |

## Configuration

Edit `config.yaml` to change:
- Which embedding provider to use (bedrock, huggingface, openai)
- Which companies to ingest (default: 12 S&P 500 tech companies)
- Chunk sizes and overlap settings
- Output directories

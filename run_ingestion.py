"""
M&A Oracle Data Pipeline — Single entry point.

Usage:
    python run_ingestion.py                          # Ingest all sources, all companies
    python run_ingestion.py --tickers AAPL MSFT      # Specific companies
    python run_ingestion.py --sources edgar xbrl     # Specific sources only
    python run_ingestion.py --stats                  # Show what data you have
    python run_ingestion.py --index                  # Just build FAISS index from existing chunks
"""

import argparse
import json
import os
import sys
import logging

from dotenv import load_dotenv
load_dotenv()

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "")


def load_config():
    with open(os.path.join(os.path.dirname(__file__), "config.yaml")) as f:
        return yaml.safe_load(f)


def ingest_edgar(tickers, config):
    """Source 1+2: SEC EDGAR 10-K filings."""
    from ingestion.edgar import EdgarIngestionPipeline
    output_dir = config.get("edgar", {}).get("output_dir", "output/edgar")
    pipeline = EdgarIngestionPipeline(user_agent=SEC_USER_AGENT, output_dir=output_dir)
    count = config.get("edgar", {}).get("filings_per_type", 2)

    for ticker in tickers:
        result = pipeline.ingest_company(ticker=ticker, filing_types=["10-K", "10-Q", "8-K"], count=count)
        print(f"  {ticker}: {result.chunks_created} chunks")

    docs = pipeline.get_documents()
    slim = [{"text": d["text"], "metadata": {k: v for k, v in d["metadata"].items() if k != "parent_text"}} for d in docs]
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "chunked_documents.json"), "w") as f:
        json.dump(slim, f)
    print(f"  Total: {len(slim)} chunks saved")


def ingest_xbrl(tickers, config):
    """Source 3: XBRL structured financial data."""
    from ingestion.xbrl.pipeline import XBRLPipeline
    db_path = os.path.join(config.get("output", {}).get("base_dir", "output"), "xbrl", "financials.db")
    pipeline = XBRLPipeline(user_agent=SEC_USER_AGENT, db_path=db_path)
    pipeline.ingest_batch(tickers)
    stats = pipeline.get_stats()
    print(f"  Total: {stats['total_facts']} facts for {stats['companies']} companies")
    pipeline.close()


def ingest_transcripts(tickers, config):
    """Source 4: Earnings call transcripts."""
    from ingestion.transcripts import TranscriptPipeline
    pipeline = TranscriptPipeline(user_agent=SEC_USER_AGENT)
    chunks = pipeline.ingest_batch(tickers, count=4)
    out_dir = os.path.join(config.get("output", {}).get("base_dir", "output"), "transcripts")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "chunked_documents.json"), "w") as f:
        json.dump(chunks, f)


def ingest_patents(tickers, config):
    """Source 5: USPTO Patents."""
    from ingestion.patents import PatentPipeline
    db_path = os.path.join(config.get("output", {}).get("base_dir", "output"), "patents", "patents.db")
    pipeline = PatentPipeline(db_path=db_path)
    chunks = pipeline.ingest_batch(tickers, count=50)
    out_dir = os.path.join(config.get("output", {}).get("base_dir", "output"), "patents")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "chunked_documents.json"), "w") as f:
        json.dump(chunks, f)
    pipeline.close()


def ingest_proxy(tickers, config):
    """Source 6: DEF 14A Proxy Statements."""
    from ingestion.proxy import ProxyPipeline
    pipeline = ProxyPipeline(user_agent=SEC_USER_AGENT)
    chunks = pipeline.ingest_batch(tickers, count=2)
    out_dir = os.path.join(config.get("output", {}).get("base_dir", "output"), "proxy")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "chunked_documents.json"), "w") as f:
        json.dump(chunks, f)


def ingest_company_facts(tickers, config):
    """Source 7: EDGAR Company Facts metadata."""
    from ingestion.edgar.client import EdgarClient
    client = EdgarClient(user_agent=SEC_USER_AGENT)
    facts = []
    for ticker in tickers:
        cik = client.get_cik(ticker)
        meta = client.get_company_facts_metadata(cik)
        meta["ticker"] = ticker
        facts.append(meta)
        print(f"  {ticker}: {meta['name']}")
    out_dir = os.path.join(config.get("output", {}).get("base_dir", "output"), "company_facts")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "companies.json"), "w") as f:
        json.dump(facts, f, indent=2)
    print(f"  Total: {len(facts)} companies")


def build_index(config):
    """Merge all chunks and upsert to Pinecone using integrated embedding."""
    base_dir = config.get("output", {}).get("base_dir", "output")
    chunk_files = [
        (os.path.join(base_dir, "edgar", "chunked_documents.json"), "EDGAR"),
        (os.path.join(base_dir, "transcripts", "chunked_documents.json"), "Transcripts"),
        (os.path.join(base_dir, "proxy", "chunked_documents.json"), "Proxy"),
        (os.path.join(base_dir, "patents", "chunked_documents.json"), "Patents"),
    ]

    all_docs = []
    for path, label in chunk_files:
        if os.path.exists(path):
            docs = json.load(open(path))
            print(f"  {label}: {len(docs)} chunks")
            all_docs.extend(docs)
        else:
            print(f"  {label}: not found ({path})")

    if not all_docs:
        print("No chunks to index.")
        return

    print(f"\n  Total: {len(all_docs)} chunks to index")

    from pinecone import Pinecone

    vs_cfg = config.get("vector_store", {}).get("pinecone", {})
    index_name = vs_cfg.get("index_name", "ma-oracle-cap")
    namespace = vs_cfg.get("namespace", "default")
    cloud = vs_cfg.get("cloud", "aws")
    region = vs_cfg.get("region", "us-east-1")
    embed_model = config.get("embedding", {}).get("pinecone", {}).get("model_name", "multilingual-e5-large")

    pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))

    # Create index if it doesn't exist
    existing = [idx.name for idx in pc.list_indexes()]
    if index_name not in existing:
        print(f"  Creating Pinecone index '{index_name}' with integrated embedding ({embed_model})...")
        pc.create_index_for_model(
            name=index_name,
            cloud=cloud,
            region=region,
            embed={
                "model": embed_model,
                "field_map": {"text": "chunk_text"},
            },
        )
        print(f"  Index '{index_name}' created.")
    else:
        print(f"  Index '{index_name}' already exists.")

    index = pc.Index(index_name)
    print(f"  Connected to Pinecone index: {index_name}")

    # Pinecone integrated embedding: upsert_records with text, max 96 per batch
    # Rate limit: 250k tokens/min on free plan, so we add delays and retry on 429
    import time

    batch_size = 48  # Smaller batches to avoid rate limits
    start_from = 0

    # Check if we can resume from a previous run
    stats = index.describe_index_stats()
    existing_count = stats.get("total_vector_count", 0)
    if existing_count > 0:
        print(f"  Index already has {existing_count} vectors. Resuming from doc-{existing_count}...")
        start_from = existing_count

    for i in range(start_from, len(all_docs), batch_size):
        batch = all_docs[i:i + batch_size]
        records = []
        for j, doc in enumerate(batch):
            record = {"_id": f"doc-{i + j}", "chunk_text": doc["text"]}
            # Add metadata fields (Pinecone stores them for filtering)
            for k, v in doc.get("metadata", {}).items():
                if isinstance(v, (str, int, float, bool)):
                    record[k] = v
                elif isinstance(v, list):
                    record[k] = ", ".join(str(x) for x in v)
                else:
                    record[k] = str(v)
            records.append(record)

        # Retry with exponential backoff on rate limit (429)
        max_retries = 5
        for attempt in range(max_retries):
            try:
                index.upsert_records(namespace, records)
                break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 30 * (attempt + 1)  # 30s, 60s, 90s, 120s, 150s
                    print(f"  Rate limited at doc-{i}. Waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait)
                else:
                    raise

        end = min(i + batch_size, len(all_docs))
        if (i // batch_size) % 5 == 0:
            print(f"  Upserted {end}/{len(all_docs)} docs...")

        # Throttle: pause between batches to stay under token limit
        time.sleep(2)

    time.sleep(5)  # Wait for indexing to complete
    stats = index.describe_index_stats()
    total = stats.get("total_vector_count", 0)
    print(f"\n  Pinecone index '{index_name}' updated: {total} total vectors")


def show_stats(config):
    """Show what data exists."""
    base_dir = config.get("output", {}).get("base_dir", "output")
    print("\nData Summary:")
    for name, path in [
        ("EDGAR chunks", os.path.join(base_dir, "edgar", "chunked_documents.json")),
        ("Transcripts", os.path.join(base_dir, "transcripts", "chunked_documents.json")),
        ("Proxy chunks", os.path.join(base_dir, "proxy", "chunked_documents.json")),
        ("Patent chunks", os.path.join(base_dir, "patents", "chunked_documents.json")),
        ("Company facts", os.path.join(base_dir, "company_facts", "companies.json")),
    ]:
        if os.path.exists(path):
            docs = json.load(open(path))
            print(f"  {name}: {len(docs)} items")
        else:
            print(f"  {name}: not ingested yet")

    xbrl_path = os.path.join(base_dir, "xbrl", "financials.db")
    if os.path.exists(xbrl_path):
        import sqlite3
        conn = sqlite3.connect(xbrl_path)
        cnt = conn.execute("SELECT COUNT(*) FROM financial_facts").fetchone()[0]
        companies = conn.execute("SELECT COUNT(DISTINCT ticker) FROM companies").fetchone()[0]
        conn.close()
        print(f"  XBRL facts: {cnt} facts for {companies} companies")
    else:
        print(f"  XBRL facts: not ingested yet")


def main():
    parser = argparse.ArgumentParser(description="M&A Oracle Data Pipeline")
    parser.add_argument("--tickers", nargs="+", default=None)
    parser.add_argument("--sources", nargs="+",
        default=["edgar", "xbrl", "transcripts", "patents", "proxy", "company_facts"])
    parser.add_argument("--stats", action="store_true", help="Show data summary")
    parser.add_argument("--index", action="store_true", help="Build FAISS index only")
    args = parser.parse_args()

    config = load_config()
    tickers = args.tickers or config.get("companies", ["AAPL"])

    if args.stats:
        show_stats(config)
        return

    if args.index:
        print("Building FAISS index...")
        build_index(config)
        return

    if not SEC_USER_AGENT:
        print("ERROR: Set SEC_USER_AGENT in .env (format: 'AppName your@email.com')")
        sys.exit(1)

    print(f"Companies: {', '.join(tickers)}")
    print(f"Sources: {', '.join(args.sources)}\n")

    source_map = {
        "edgar": ("SEC EDGAR 10-K", ingest_edgar),
        "xbrl": ("XBRL Financial Data", ingest_xbrl),
        "transcripts": ("Earnings Transcripts", ingest_transcripts),
        "patents": ("USPTO Patents", ingest_patents),
        "proxy": ("DEF 14A Proxy", ingest_proxy),
        "company_facts": ("Company Facts", ingest_company_facts),
    }

    for source in args.sources:
        if source in source_map:
            label, func = source_map[source]
            print(f"{'='*50}\n  {label}\n{'='*50}")
            try:
                func(tickers, config)
            except Exception as e:
                print(f"  ERROR: {e}")

    print(f"\n{'='*50}\n  DONE\n{'='*50}")


if __name__ == "__main__":
    main()

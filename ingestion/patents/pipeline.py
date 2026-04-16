"""
USPTO Patent Ingestion Pipeline (Source 5).

Stores patent data in SQLite and produces text chunks for FAISS.
"""

import os
import sqlite3
import logging
from typing import List, Dict

from .client import PatentClient

logger = logging.getLogger(__name__)

TICKER_TO_ASSIGNEE = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft", "NVDA": "NVIDIA",
    "AMZN": "Amazon", "META": "Meta Platforms", "GOOGL": "Alphabet",
    "TSLA": "Tesla", "CRM": "Salesforce", "SNOW": "Snowflake",
    "CRWD": "CrowdStrike", "PANW": "Palo Alto Networks", "FTNT": "Fortinet",
}


class PatentPipeline:
    def __init__(self, db_path: str = "data/patents/patents.db", raw_dir: str = "output/patents/raw"):
        self.client = PatentClient()
        self.db_path = db_path
        self.raw_dir = raw_dir
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
        self._all_chunks: List[Dict] = []

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS patents (
                patent_id TEXT PRIMARY KEY, title TEXT, abstract TEXT,
                patent_date TEXT, patent_type TEXT, assignee TEXT,
                ticker TEXT, filing_date TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_patents_ticker ON patents(ticker);
        """)
        self.conn.commit()

    def ingest_company(self, ticker: str, count: int = 50, after_date: str = "2020-01-01") -> List[Dict]:
        import json
        assignee = TICKER_TO_ASSIGNEE.get(ticker, ticker)
        patents = self.client.search_by_assignee(assignee, size=count)

        # Save raw patent data
        raw_path = os.path.join(self.raw_dir, ticker)
        os.makedirs(raw_path, exist_ok=True)
        with open(os.path.join(raw_path, "patents_raw.json"), "w", encoding="utf-8") as f:
            json.dump(patents, f, indent=2)
        logger.info(f"  Saved raw patent data to {raw_path}/patents_raw.json")

        chunks = []
        for p in patents:
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO patents VALUES (?,?,?,?,?,?,?,?)",
                    (p["patent_id"], p["title"], p["abstract"], p["patent_date"],
                     p["patent_type"], p["assignee"], ticker, "")
                )
            except Exception as e:
                logger.error(f"DB error: {e}")

            chunks.append({
                "text": f"Patent: {p['title']}\nAssignee: {p['assignee']}\nDate: {p['patent_date']}\n\n{p['abstract']}",
                "metadata": {
                    "source": "uspto", "category": "patent",
                    "patent_id": p["patent_id"], "company_name": p["assignee"],
                    "ticker": ticker, "patent_date": p["patent_date"],
                }
            })

        self.conn.commit()
        self._all_chunks.extend(chunks)
        logger.info(f"Ingested {len(chunks)} patents for {ticker}")
        return chunks

    def ingest_batch(self, tickers: List[str], count: int = 50) -> List[Dict]:
        all_chunks = []
        for i, ticker in enumerate(tickers, 1):
            chunks = self.ingest_company(ticker, count=count)
            all_chunks.extend(chunks)
            print(f"  [{i}/{len(tickers)}] {ticker}: {len(chunks)} patents")
        print(f"\nTotal patent chunks: {len(all_chunks)}")
        return all_chunks

    def query(self, sql: str, params: tuple = ()) -> List[Dict]:
        cursor = self.conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_stats(self) -> Dict:
        cnt = self.query("SELECT COUNT(*) as cnt FROM patents")[0]["cnt"]
        companies = self.query("SELECT COUNT(DISTINCT ticker) as cnt FROM patents")[0]["cnt"]
        return {"total_patents": cnt, "companies": companies}

    def get_all_chunks(self) -> List[Dict]:
        return self._all_chunks

    def close(self):
        self.conn.close()

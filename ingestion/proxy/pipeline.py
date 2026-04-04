"""
DEF 14A Proxy Statement Ingestion Pipeline (Source 6).

Downloads proxy statements via EDGAR, parses board/compensation/
related-party sections, and produces chunks for indexing.
"""

import logging
from typing import List, Dict, Optional

from ingestion.edgar.client import EdgarClient
from .parser import ProxyParser

logger = logging.getLogger(__name__)


class ProxyPipeline:
    """
    Ingest DEF 14A proxy statements.

    Usage:
        pipeline = ProxyPipeline(user_agent="MAOracle user@example.com")
        chunks = pipeline.ingest_company("AAPL", count=2)
    """

    def __init__(self, user_agent: str):
        self.client = EdgarClient(user_agent=user_agent)
        self.parser = ProxyParser()
        self._all_chunks: List[Dict] = []

    def ingest_company(
        self, ticker: str, count: int = 2, cik: Optional[str] = None
    ) -> List[Dict]:
        """Ingest proxy statements for a company."""
        if not cik:
            cik = self.client.get_cik(ticker)

        filings = self.client.get_filings(cik, filing_type="DEF 14A", count=count)
        logger.info(f"Found {len(filings)} DEF 14A filings for {ticker}")

        chunks = []
        for filing in filings:
            try:
                html = self.client.download_filing(filing)
                metadata = {
                    "company_name": filing.company_name,
                    "cik": filing.cik,
                    "filing_type": "DEF 14A",
                    "filing_date": filing.filing_date,
                    "accession_number": filing.accession_number,
                }
                parsed = self.parser.parse(html, metadata)
                chunks.extend(parsed)
                logger.info(
                    f"  {filing.filing_date}: {len(parsed)} chunks"
                )
            except Exception as e:
                logger.error(f"  Failed {filing.filing_date}: {e}")

        self._all_chunks.extend(chunks)
        return chunks

    def ingest_batch(self, tickers: List[str], count: int = 2) -> List[Dict]:
        """Ingest proxy statements for multiple companies."""
        all_chunks = []
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"[{i}/{len(tickers)}] Ingesting DEF 14A for {ticker}...")
            chunks = self.ingest_company(ticker, count=count)
            all_chunks.extend(chunks)
            print(f"  [{i}/{len(tickers)}] {ticker}: {len(chunks)} chunks")
        print(f"\nTotal proxy chunks: {len(all_chunks)}")
        return all_chunks

    def get_all_chunks(self) -> List[Dict]:
        return self._all_chunks

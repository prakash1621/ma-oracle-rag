"""
Earnings Transcript Ingestion Pipeline (Source 4).

Tries Motley Fool first, falls back to 8-K Item 2.02 earnings releases.
"""

import logging
from typing import List, Dict, Optional

from .scraper import TranscriptScraper
from .parser import TranscriptParser

logger = logging.getLogger(__name__)


class TranscriptPipeline:
    """
    Ingest earnings call transcripts.

    Usage:
        pipeline = TranscriptPipeline(user_agent="MAOracle user@example.com")
        chunks = pipeline.ingest_company("AAPL", count=4)
    """

    def __init__(self, user_agent: str = ""):
        self.scraper = TranscriptScraper()
        self.parser = TranscriptParser()
        self.user_agent = user_agent
        self._all_chunks: List[Dict] = []

    def ingest_company(
        self, ticker: str, count: int = 4, cik: Optional[str] = None
    ) -> List[Dict]:
        """
        Ingest transcripts for a company.
        Tries Motley Fool first, falls back to 8-K earnings releases.
        """
        chunks = []

        # Try Motley Fool
        urls = self.scraper.find_transcript_urls(ticker, count=count)
        for url in urls:
            transcript = self.scraper.fetch_transcript(url)
            if transcript:
                parsed = self.parser.parse(transcript)
                chunks.extend(parsed)
                logger.info(f"  Motley Fool: {len(parsed)} chunks from {url}")

        # If not enough from Motley Fool, try 8-K fallback
        if len(chunks) < count * 3 and self.user_agent:
            logger.info(f"  Trying 8-K fallback for {ticker}...")
            from ingestion.edgar.client import EdgarClient
            client = EdgarClient(user_agent=self.user_agent)
            if not cik:
                cik = client.get_cik(ticker)

            releases = self.scraper.fetch_from_8k(client, cik, count=count)
            for release in releases:
                parsed = self.parser.parse(release)
                chunks.extend(parsed)

        self._all_chunks.extend(chunks)
        logger.info(f"Ingested {len(chunks)} transcript chunks for {ticker}")
        return chunks

    def ingest_batch(self, tickers: List[str], count: int = 4) -> List[Dict]:
        """Ingest transcripts for multiple companies."""
        all_chunks = []
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"[{i}/{len(tickers)}] Ingesting transcripts for {ticker}...")
            chunks = self.ingest_company(ticker, count=count)
            all_chunks.extend(chunks)
            print(f"  [{i}/{len(tickers)}] {ticker}: {len(chunks)} chunks")
        print(f"\nTotal transcript chunks: {len(all_chunks)}")
        return all_chunks

    def get_all_chunks(self) -> List[Dict]:
        return self._all_chunks

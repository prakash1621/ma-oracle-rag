"""
XBRL Ingestion Pipeline.

Orchestrates: fetch company facts → parse → store in SQLite.
Supports batch ingestion of multiple companies.
"""

import json
import logging
from typing import List, Dict, Optional

from .client import XBRLClient
from .parser import XBRLParser
from .storage import XBRLStorage

logger = logging.getLogger(__name__)


class XBRLPipeline:
    """
    End-to-end XBRL ingestion pipeline.

    Usage:
        pipeline = XBRLPipeline(
            user_agent="MAOracle user@example.com",
            db_path="data/xbrl/financials.db"
        )
        stats = pipeline.ingest_company("AAPL", cik="0000320193")
        stats = pipeline.ingest_batch(["AAPL", "MSFT", "NVDA"])
    """

    def __init__(
        self,
        user_agent: str,
        db_path: str = "data/xbrl/financials.db",
        core_only: bool = True,
        raw_dir: str = "output/xbrl/raw",
    ):
        self.client = XBRLClient(user_agent=user_agent)
        self.parser = XBRLParser(core_only=core_only)
        self.storage = XBRLStorage(db_path=db_path)
        self.raw_dir = raw_dir
        self._cik_cache: Dict[str, str] = {}

    def _resolve_cik(self, ticker: str, cik: Optional[str] = None) -> str:
        """Resolve ticker to CIK, using cache."""
        if cik:
            return cik
        if ticker in self._cik_cache:
            return self._cik_cache[ticker]

        # Use the EDGAR client from the existing pipeline
        from ingestion.edgar.client import EdgarClient
        edgar = EdgarClient(user_agent=self.client.session.headers["User-Agent"])
        resolved = edgar.get_cik(ticker)
        self._cik_cache[ticker] = resolved
        return resolved

    def ingest_company(
        self, ticker: str, cik: Optional[str] = None
    ) -> Dict:
        """
        Ingest all XBRL financial facts for a single company.

        Args:
            ticker: Stock ticker (e.g., "AAPL")
            cik: Optional pre-resolved CIK

        Returns:
            Dict with ingestion stats
        """
        cik = self._resolve_cik(ticker, cik)
        logger.info(f"Ingesting XBRL data for {ticker} (CIK {cik})")

        # Fetch raw facts from SEC
        try:
            raw_facts = self.client.get_company_facts(cik)
        except Exception as e:
            logger.error(f"Failed to fetch XBRL for {ticker}: {e}")
            return {"ticker": ticker, "cik": cik, "status": "error", "error": str(e)}

        # Save raw XBRL JSON
        import os
        raw_path = os.path.join(self.raw_dir, ticker)
        os.makedirs(raw_path, exist_ok=True)
        with open(os.path.join(raw_path, "company_facts.json"), "w", encoding="utf-8") as f:
            json.dump(raw_facts, f, indent=2)
        logger.info(f"  Saved raw XBRL data to {raw_path}/company_facts.json")

        entity_name = raw_facts.get("entityName", ticker)

        # Parse into normalized facts
        facts = self.parser.parse_company_facts(raw_facts)

        # Store company metadata
        self.storage.store_company(cik, entity_name, ticker)

        # Store facts
        stored = self.storage.store_facts(facts)

        stats = {
            "ticker": ticker,
            "cik": cik,
            "entity_name": entity_name,
            "facts_parsed": len(facts),
            "facts_stored": stored,
            "status": "success",
        }
        logger.info(
            f"Ingested {ticker}: {stored} facts stored for {entity_name}"
        )
        return stats

    def ingest_batch(self, tickers: List[str]) -> List[Dict]:
        """
        Ingest XBRL data for multiple companies.

        Args:
            tickers: List of stock tickers

        Returns:
            List of per-company stats dicts
        """
        results = []
        for i, ticker in enumerate(tickers, 1):
            logger.info(f"[{i}/{len(tickers)}] Processing {ticker}...")
            stats = self.ingest_company(ticker)
            results.append(stats)
            if stats["status"] == "success":
                print(
                    f"  [{i}/{len(tickers)}] {ticker}: "
                    f"{stats['facts_stored']} facts for {stats['entity_name']}"
                )
            else:
                print(f"  [{i}/{len(tickers)}] {ticker}: FAILED - {stats.get('error', 'unknown')}")

        # Summary
        success = sum(1 for r in results if r["status"] == "success")
        total_facts = sum(r.get("facts_stored", 0) for r in results)
        print(f"\nBatch complete: {success}/{len(tickers)} companies, {total_facts} total facts")

        return results

    def get_stats(self) -> Dict:
        """Get database statistics."""
        return self.storage.get_stats()

    def close(self):
        self.storage.close()

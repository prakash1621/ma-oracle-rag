"""
XBRL API Client for SEC EDGAR.

Fetches structured financial data from the SEC's XBRL APIs:
- companyfacts: All XBRL facts for a company
- companyconcept: Single concept time series
- frames: Cross-company comparison for a concept/period
"""

import time
import logging
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.12  # ~8 req/sec


class XBRLClient:
    """
    Client for SEC EDGAR XBRL data APIs.

    Usage:
        client = XBRLClient(user_agent="MAOracle user@example.com")
        facts = client.get_company_facts("0000320193")  # Apple
        concept = client.get_company_concept("0000320193", "us-gaap", "Revenues")
    """

    XBRL_BASE = "https://data.sec.gov/api/xbrl"

    def __init__(self, user_agent: str):
        if not user_agent or "@" not in user_agent:
            raise ValueError("SEC requires User-Agent with contact email.")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request_time = 0.0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str) -> requests.Response:
        self._rate_limit()
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp

    def get_company_facts(self, cik: str) -> Dict:
        """
        Fetch ALL XBRL facts for a company.

        Returns the full companyfacts JSON which contains every
        structured fact the company has ever filed, organized by
        taxonomy (us-gaap, dei, ifrs-full) and concept.

        Args:
            cik: 10-digit zero-padded CIK

        Returns:
            Dict with keys: cik, entityName, facts
            facts[taxonomy][concept] = { label, description, units }
        """
        url = f"{self.XBRL_BASE}/companyfacts/CIK{cik}.json"
        logger.info(f"Fetching company facts for CIK {cik}")
        resp = self._get(url)
        data = resp.json()
        logger.info(
            f"Got facts for {data.get('entityName', 'Unknown')}: "
            f"{sum(len(v) for v in data.get('facts', {}).values())} concepts"
        )
        return data

    def get_company_concept(
        self, cik: str, taxonomy: str, concept: str
    ) -> Dict:
        """
        Fetch a single concept's time series for a company.

        Args:
            cik: 10-digit zero-padded CIK
            taxonomy: e.g. "us-gaap", "dei", "ifrs-full"
            concept: e.g. "Revenues", "Assets", "NetIncomeLoss"

        Returns:
            Dict with units containing arrays of fact values over time
        """
        url = f"{self.XBRL_BASE}/companyconcept/CIK{cik}/{taxonomy}/{concept}.json"
        logger.info(f"Fetching concept {taxonomy}/{concept} for CIK {cik}")
        resp = self._get(url)
        return resp.json()

    def get_frame(
        self, taxonomy: str, concept: str, unit: str, period: str
    ) -> Dict:
        """
        Fetch cross-company data for a concept in a specific period.

        Args:
            taxonomy: e.g. "us-gaap"
            concept: e.g. "Revenues"
            unit: e.g. "USD", "USD-per-shares", "pure"
            period: e.g. "CY2023", "CY2023Q1", "CY2023Q1I"

        Returns:
            Dict with data array of {cik, entityName, val, ...} entries
        """
        url = f"{self.XBRL_BASE}/frames/{taxonomy}/{concept}/{unit}/{period}.json"
        logger.info(f"Fetching frame {taxonomy}/{concept}/{unit}/{period}")
        resp = self._get(url)
        return resp.json()

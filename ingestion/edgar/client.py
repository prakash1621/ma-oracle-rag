"""
SEC EDGAR API Client

Handles:
- Company CIK lookup
- Filing index retrieval (10-K, 10-Q, 8-K)
- Full filing document download
- Rate limiting per SEC fair access policy (10 req/sec max)

SEC EDGAR requires a User-Agent header with contact info.
"""

import time
import logging
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# SEC fair access: max 10 requests/sec
RATE_LIMIT_DELAY = 0.12  # ~8 req/sec to stay safe


@dataclass
class Filing:
    """Represents a single SEC filing."""
    accession_number: str
    filing_type: str  # 10-K, 10-Q, 8-K
    filing_date: str
    primary_document: str
    company_name: str
    cik: str
    period_of_report: str = ""
    items: str = ""  # For 8-K: item numbers (e.g., "2.02,9.01")
    documents: List[Dict] = field(default_factory=list)


class EdgarClient:
    """
    Client for SEC EDGAR EFTS and filing APIs.
    
    Usage:
        client = EdgarClient(user_agent="MyApp [email]")
        cik = client.get_cik("AAPL")
        filings = client.get_filings(cik, filing_type="10-K", count=5)
        html = client.download_filing(filings[0])
    """

    BASE_URL = "https://efts.sec.gov/LATEST"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions"
    ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"

    def __init__(self, user_agent: str):
        """
        Args:
            user_agent: Required by SEC. Format: "AppName ContactEmail"
                        e.g., "MAOracle research@example.com"
        """
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC requires a User-Agent with contact email. "
                "Format: 'AppName contact@email.com'"
            )
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request_time = 0.0

    def _rate_limit(self):
        """Enforce SEC fair access rate limit."""
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, params: Optional[Dict] = None) -> requests.Response:
        """Rate-limited GET request."""
        self._rate_limit()
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp

    def get_cik(self, ticker: str) -> str:
        """
        Look up a company's CIK number by ticker symbol.
        
        Returns:
            CIK as zero-padded 10-digit string (e.g., "0000320193" for AAPL)
        """
        url = "https://efts.sec.gov/LATEST/search-index"
        # Use the company tickers JSON endpoint instead
        tickers_url = "https://www.sec.gov/files/company_tickers.json"
        resp = self._get(tickers_url)
        data = resp.json()

        ticker_upper = ticker.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                cik = str(entry["cik_str"]).zfill(10)
                logger.info(f"Resolved {ticker} → CIK {cik} ({entry.get('title', '')})")
                return cik

        raise ValueError(f"Ticker '{ticker}' not found in SEC EDGAR")

    def get_company_info(self, cik: str) -> Dict:
        """Fetch company submission metadata from EDGAR."""
        url = f"{self.SUBMISSIONS_URL}/CIK{cik}.json"
        resp = self._get(url)
        return resp.json()

    def get_filings(
        self,
        cik: str,
        filing_type: str = "10-K",
        count: int = 5,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Filing]:
        """
        Get recent filings for a company.
        
        Args:
            cik: Company CIK (zero-padded)
            filing_type: "10-K", "10-Q", or "8-K"
            count: Max number of filings to return
            start_date: Filter filings after this date (YYYY-MM-DD)
            end_date: Filter filings before this date (YYYY-MM-DD)
            
        Returns:
            List of Filing objects sorted by date (newest first)
        """
        company_data = self.get_company_info(cik)
        company_name = company_data.get("name", "Unknown")

        recent = company_data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        periods = recent.get("reportDate", [])
        items_list = recent.get("items", [])

        filings = []
        for i, form in enumerate(forms):
            if form != filing_type:
                continue

            filing_date = dates[i] if i < len(dates) else ""

            # Date filtering
            if start_date and filing_date < start_date:
                continue
            if end_date and filing_date > end_date:
                continue

            filing = Filing(
                accession_number=accessions[i] if i < len(accessions) else "",
                filing_type=form,
                filing_date=filing_date,
                primary_document=primary_docs[i] if i < len(primary_docs) else "",
                company_name=company_name,
                cik=cik,
                period_of_report=periods[i] if i < len(periods) else "",
                items=items_list[i] if i < len(items_list) else "",
            )
            filings.append(filing)

            if len(filings) >= count:
                break

        logger.info(
            f"Found {len(filings)} {filing_type} filings for {company_name} (CIK {cik})"
        )
        return filings

    def download_filing(self, filing: Filing) -> str:
        """
        Download the primary document of a filing.
        
        Returns:
            Raw HTML content of the filing
        """
        accession_clean = filing.accession_number.replace("-", "")
        cik_clean = filing.cik.lstrip("0")
        url = (
            f"{self.ARCHIVES_URL}/{cik_clean}/{accession_clean}"
            f"/{filing.primary_document}"
        )
        logger.info(f"Downloading {filing.filing_type} from {url}")
        resp = self._get(url)
        return resp.text

    def get_filing_index(self, filing: Filing) -> List[Dict]:
        """
        Get the filing index (list of all documents in the filing).
        Useful for finding exhibits like Ex-99.1 earnings releases.
        
        Returns:
            List of dicts with keys: name, type, description, url
        """
        accession_clean = filing.accession_number.replace("-", "")
        cik_clean = filing.cik.lstrip("0")
        index_url = (
            f"{self.ARCHIVES_URL}/{cik_clean}/{accession_clean}/index.json"
        )
        resp = self._get(index_url)
        data = resp.json()

        documents = []
        for item in data.get("directory", {}).get("item", []):
            doc = {
                "name": item.get("name", ""),
                "type": item.get("type", ""),
                "description": item.get("description", ""),
                "url": (
                    f"{self.ARCHIVES_URL}/{cik_clean}/{accession_clean}"
                    f"/{item.get('name', '')}"
                ),
            }
            documents.append(doc)

        return documents

    def get_company_facts_metadata(self, cik: str) -> Dict:
        """
        Fetch structured company metadata from EDGAR Company Facts API.
        (Source 7: EDGAR Company Facts)

        Returns company info: name, tickers, exchanges, SIC code,
        state, fiscal year end, former names, etc.
        """
        info = self.get_company_info(cik)
        return {
            "cik": cik,
            "name": info.get("name", ""),
            "tickers": info.get("tickers", []),
            "exchanges": info.get("exchanges", []),
            "sic": info.get("sic", ""),
            "sic_description": info.get("sicDescription", ""),
            "state": info.get("stateOfIncorporation", ""),
            "fiscal_year_end": info.get("fiscalYearEnd", ""),
            "entity_type": info.get("entityType", ""),
            "category": info.get("category", ""),
            "former_names": [
                {"name": fn.get("name", ""), "from": fn.get("from", ""), "to": fn.get("to", "")}
                for fn in info.get("formerNames", [])
            ],
            "phone": info.get("phone", ""),
            "website": info.get("website", ""),
            "addresses": info.get("addresses", {}),
            "insider_transaction_for_owner_exists": info.get("insiderTransactionForOwnerExists", False),
            "insider_transaction_for_issuer_exists": info.get("insiderTransactionForIssuerExists", False),
        }

"""
Earnings Call Transcript Scraper (Source 4).

Fetches earnings call transcripts from free public sources.
Primary: Motley Fool free transcripts.
Fallback: SEC 8-K Item 2.02 earnings press releases.
"""

import re
import time
import logging
import requests
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 1.0  # Be polite to Motley Fool


class TranscriptScraper:
    """
    Scrape earnings call transcripts from Motley Fool.

    Usage:
        scraper = TranscriptScraper()
        urls = scraper.find_transcripts("AAPL", count=4)
        text = scraper.fetch_transcript(urls[0])
    """

    FOOL_SEARCH = "https://www.fool.com/quote/nasdaq/{ticker}/"
    FOOL_EARNINGS = "https://www.fool.com/earnings-call-transcripts/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        self._last_request = 0.0

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request = time.time()

    def _get(self, url: str) -> Optional[str]:
        """Fetch a URL with rate limiting. Returns HTML or None."""
        self._rate_limit()
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"HTTP {resp.status_code} for {url}")
            return None
        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

    def find_transcript_urls(self, ticker: str, count: int = 4) -> List[str]:
        """
        Search Motley Fool for earnings transcript URLs.

        Args:
            ticker: Stock ticker (e.g., "AAPL")
            count: Max transcripts to find

        Returns:
            List of transcript page URLs
        """
        # Search Google for Motley Fool transcripts for this ticker
        search_url = f"https://www.fool.com/earnings-call-transcripts/?q={ticker}"
        html = self._get(search_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        urls = []

        # Find transcript links
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/earnings/call-transcript/" in href or "earnings-call-transcript" in href:
                full_url = href if href.startswith("http") else f"https://www.fool.com{href}"
                if full_url not in urls:
                    urls.append(full_url)
                if len(urls) >= count:
                    break

        logger.info(f"Found {len(urls)} transcript URLs for {ticker}")
        return urls

    def fetch_transcript(self, url: str) -> Optional[Dict]:
        """
        Fetch and parse a single transcript page.

        Returns:
            Dict with keys: title, date, company, text, speakers, url
            or None if fetch fails
        """
        html = self._get(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")

        # Extract title
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Extract article body
        article = soup.find("article") or soup.find("div", class_=re.compile("article|content|transcript"))
        if not article:
            # Fallback: get main content area
            article = soup.find("main") or soup.body

        if not article:
            return None

        text = article.get_text(separator="\n", strip=True)

        # Try to extract date from title or meta
        date = ""
        date_match = re.search(r"(Q[1-4]\s+\d{4}|FY\s*\d{4})", title)
        if date_match:
            date = date_match.group(1)

        # Extract company name from title
        company = ""
        company_match = re.match(r"^(.+?)\s*\(", title)
        if company_match:
            company = company_match.group(1).strip()

        return {
            "title": title,
            "date": date,
            "company": company,
            "text": text,
            "url": url,
        }

    def fetch_from_8k(self, client, cik: str, count: int = 4) -> List[Dict]:
        """
        Fallback: Extract earnings press releases from 8-K Item 2.02 filings.

        Args:
            client: EdgarClient instance
            cik: Company CIK
            count: Number of 8-K filings to check

        Returns:
            List of transcript-like dicts from earnings releases
        """
        filings = client.get_filings(cik, filing_type="8-K", count=count * 3)

        results = []
        for filing in filings:
            # Item 2.02 = Results of Operations and Financial Condition
            if "2.02" in filing.items:
                try:
                    html = client.download_filing(filing)
                    soup = BeautifulSoup(html, "lxml")
                    for tag in soup(["script", "style"]):
                        tag.decompose()
                    text = soup.get_text(separator="\n", strip=True)

                    results.append({
                        "title": f"{filing.company_name} 8-K Earnings Release ({filing.filing_date})",
                        "date": filing.filing_date,
                        "company": filing.company_name,
                        "text": text,
                        "url": f"SEC EDGAR 8-K {filing.accession_number}",
                        "filing_type": "8-K",
                        "accession_number": filing.accession_number,
                    })

                    if len(results) >= count:
                        break
                except Exception as e:
                    logger.error(f"Failed to fetch 8-K {filing.accession_number}: {e}")

        logger.info(f"Found {len(results)} earnings releases from 8-K filings")
        return results

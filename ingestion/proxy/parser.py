"""
DEF 14A Proxy Statement Parser (Source 6).

Extracts from proxy statements:
- Board of Directors (names, roles, tenure, committees)
- Executive compensation (salary, bonus, stock awards)
- Related-party transactions
- Shareholder proposals
"""

import re
import logging
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ProxyParser:
    """Parse DEF 14A proxy statement HTML into structured sections."""

    # Key sections to extract from proxy statements
    SECTION_PATTERNS = {
        "board_directors": [
            r"board of directors",
            r"director nominees",
            r"election of directors",
            r"proposal.*election",
        ],
        "executive_compensation": [
            r"executive compensation",
            r"compensation discussion",
            r"summary compensation table",
            r"compensation of.*officers",
        ],
        "related_party": [
            r"related.?party",
            r"certain relationships",
            r"transactions with related",
            r"related person",
        ],
        "stock_ownership": [
            r"security ownership",
            r"beneficial ownership",
            r"stock ownership",
            r"principal stockholders",
        ],
        "audit_committee": [
            r"audit committee",
            r"report of.*audit",
        ],
        "shareholder_proposals": [
            r"shareholder proposal",
            r"stockholder proposal",
        ],
    }

    def parse(self, html: str, metadata: Dict) -> List[Dict]:
        """
        Parse proxy statement HTML into structured chunks.

        Args:
            html: Raw HTML of the DEF 14A filing
            metadata: Filing metadata (company_name, cik, filing_date, etc.)

        Returns:
            List of chunk dicts with text and metadata
        """
        soup = BeautifulSoup(html, "lxml")

        # Remove scripts, styles
        for tag in soup(["script", "style"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        chunks = []

        # Extract sections by pattern matching
        for section_name, patterns in self.SECTION_PATTERNS.items():
            section_text = self._extract_section(text, patterns)
            if section_text and len(section_text) > 100:
                # Chunk large sections
                section_chunks = self._chunk_text(section_text, max_size=800, overlap=150)
                for i, chunk in enumerate(section_chunks):
                    chunks.append({
                        "text": chunk,
                        "metadata": {
                            **metadata,
                            "source": "sec_edgar",
                            "category": "proxy_statement",
                            "section": section_name,
                            "chunk_index": i,
                            "total_chunks": len(section_chunks),
                        }
                    })

        # If no sections matched, chunk the whole document
        if not chunks:
            all_chunks = self._chunk_text(text, max_size=800, overlap=150)
            for i, chunk in enumerate(all_chunks):
                chunks.append({
                    "text": chunk,
                    "metadata": {
                        **metadata,
                        "source": "sec_edgar",
                        "category": "proxy_statement",
                        "section": "full_document",
                        "chunk_index": i,
                        "total_chunks": len(all_chunks),
                    }
                })

        logger.info(
            f"Parsed proxy statement: {len(chunks)} chunks "
            f"for {metadata.get('company_name', 'Unknown')}"
        )
        return chunks

    def _extract_section(self, text: str, patterns: List[str]) -> Optional[str]:
        """Extract a section from text using regex patterns."""
        text_lower = text.lower()
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                start = match.start()
                # Find the next major section heading (rough heuristic)
                # Look for the next all-caps line or next pattern match
                remaining = text[start:]
                # Take up to 10000 chars or until next section
                end = min(len(remaining), 10000)

                # Try to find a natural break
                for break_pattern in [r"\n\s*PROPOSAL", r"\n\s*ITEM\s+\d", r"\n\s*PART\s+"]:
                    break_match = re.search(break_pattern, remaining[500:], re.IGNORECASE)
                    if break_match:
                        end = min(end, 500 + break_match.start())
                        break

                return remaining[:end].strip()
        return None

    def _chunk_text(self, text: str, max_size: int = 800, overlap: int = 150) -> List[str]:
        """Split text into overlapping chunks."""
        if len(text) <= max_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + max_size
            # Try to break at a sentence boundary
            if end < len(text):
                last_period = text[start:end].rfind(". ")
                if last_period > max_size // 2:
                    end = start + last_period + 2
            chunks.append(text[start:end].strip())
            start = end - overlap

        return [c for c in chunks if c]

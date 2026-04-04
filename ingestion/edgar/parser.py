"""
SEC Filing HTML Parser

Handles the messy reality of EDGAR HTML:
- Strips XBRL inline tags (ix:nonfraction, ix:nonnumeric, etc.)
- Extracts tables into structured format (for financial statements)
- Cleans up whitespace and formatting artifacts
- Preserves document structure for section extraction
"""

import re
import logging
import warnings
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)


@dataclass
class ParsedTable:
    """A table extracted from a filing."""
    headers: List[str]
    rows: List[List[str]]
    caption: str = ""
    section: str = ""  # Which Item this table belongs to

    def to_text(self) -> str:
        """Convert table to readable text format for embedding."""
        lines = []
        if self.caption:
            lines.append(f"Table: {self.caption}")
        if self.headers:
            lines.append(" | ".join(self.headers))
            lines.append("-" * 40)
        for row in self.rows:
            lines.append(" | ".join(row))
        return "\n".join(lines)


@dataclass
class ParsedFiling:
    """Result of parsing a filing HTML document."""
    full_text: str
    tables: List[ParsedTable] = field(default_factory=list)
    footnotes: List[str] = field(default_factory=list)
    exhibits: List[Dict] = field(default_factory=list)


class FilingParser:
    """
    Parses SEC filing HTML into clean text + structured tables.
    
    Usage:
        parser = FilingParser()
        result = parser.parse(html_content)
        print(result.full_text)
        for table in result.tables:
            print(table.to_text())
    """

    # XBRL inline tags to strip (keep their text content)
    XBRL_TAGS = re.compile(
        r"</?ix:(non(?:fraction|numeric)|continuation|header|hidden|references|resources|"
        r"tuple|context|unit|footnote)[^>]*>",
        re.IGNORECASE,
    )

    # Common noise patterns in EDGAR HTML
    NOISE_PATTERNS = [
        re.compile(r"<!\-\-.*?\-\->", re.DOTALL),  # HTML comments
        re.compile(r"&nbsp;"),  # Non-breaking spaces
        re.compile(r"\xa0"),  # Unicode NBSP
    ]

    def parse(self, html: str) -> ParsedFiling:
        """
        Parse a filing HTML document.
        
        Args:
            html: Raw HTML content from EDGAR
            
        Returns:
            ParsedFiling with clean text, tables, and footnotes
        """
        # Pre-clean: strip XBRL tags but keep text content
        cleaned_html = self.XBRL_TAGS.sub("", html)
        for pattern in self.NOISE_PATTERNS:
            cleaned_html = pattern.sub(" ", cleaned_html)

        soup = BeautifulSoup(cleaned_html, "lxml")

        # Remove script/style tags entirely
        for tag in soup.find_all(["script", "style", "meta", "link"]):
            tag.decompose()

        # Extract tables before converting to text
        tables = self._extract_tables(soup)

        # Extract footnotes
        footnotes = self._extract_footnotes(soup)

        # Get clean text
        full_text = self._extract_text(soup)

        return ParsedFiling(
            full_text=full_text,
            tables=tables,
            footnotes=footnotes,
        )

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extract clean text preserving paragraph structure."""
        # Get text with newlines at block boundaries
        text = soup.get_text(separator="\n")

        # Clean up excessive whitespace
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped:
                # Collapse internal whitespace
                stripped = re.sub(r"\s+", " ", stripped)
                lines.append(stripped)

        # Join with double newlines for paragraph separation
        text = "\n\n".join(lines)

        # Collapse runs of 3+ newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _extract_tables(self, soup: BeautifulSoup) -> List[ParsedTable]:
        """Extract all tables from the filing."""
        tables = []
        for table_tag in soup.find_all("table"):
            parsed = self._parse_table(table_tag)
            if parsed and len(parsed.rows) > 0:
                tables.append(parsed)
        return tables

    def _parse_table(self, table_tag: Tag) -> Optional[ParsedTable]:
        """Parse a single HTML table into structured format."""
        rows_data = []
        headers = []

        # Look for caption
        caption_tag = table_tag.find("caption")
        caption = caption_tag.get_text(strip=True) if caption_tag else ""

        for row in table_tag.find_all("tr"):
            cells = row.find_all(["th", "td"])
            cell_texts = []
            is_header = all(c.name == "th" for c in cells) if cells else False

            for cell in cells:
                text = cell.get_text(strip=True)
                text = re.sub(r"\s+", " ", text)
                cell_texts.append(text)

            if not any(cell_texts):  # Skip empty rows
                continue

            if is_header and not headers:
                headers = cell_texts
            else:
                rows_data.append(cell_texts)

        if not rows_data:
            return None

        return ParsedTable(
            headers=headers,
            rows=rows_data,
            caption=caption,
        )

    def _extract_footnotes(self, soup: BeautifulSoup) -> List[str]:
        """
        Extract footnotes from financial statements.
        
        Footnotes are typically in smaller text after financial tables,
        or marked with specific patterns like (1), (2), etc.
        """
        footnotes = []

        # Look for common footnote patterns
        # Pattern 1: Elements with "footnote" in class/id
        for el in soup.find_all(attrs={"class": re.compile(r"footnote", re.I)}):
            text = el.get_text(strip=True)
            if text and len(text) > 10:
                footnotes.append(text)

        # Pattern 2: Superscript references followed by text
        for sup in soup.find_all("sup"):
            parent = sup.parent
            if parent:
                text = parent.get_text(strip=True)
                if text and len(text) > 20 and text not in footnotes:
                    footnotes.append(text)

        return footnotes

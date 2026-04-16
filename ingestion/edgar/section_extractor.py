"""
SEC Filing Section Extractor — Book RAG / Page Indexing

Extracts Item-level sections from 10-K, 10-Q, and 8-K filings.
This is critical for Book RAG: we index by Item number so retrieval
can target specific sections (e.g., "Item 1A Risk Factors").

10-K Items:
    Item 1   - Business
    Item 1A  - Risk Factors
    Item 1B  - Unresolved Staff Comments
    Item 1C  - Cybersecurity
    Item 2   - Properties
    Item 3   - Legal Proceedings
    Item 4   - Mine Safety Disclosures
    Item 5   - Market for Registrant's Common Equity
    Item 6   - [Reserved]
    Item 7   - MD&A (Management's Discussion and Analysis)
    Item 7A  - Quantitative and Qualitative Disclosures About Market Risk
    Item 8   - Financial Statements and Supplementary Data
    Item 9   - Changes in and Disagreements with Accountants
    Item 9A  - Controls and Procedures
    Item 9B  - Other Information
    Item 10  - Directors, Executive Officers and Corporate Governance
    Item 11  - Executive Compensation
    Item 12  - Security Ownership
    Item 13  - Certain Relationships and Related Transactions
    Item 14  - Principal Accountant Fees and Services
    Item 15  - Exhibits and Financial Statement Schedules

10-Q Items:
    Part I, Item 1  - Financial Statements
    Part I, Item 2  - MD&A
    Part I, Item 3  - Quantitative Market Risk
    Part I, Item 4  - Controls and Procedures
    Part II, Item 1 - Legal Proceedings
    Part II, Item 1A - Risk Factors
    Part II, Item 2 - Unregistered Sales
    Part II, Item 5 - Other Information
    Part II, Item 6 - Exhibits

8-K Items:
    Item 2.02 - Results of Operations (Earnings Release)
    Item 5.02 - Departure/Election of Directors or Officers
    Item 7.01 - Regulation FD Disclosure
    Item 8.01 - Other Events
    Item 9.01 - Financial Statements and Exhibits
"""

import re
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FilingSection:
    """A single section extracted from a filing."""
    item_number: str          # e.g., "1A", "7", "2.02"
    item_title: str           # e.g., "Risk Factors"
    content: str              # Full text of the section
    filing_type: str          # "10-K", "10-Q", "8-K"
    company_name: str
    cik: str
    filing_date: str
    period_of_report: str
    accession_number: str
    tables: List[Dict] = field(default_factory=list)
    footnotes: List[str] = field(default_factory=list)
    char_start: int = 0       # Position in original document
    char_end: int = 0

    @property
    def section_id(self) -> str:
        """Unique identifier for this section."""
        return (
            f"{self.cik}_{self.filing_type}_{self.filing_date}"
            f"_item{self.item_number}"
        )

    def to_metadata(self) -> Dict:
        """Metadata dict for vector store indexing."""
        return {
            "source": "sec_edgar",
            "filing_type": self.filing_type,
            "item_number": self.item_number,
            "item_title": self.item_title,
            "company_name": self.company_name,
            "cik": self.cik,
            "filing_date": self.filing_date,
            "period_of_report": self.period_of_report,
            "accession_number": self.accession_number,
            "section_id": self.section_id,
            "has_tables": len(self.tables) > 0,
            "has_footnotes": len(self.footnotes) > 0,
            "category": "sec_filing",
        }


# ─── Item patterns for each filing type ──────────────────────────────────────

# 10-K Item headers — these appear as headings in the HTML
_10K_ITEMS = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Reserved",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
}

_10Q_ITEMS = {
    "P1-1": "Financial Statements",
    "P1-2": "Management's Discussion and Analysis",
    "P1-3": "Quantitative and Qualitative Disclosures About Market Risk",
    "P1-4": "Controls and Procedures",
    "P2-1": "Legal Proceedings",
    "P2-1A": "Risk Factors",
    "P2-2": "Unregistered Sales of Equity Securities",
    "P2-5": "Other Information",
    "P2-6": "Exhibits",
}

_8K_ITEMS = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure/Election of Directors or Principal Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}


class SectionExtractor:
    """
    Extracts Item-level sections from parsed filing text.
    
    This is the core of Book RAG for SEC filings — each section becomes
    a separately indexed document with rich metadata.
    
    Usage:
        extractor = SectionExtractor()
        sections = extractor.extract(
            text=parsed_filing.full_text,
            filing_type="10-K",
            metadata={...}
        )
    """

    def __init__(self):
        # Build regex patterns for each filing type
        self._10k_pattern = self._build_item_pattern(_10K_ITEMS)
        self._10q_pattern = self._build_10q_pattern()
        self._8k_pattern = self._build_8k_pattern()

    def _build_item_pattern(self, items: Dict[str, str]) -> re.Pattern:
        """
        Build regex to match Item headers in filing text.
        
        Matches patterns like:
            "Item 1A. Risk Factors"
            "ITEM 1A — RISK FACTORS"
            "Item 1A: Risk Factors"
            "ITEM 1A RISK FACTORS"
        """
        item_nums = "|".join(re.escape(k) for k in sorted(items.keys(), key=len, reverse=True))
        pattern = (
            rf"(?:^|\n)"
            rf"[\s]*"
            rf"(?:ITEM|Item)\s+"
            rf"({item_nums})"
            rf"[\s]*[.:\-—]?\s*"
            rf"([^\n]{{0,100}})"
            rf"[\s]*(?:\n|$)"
        )
        return re.compile(pattern, re.IGNORECASE | re.MULTILINE)

    def _build_10q_pattern(self) -> re.Pattern:
        """Build pattern for 10-Q which has Part I/Part II structure."""
        pattern = (
            r"(?:^|\n)"
            r"[\s]*"
            r"(?:PART|Part)\s+(I{1,2}|1|2)"
            r"[\s]*[,\-—]?\s*"
            r"(?:ITEM|Item)\s+"
            r"(\d+[A-Za-z]?)"
            r"[\s]*[.:\-—]?\s*"
            r"([^\n]{0,100})"
            r"[\s]*(?:\n|$)"
        )
        return re.compile(pattern, re.IGNORECASE | re.MULTILINE)

    def _build_8k_pattern(self) -> re.Pattern:
        """Build pattern for 8-K items (e.g., Item 2.02)."""
        item_nums = "|".join(
            re.escape(k) for k in sorted(_8K_ITEMS.keys(), key=len, reverse=True)
        )
        pattern = (
            rf"(?:^|\n)"
            rf"[\s]*"
            rf"(?:ITEM|Item)\s+"
            rf"({item_nums})"
            rf"[\s]*[.:\-—]?\s*"
            rf"([^\n]{{0,100}})"
            rf"[\s]*(?:\n|$)"
        )
        return re.compile(pattern, re.IGNORECASE | re.MULTILINE)

    def extract(
        self,
        text: str,
        filing_type: str,
        metadata: Dict,
        tables: Optional[List] = None,
        footnotes: Optional[List[str]] = None,
    ) -> List[FilingSection]:
        """
        Extract sections from filing text.
        
        Args:
            text: Clean text from FilingParser
            filing_type: "10-K", "10-Q", or "8-K"
            metadata: Dict with company_name, cik, filing_date, etc.
            tables: Optional parsed tables to attach to sections
            footnotes: Optional footnotes to attach to sections
            
        Returns:
            List of FilingSection objects
        """
        if filing_type in ("10-K", "10-K/A"):
            return self._extract_10k(text, metadata, tables, footnotes)
        elif filing_type in ("10-Q", "10-Q/A"):
            return self._extract_10q(text, metadata, tables, footnotes)
        elif filing_type in ("8-K", "8-K/A"):
            return self._extract_8k(text, metadata, tables, footnotes)
        else:
            logger.warning(f"Unknown filing type: {filing_type}, treating as raw text")
            return self._extract_raw(text, filing_type, metadata)

    def _extract_10k(
        self, text: str, metadata: Dict,
        tables: Optional[List] = None, footnotes: Optional[List[str]] = None,
    ) -> List[FilingSection]:
        """Extract Item sections from a 10-K filing."""
        matches = list(self._10k_pattern.finditer(text))
        if not matches:
            logger.warning("No Item headers found in 10-K, returning as single section")
            return self._extract_raw(text, "10-K", metadata)

        sections = []
        for i, match in enumerate(matches):
            item_num = match.group(1).upper()
            item_title_raw = match.group(2).strip()

            # Use known title if raw is empty or just noise
            item_title = _10K_ITEMS.get(item_num, item_title_raw or f"Item {item_num}")

            # Content runs from end of this header to start of next header
            content_start = match.end()
            content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[content_start:content_end].strip()

            if len(content) < 50:  # Skip near-empty sections
                continue

            section = FilingSection(
                item_number=item_num,
                item_title=item_title,
                content=content,
                filing_type="10-K",
                company_name=metadata.get("company_name", ""),
                cik=metadata.get("cik", ""),
                filing_date=metadata.get("filing_date", ""),
                period_of_report=metadata.get("period_of_report", ""),
                accession_number=metadata.get("accession_number", ""),
                char_start=content_start,
                char_end=content_end,
                footnotes=footnotes or [],
            )
            sections.append(section)

        logger.info(f"Extracted {len(sections)} sections from 10-K")
        return sections

    def _extract_10q(
        self, text: str, metadata: Dict,
        tables: Optional[List] = None, footnotes: Optional[List[str]] = None,
    ) -> List[FilingSection]:
        """Extract sections from a 10-Q filing."""
        matches = list(self._10q_pattern.finditer(text))
        if not matches:
            # Fallback: try 10-K pattern (some 10-Qs don't use Part prefix)
            matches = list(self._10k_pattern.finditer(text))
            if not matches:
                logger.warning("No Item headers found in 10-Q")
                return self._extract_raw(text, "10-Q", metadata)

        sections = []
        for i, match in enumerate(matches):
            groups = match.groups()
            if len(groups) == 3:
                # Part + Item format
                part = groups[0]
                item_num = groups[1]
                item_title_raw = groups[2].strip()
                part_num = "1" if part in ("I", "1") else "2"
                item_key = f"P{part_num}-{item_num.upper()}"
            else:
                # Fallback to 10-K style
                item_num = groups[0].upper()
                item_title_raw = groups[1].strip() if len(groups) > 1 else ""
                item_key = item_num

            item_title = _10Q_ITEMS.get(item_key, item_title_raw or f"Item {item_key}")

            content_start = match.end()
            content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[content_start:content_end].strip()

            if len(content) < 50:
                continue

            section = FilingSection(
                item_number=item_key,
                item_title=item_title,
                content=content,
                filing_type="10-Q",
                company_name=metadata.get("company_name", ""),
                cik=metadata.get("cik", ""),
                filing_date=metadata.get("filing_date", ""),
                period_of_report=metadata.get("period_of_report", ""),
                accession_number=metadata.get("accession_number", ""),
                char_start=content_start,
                char_end=content_end,
                footnotes=footnotes or [],
            )
            sections.append(section)

        logger.info(f"Extracted {len(sections)} sections from 10-Q")
        return sections

    def _extract_8k(
        self, text: str, metadata: Dict,
        tables: Optional[List] = None, footnotes: Optional[List[str]] = None,
    ) -> List[FilingSection]:
        """Extract sections from an 8-K filing."""
        matches = list(self._8k_pattern.finditer(text))
        if not matches:
            logger.warning("No Item headers found in 8-K")
            return self._extract_raw(text, "8-K", metadata)

        sections = []
        for i, match in enumerate(matches):
            item_num = match.group(1)
            item_title_raw = match.group(2).strip()
            item_title = _8K_ITEMS.get(item_num, item_title_raw or f"Item {item_num}")

            content_start = match.end()
            content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[content_start:content_end].strip()

            if len(content) < 20:  # 8-Ks can be shorter
                continue

            section = FilingSection(
                item_number=item_num,
                item_title=item_title,
                content=content,
                filing_type="8-K",
                company_name=metadata.get("company_name", ""),
                cik=metadata.get("cik", ""),
                filing_date=metadata.get("filing_date", ""),
                period_of_report=metadata.get("period_of_report", ""),
                accession_number=metadata.get("accession_number", ""),
                char_start=content_start,
                char_end=content_end,
            )
            sections.append(section)

        logger.info(f"Extracted {len(sections)} sections from 8-K")
        return sections

    def _extract_raw(
        self, text: str, filing_type: str, metadata: Dict
    ) -> List[FilingSection]:
        """Fallback: return entire filing as a single section."""
        return [
            FilingSection(
                item_number="FULL",
                item_title=f"Full {filing_type} Filing",
                content=text,
                filing_type=filing_type,
                company_name=metadata.get("company_name", ""),
                cik=metadata.get("cik", ""),
                filing_date=metadata.get("filing_date", ""),
                period_of_report=metadata.get("period_of_report", ""),
                accession_number=metadata.get("accession_number", ""),
                char_start=0,
                char_end=len(text),
            )
        ]

"""
EDGAR Ingestion Pipeline — Orchestrates the full flow:

1. Resolve ticker → CIK
2. Fetch filing list from EDGAR
3. Download each filing HTML
4. Parse HTML → clean text + tables + footnotes
5. Extract Item-level sections (Book RAG)
6. Chunk sections using parent-child strategy
7. Store in vector store with rich metadata

This produces documents indexed by:
  - Company (CIK, name, ticker)
  - Filing type (10-K, 10-Q, 8-K)
  - Filing date and period
  - Item number and title
  - Section position in original document
"""

import os
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from .client import EdgarClient, Filing
from .parser import FilingParser, ParsedFiling
from .section_extractor import SectionExtractor, FilingSection

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Summary of an ingestion run."""
    company: str
    ticker: str
    cik: str
    filings_processed: int = 0
    sections_extracted: int = 0
    chunks_created: int = 0
    errors: List[str] = field(default_factory=list)


class EdgarIngestionPipeline:
    """
    End-to-end pipeline for ingesting SEC filings into the RAG system.
    
    Usage:
        pipeline = EdgarIngestionPipeline(
            user_agent="MAOracle research@example.com",
            output_dir="data/edgar"
        )
        
        # Ingest 10-K filings for Apple
        result = pipeline.ingest_company(
            ticker="AAPL",
            filing_types=["10-K", "10-Q", "8-K"],
            count=5,
        )
        
        # Get chunked documents ready for embedding
        documents = pipeline.get_documents()
    """

    def __init__(
        self,
        user_agent: str,
        output_dir: str = "data/edgar",
        parent_chunk_size: int = 3000,
        parent_chunk_overlap: int = 500,
        child_chunk_size: int = 500,
        child_chunk_overlap: int = 100,
    ):
        self.client = EdgarClient(user_agent=user_agent)
        self.parser = FilingParser()
        self.extractor = SectionExtractor()
        self.output_dir = output_dir
        self.parent_chunk_size = parent_chunk_size
        self.parent_chunk_overlap = parent_chunk_overlap
        self.child_chunk_size = child_chunk_size
        self.child_chunk_overlap = child_chunk_overlap

        # Accumulated documents from all ingestion runs
        self._sections: List[FilingSection] = []
        self._documents: List[Dict] = []  # {text, metadata} ready for embedding

        os.makedirs(output_dir, exist_ok=True)

    def ingest_company(
        self,
        ticker: str,
        filing_types: Optional[List[str]] = None,
        count: int = 5,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        save_raw: bool = True,
    ) -> IngestionResult:
        """
        Ingest all specified filings for a company.
        
        Args:
            ticker: Stock ticker (e.g., "AAPL")
            filing_types: List of filing types to ingest. Default: ["10-K"]
            count: Number of filings per type
            start_date: Filter filings after this date (YYYY-MM-DD)
            end_date: Filter filings before this date (YYYY-MM-DD)
            save_raw: Whether to save raw HTML to disk
            
        Returns:
            IngestionResult with summary stats
        """
        filing_types = filing_types or ["10-K"]

        # Resolve ticker to CIK
        try:
            cik = self.client.get_cik(ticker)
        except ValueError as e:
            return IngestionResult(
                company="Unknown", ticker=ticker, cik="",
                errors=[str(e)]
            )

        result = IngestionResult(company="", ticker=ticker, cik=cik)

        for filing_type in filing_types:
            try:
                filings = self.client.get_filings(
                    cik=cik,
                    filing_type=filing_type,
                    count=count,
                    start_date=start_date,
                    end_date=end_date,
                )
                if not filings:
                    logger.warning(f"No {filing_type} filings found for {ticker}")
                    continue

                result.company = filings[0].company_name

                for filing in filings:
                    try:
                        sections = self._process_filing(filing, save_raw)
                        self._sections.extend(sections)
                        result.filings_processed += 1
                        result.sections_extracted += len(sections)

                        # Chunk each section
                        for section in sections:
                            chunks = self._chunk_section(section)
                            self._documents.extend(chunks)
                            result.chunks_created += len(chunks)

                    except Exception as e:
                        error_msg = (
                            f"Error processing {filing_type} "
                            f"({filing.filing_date}): {e}"
                        )
                        logger.error(error_msg)
                        result.errors.append(error_msg)

            except Exception as e:
                error_msg = f"Error fetching {filing_type} list: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        logger.info(
            f"Ingestion complete for {ticker}: "
            f"{result.filings_processed} filings, "
            f"{result.sections_extracted} sections, "
            f"{result.chunks_created} chunks"
        )
        return result

    def _process_filing(
        self, filing: Filing, save_raw: bool = True
    ) -> List[FilingSection]:
        """Download, parse, and extract sections from a single filing."""
        logger.info(
            f"Processing {filing.filing_type} for {filing.company_name} "
            f"({filing.filing_date})"
        )

        # Download
        html = self.client.download_filing(filing)

        # Optionally save raw HTML
        if save_raw:
            self._save_raw(filing, html)

        # Parse
        parsed = self.parser.parse(html)

        # Extract sections
        metadata = {
            "company_name": filing.company_name,
            "cik": filing.cik,
            "filing_date": filing.filing_date,
            "period_of_report": filing.period_of_report,
            "accession_number": filing.accession_number,
        }
        sections = self.extractor.extract(
            text=parsed.full_text,
            filing_type=filing.filing_type,
            metadata=metadata,
            tables=parsed.tables,
            footnotes=parsed.footnotes,
        )

        return sections

    def _chunk_section(self, section: FilingSection) -> List[Dict]:
        """
        Chunk a filing section using parent-child strategy.
        
        Each chunk gets the section's metadata plus chunk-level info.
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        # For short sections, don't chunk
        if len(section.content) <= self.child_chunk_size:
            return [{
                "text": section.content,
                "metadata": {
                    **section.to_metadata(),
                    "chunk_type": "full_section",
                    "chunk_index": 0,
                    "total_chunks": 1,
                },
            }]

        # Parent-child chunking
        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.parent_chunk_size,
            chunk_overlap=self.parent_chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.child_chunk_size,
            chunk_overlap=self.child_chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        parent_chunks = parent_splitter.split_text(section.content)
        documents = []

        for p_idx, parent_text in enumerate(parent_chunks):
            child_chunks = child_splitter.split_text(parent_text)
            for c_idx, child_text in enumerate(child_chunks):
                doc = {
                    "text": child_text,
                    "metadata": {
                        **section.to_metadata(),
                        "chunk_type": "child",
                        "parent_index": p_idx,
                        "chunk_index": c_idx,
                        "total_parent_chunks": len(parent_chunks),
                        "parent_text": parent_text,  # Store parent for context
                    },
                }
                documents.append(doc)

        return documents

    def _save_raw(self, filing: Filing, html: str):
        """Save raw filing HTML to disk for debugging/reprocessing."""
        company_dir = os.path.join(
            self.output_dir,
            filing.cik,
            filing.filing_type.replace("/", "_"),
        )
        os.makedirs(company_dir, exist_ok=True)

        filename = f"{filing.filing_date}_{filing.accession_number}.html"
        filepath = os.path.join(company_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        # Save metadata alongside
        meta_path = filepath.replace(".html", "_meta.json")
        meta = {
            "company_name": filing.company_name,
            "cik": filing.cik,
            "filing_type": filing.filing_type,
            "filing_date": filing.filing_date,
            "period_of_report": filing.period_of_report,
            "accession_number": filing.accession_number,
            "primary_document": filing.primary_document,
            "items": filing.items,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def get_sections(self) -> List[FilingSection]:
        """Get all extracted sections from all ingestion runs."""
        return self._sections

    def get_documents(self) -> List[Dict]:
        """Get all chunked documents ready for embedding."""
        return self._documents

    def clear(self):
        """Clear accumulated sections and documents."""
        self._sections.clear()
        self._documents.clear()

    def get_stats(self) -> Dict:
        """Get summary statistics of ingested data."""
        companies = set()
        filing_types = {}
        items = {}

        for section in self._sections:
            companies.add(section.company_name)
            ft = section.filing_type
            filing_types[ft] = filing_types.get(ft, 0) + 1
            items[section.item_number] = items.get(section.item_number, 0) + 1

        return {
            "total_sections": len(self._sections),
            "total_chunks": len(self._documents),
            "companies": list(companies),
            "filing_types": filing_types,
            "items_breakdown": items,
        }

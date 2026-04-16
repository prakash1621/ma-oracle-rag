"""
SEC EDGAR Ingestion Pipeline

Modules:
- client: EDGAR API client for fetching filings
- parser: HTML parser for extracting text and tables from filings
- section_extractor: Item-level section extraction for Book RAG
- pipeline: Orchestrates the full ingestion flow
"""

from .client import EdgarClient
from .parser import FilingParser
from .section_extractor import SectionExtractor
from .pipeline import EdgarIngestionPipeline

__all__ = [
    "EdgarClient",
    "FilingParser",
    "SectionExtractor",
    "EdgarIngestionPipeline",
]

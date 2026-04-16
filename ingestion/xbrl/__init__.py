"""XBRL structured financial data ingestion pipeline."""

from .client import XBRLClient
from .parser import XBRLParser
from .storage import XBRLStorage
from .pipeline import XBRLPipeline

__all__ = ["XBRLClient", "XBRLParser", "XBRLStorage", "XBRLPipeline"]

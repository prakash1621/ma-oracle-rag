"""USPTO Patent ingestion (Source 5)."""

from .client import PatentClient
from .pipeline import PatentPipeline

__all__ = ["PatentClient", "PatentPipeline"]

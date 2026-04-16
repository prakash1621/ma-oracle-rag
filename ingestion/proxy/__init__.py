"""SEC DEF 14A Proxy Statement ingestion (Source 6)."""

from .parser import ProxyParser
from .pipeline import ProxyPipeline

__all__ = ["ProxyParser", "ProxyPipeline"]

"""Unified configuration for the NL2SQL service.

Loading strategy:
1. Load .env via python-dotenv
2. Parse config.yaml with pyyaml
3. Environment variables override config.yaml values where specified
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env from repo root (step 1)
load_dotenv()

# Repo-root-relative path to the shared config file
_CONFIG_YAML_PATH = Path("config.yaml")


def _load_yaml(path: Path = _CONFIG_YAML_PATH) -> dict[str, Any]:
    """Parse config.yaml and return the full dict (step 2)."""
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _deep_get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts: _deep_get(cfg, 'a', 'b', 'c')."""
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)  # type: ignore[assignment]
    return d


@dataclass(frozen=True)
class Settings:
    # Database
    db_path: str = "output/xbrl/financials.db"

    # LLM
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    groq_api_key: str | None = None

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    max_rows: int = 200

    # Memory
    memory_search_limit: int = 4
    memory_namespace: str = "nl2sql-memory"

    # Pinecone
    pinecone_api_key: str | None = None
    pinecone_index_name: str = "ma-oracle-cap"
    pinecone_embed_model: str = "multilingual-e5-large"


def get_settings(yaml_path: Path | None = None) -> Settings:
    """Build a Settings instance from config.yaml + env-var overrides.

    Parameters
    ----------
    yaml_path : Path | None
        Override the default config.yaml location (useful for testing).
    """
    cfg = _load_yaml(yaml_path or _CONFIG_YAML_PATH)

    nl2sql = cfg.get("nl2sql", {}) or {}

    # --- Resolve each field: env var > config.yaml > dataclass default ---

    db_path = os.environ.get("DB_PATH") or nl2sql.get("db_path") or Settings.db_path
    llm_base_url = (
        os.environ.get("LLM_BASE_URL")
        or nl2sql.get("llm_base_url")
        or Settings.llm_base_url
    )
    llm_model = (
        os.environ.get("LLM_MODEL")
        or nl2sql.get("llm_model")
        or Settings.llm_model
    )
    groq_api_key = (
        os.environ.get("GROQ_API_KEY")
        or nl2sql.get("groq_api_key")
        or Settings.groq_api_key
    )

    # Pick the right API key based on the LLM base URL
    llm_api_key = groq_api_key
    if "openai.com" in (llm_base_url or ""):
        llm_api_key = os.environ.get("OPENAI_API_KEY") or groq_api_key

    host = nl2sql.get("host") or Settings.host
    port = int(nl2sql.get("port", Settings.port))
    max_rows = int(nl2sql.get("max_rows", Settings.max_rows))
    memory_search_limit = int(
        nl2sql.get("memory_search_limit", Settings.memory_search_limit)
    )
    memory_namespace = nl2sql.get("memory_namespace") or Settings.memory_namespace

    pinecone_api_key = (
        os.environ.get("PINECONE_API_KEY")
        or _deep_get(cfg, "vector_store", "pinecone", "api_key")
        or Settings.pinecone_api_key
    )
    pinecone_index_name = (
        _deep_get(cfg, "vector_store", "pinecone", "index_name")
        or Settings.pinecone_index_name
    )
    pinecone_embed_model = (
        _deep_get(cfg, "embedding", "pinecone", "model_name")
        or Settings.pinecone_embed_model
    )

    return Settings(
        db_path=db_path,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        groq_api_key=llm_api_key,
        host=host,
        port=port,
        max_rows=max_rows,
        memory_search_limit=memory_search_limit,
        memory_namespace=memory_namespace,
        pinecone_api_key=pinecone_api_key,
        pinecone_index_name=pinecone_index_name,
        pinecone_embed_model=pinecone_embed_model,
    )

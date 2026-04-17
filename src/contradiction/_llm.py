"""LLM client factory — config-driven, config.yaml is the single source of truth.

Provider, model, and base URL are resolved exclusively from config.yaml.
API keys are still read from environment variables (e.g. GROQ_API_KEY)
because they are secrets that must not live in config files.

Public API:
    from src.contradiction._llm import build_llm_client, resolve_llm_config
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# src/contradiction/_llm.py  →  parents[2] is the repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"


def _load_repo_dotenv() -> None:
    if load_dotenv is not None:
        load_dotenv(_REPO_ROOT / ".env")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def resolve_llm_config(config_path: Path | None = None) -> dict[str, str]:
    """Resolve LLM provider settings exclusively from config.yaml.

    The provider, model, and base URL are read only from the config file.
    No environment variable overrides are applied so that the configuration
    is fully determined by config.yaml.
    API keys are still read from environment variables (e.g. GROQ_API_KEY)
    because they are secrets and must not live in config files.
    """
    _load_repo_dotenv()
    cfg = _load_yaml(config_path or _CONFIG_PATH)
    llm_cfg = cfg.get("llm", {}) or {}

    # Provider comes ONLY from config.yaml
    provider = (llm_cfg.get("provider") or "groq").lower()

    provider_cfg = llm_cfg.get(provider, {}) or {}
    default_base_urls = {
        "groq": "https://api.groq.com/openai/v1",
        "openai": "https://api.openai.com/v1",
        "ollama": "http://localhost:11434/v1",
    }
    api_key_envs = {
        "groq": ("GROQ_API_KEY", "OPENAI_API_KEY"),
        "openai": ("OPENAI_API_KEY",),
        "ollama": ("OPENAI_API_KEY",),
    }

    # API key still pulled from env (secrets should not be in config files)
    api_key = None
    for env_name in api_key_envs.get(provider, ("OPENAI_API_KEY", "GROQ_API_KEY")):
        api_key = _first_non_empty(api_key, os.environ.get(env_name))
    api_key = _first_non_empty(api_key, provider_cfg.get("api_key"))

    # Model and base_url come ONLY from config.yaml
    return {
        "provider": provider,
        "api_key": api_key or "",
        "base_url": _first_non_empty(
            provider_cfg.get("base_url"),
            default_base_urls.get(provider),
        ) or "",
        "model": _first_non_empty(
            provider_cfg.get("deployment_name"),
            provider_cfg.get("model_name"),
        ) or "",
    }


def build_llm_client(config_path: Path | None = None):
    """Build the active LLM client and return (client, model_name).

    Provider, model, and base URL are resolved exclusively from config.yaml.
    Only the API key is read from environment variables.
    """
    resolved = resolve_llm_config(config_path)

    from openai import OpenAI

    if resolved["provider"] != "ollama" and not resolved["api_key"]:
        raise RuntimeError(
            f"Missing API key for LLM provider '{resolved['provider']}'. "
            "Set the matching environment variable (e.g. GROQ_API_KEY)."
        )
    if not resolved["model"]:
        raise RuntimeError(
            f"Missing model name for LLM provider '{resolved['provider']}'. "
            "Set llm.<provider>.model_name in config.yaml."
        )

    client = OpenAI(
        base_url=resolved["base_url"] or None,
        api_key=resolved["api_key"] or "placeholder",
    )
    return client, resolved["model"]

"""
Provider factory — creates embeddings based on config.yaml.
Teammates can switch providers by editing config.yaml.
"""

import os
import yaml
import logging

logger = logging.getLogger(__name__)

_config = None

def _load_config():
    global _config
    if _config is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(config_path) as f:
            _config = yaml.safe_load(f)
    return _config


def get_embeddings():
    """Create embeddings based on config.yaml provider setting."""
    config = _load_config()
    embed_cfg = config.get("embedding", {})
    provider = os.environ.get("EMBEDDING_PROVIDER", embed_cfg.get("provider", "bedrock"))

    if provider == "bedrock":
        import boto3
        from langchain_aws import BedrockEmbeddings
        cfg = embed_cfg.get("bedrock", {})
        client = boto3.client("bedrock-runtime", region_name=cfg.get("region", "us-east-1"))
        logger.info(f"Using Bedrock embeddings: {cfg.get('model_id')}")
        return BedrockEmbeddings(client=client, model_id=cfg.get("model_id", "amazon.titan-embed-text-v1"))

    elif provider == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings
        cfg = embed_cfg.get("huggingface", {})
        logger.info(f"Using HuggingFace embeddings: {cfg.get('model_name')}")
        return HuggingFaceEmbeddings(
            model_name=cfg.get("model_name", "all-MiniLM-L6-v2"),
            model_kwargs={"device": cfg.get("device", "cpu")},
        )

    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        cfg = embed_cfg.get("openai", {})
        return OpenAIEmbeddings(model=cfg.get("model_name", "text-embedding-3-small"))

    raise ValueError(f"Unknown embedding provider: {provider}")

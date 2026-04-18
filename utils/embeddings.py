import os
from langchain_openai import OpenAIEmbeddings


def get_embedding_model():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not found. Set it using: export OPENAI_API_KEY='your_key'"
        )

    return OpenAIEmbeddings(
        openai_api_key=api_key,
        model="text-embedding-3-small"
    )
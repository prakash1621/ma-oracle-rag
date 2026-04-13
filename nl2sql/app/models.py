from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, description="Natural language question")


class ChatResponse(BaseModel):
    message: str
    sql_query: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


class HealthResponse(BaseModel):
    status: str
    database: str
    agent_memory_items: int

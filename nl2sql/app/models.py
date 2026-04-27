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


class UnifiedRequest(BaseModel):
    question: str = Field(min_length=1, description="Natural language question")
    filters: dict[str, Any] = Field(default_factory=dict)


class UnifiedResponse(BaseModel):
    answer: str
    route: str
    confidence: float
    sql_query: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)

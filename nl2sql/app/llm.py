from dataclasses import dataclass
from typing import Iterable
import asyncio

from openai import OpenAI
from vanna.capabilities.agent_memory import ToolMemorySearchResult

from nl2sql.app.config import Settings
from nl2sql.app.schema import DatabaseSchema


class SqlGenerationError(RuntimeError):
    """Raised when the LLM cannot generate usable SQL."""


@dataclass(frozen=True)
class PromptContext:
    question: str
    schema_text: str
    memory_examples: tuple[ToolMemorySearchResult, ...]


class SQLGenerator:
    def __init__(self, settings: Settings, schema: DatabaseSchema) -> None:
        self.settings = settings
        self.schema = schema
        self._client = (
            OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.groq_api_key,
            )
            if settings.groq_api_key
            else None
        )

    async def generate_sql(
        self,
        question: str,
        memory_examples: Iterable[ToolMemorySearchResult],
    ) -> str:
        if self._client is None:
            raise SqlGenerationError("Missing GROQ_API_KEY environment variable.")

        prompt_context = PromptContext(
            question=question,
            schema_text=self.schema.format_for_prompt(),
            memory_examples=tuple(memory_examples),
        )
        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self.settings.llm_model,
                temperature=0,
                messages=[
                    {
                        "role": "system",
                        "content": self._build_system_prompt(prompt_context),
                    },
                    {
                        "role": "user",
                        "content": f"Question: {question}",
                    },
                ],
            )
        except Exception as exc:
            raise SqlGenerationError(f"LLM request failed: {exc}") from exc

        content = response.choices[0].message.content if response.choices else None
        if isinstance(content, list):
            content = "".join(
                part.text for part in content if getattr(part, "text", None)
            )
        if not content:
            raise SqlGenerationError("The LLM returned an empty response.")
        return content

    def _build_system_prompt(self, prompt_context: PromptContext) -> str:
        examples = self._format_examples(prompt_context.memory_examples)
        return f"""
You are an expert SQLite analyst. Convert the user's question into one safe SQLite query.

Rules:
- Return exactly one SQLite query and nothing else.
- The query must start with SELECT or WITH.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, PRAGMA, ATTACH, or multiple statements.
- Only reference tables and columns that exist in the schema below.
- Use explicit joins on companies.cik = financial_facts.cik when company metadata is needed.
- Prefer companies.ticker when the user mentions a stock symbol.
- Prefer simple SQLite syntax.
- For exploratory rankings or listings, include a LIMIT clause unless the user asks for all rows.
- If the question asks for a metric, use financial_facts.concept, label, or category to find the right rows.
- If the user asks for the latest value, use the latest relevant period_end or fiscal_year.

Database schema:
{prompt_context.schema_text}

Reference examples:
{examples}
""".strip()

    @staticmethod
    def _format_examples(memory_examples: tuple[ToolMemorySearchResult, ...]) -> str:
        if not memory_examples:
            return "- No prior examples available."

        lines: list[str] = []
        for index, result in enumerate(memory_examples, start=1):
            lines.append(f"Example {index} question: {result.memory.question}")
            lines.append(f"Example {index} SQL: {result.memory.args.get('sql', '')}")
            lines.append("")
        return "\n".join(lines).strip()

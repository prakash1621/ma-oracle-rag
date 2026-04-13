from dataclasses import dataclass

from vanna.capabilities.agent_memory import AgentMemory

from nl2sql.app.config import Settings
from nl2sql.app.database import DatabaseClient, QueryExecutionError
from nl2sql.app.llm import SQLGenerator, SqlGenerationError
from nl2sql.app.memory import build_tool_context
from nl2sql.app.models import ChatResponse
from nl2sql.app.security import SQLValidator, SqlValidationError


@dataclass
class NL2SQLPipeline:
    settings: Settings
    database: DatabaseClient
    sql_generator: SQLGenerator
    sql_validator: SQLValidator
    agent_memory: AgentMemory

    async def run(self, question: str) -> ChatResponse:
        clean_question = question.strip()
        if not clean_question:
            return ChatResponse(
                message="Please send a non-empty question.",
                sql_query="",
                columns=[],
                rows=[],
                row_count=0,
            )

        context = build_tool_context(self.agent_memory)
        memory_examples = await self.agent_memory.search_similar_usage(
            question=clean_question,
            context=context,
            limit=self.settings.memory_search_limit,
            similarity_threshold=0.15,
            tool_name_filter="run_sql",
        )

        try:
            raw_sql = await self.sql_generator.generate_sql(
                question=clean_question,
                memory_examples=memory_examples,
            )
            validated_sql = self.sql_validator.validate(raw_sql)
            query_result = self.database.execute_query(
                validated_sql,
                max_rows=self.settings.max_rows,
            )
        except (SqlGenerationError, SqlValidationError, QueryExecutionError) as exc:
            return ChatResponse(
                message=f"I couldn't generate a safe SQL query for that request: {exc}",
                sql_query="",
                columns=[],
                rows=[],
                row_count=0,
            )

        if query_result.row_count == 0:
            return ChatResponse(
                message="I generated a valid SQL query, but it returned no matching rows for the current dataset.",
                sql_query=validated_sql,
                columns=query_result.columns,
                rows=query_result.rows,
                row_count=0,
            )

        await self.agent_memory.save_tool_usage(
            question=clean_question,
            tool_name="run_sql",
            args={"sql": validated_sql},
            context=context,
            success=True,
        )

        message = f"Here are {query_result.row_count} row(s) for your question."
        if query_result.truncated:
            message = (
                f"Here are the first {query_result.row_count} row(s) for your question. "
                f"The response was capped at {self.settings.max_rows} rows."
            )

        return ChatResponse(
            message=message,
            sql_query=validated_sql,
            columns=query_result.columns,
            rows=query_result.rows,
            row_count=query_result.row_count,
        )

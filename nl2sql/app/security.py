import re

from nl2sql.app.database import DatabaseClient, QueryExecutionError
from nl2sql.app.schema import DatabaseSchema


class SqlValidationError(ValueError):
    """Raised when generated SQL is not safe to run."""


FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|ANALYZE)\b",
    re.IGNORECASE,
)
TABLE_REFERENCE_PATTERN = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?",
    re.IGNORECASE,
)
COLUMN_REFERENCE_PATTERN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b"
)


class SQLValidator:
    def __init__(self, schema: DatabaseSchema, database: DatabaseClient) -> None:
        self.schema = schema
        self.database = database

    def sanitize(self, raw_sql: str) -> str:
        sql = raw_sql.strip()
        if sql.startswith("```"):
            sql = sql.strip("`")
            if sql.lower().startswith("sql"):
                sql = sql[3:]
        select_index = min(
            [
                index
                for index in (sql.lower().find("select"), sql.lower().find("with"))
                if index >= 0
            ],
            default=-1,
        )
        if select_index > 0:
            sql = sql[select_index:]
        return sql.strip().rstrip(";").strip()

    def validate(self, raw_sql: str) -> str:
        sql = self.sanitize(raw_sql)
        if not sql:
            raise SqlValidationError("The model did not return a SQL query.")
        if not re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
            raise SqlValidationError("Only read-only SELECT queries are allowed.")
        if ";" in sql:
            raise SqlValidationError("Only a single SQL statement is allowed.")
        if "--" in sql or "/*" in sql or "*/" in sql:
            raise SqlValidationError("SQL comments are not allowed.")
        if FORBIDDEN_SQL_PATTERN.search(sql):
            raise SqlValidationError("The SQL query contains blocked keywords.")

        alias_map: dict[str, str] = {}
        referenced_tables: set[str] = set()

        for table_name, alias in TABLE_REFERENCE_PATTERN.findall(sql):
            canonical_table = table_name.lower()
            if not self.schema.has_table(canonical_table):
                raise SqlValidationError(f"Unknown table referenced: {table_name}")
            referenced_tables.add(canonical_table)
            alias_map[canonical_table] = canonical_table
            if alias:
                alias_map[alias.lower()] = canonical_table

        if not referenced_tables:
            raise SqlValidationError("The query must reference at least one known table.")

        for qualifier, column_name in COLUMN_REFERENCE_PATTERN.findall(sql):
            key = qualifier.lower()
            if key in alias_map:
                table_name = alias_map[key]
                if not self.schema.has_column(table_name, column_name):
                    raise SqlValidationError(
                        f"Unknown column reference: {qualifier}.{column_name}"
                    )

        try:
            self.database.validate_query_plan(sql)
        except QueryExecutionError as exc:
            raise SqlValidationError(f"SQL failed validation: {exc}") from exc

        return sql

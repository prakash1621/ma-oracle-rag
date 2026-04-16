from dataclasses import dataclass
import sqlite3


class QueryExecutionError(RuntimeError):
    """Raised when a SQL query is invalid or fails to execute."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[object]]
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


class DatabaseClient:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def check_connection(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def validate_query_plan(self, sql: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        except sqlite3.Error as exc:
            raise QueryExecutionError(str(exc)) from exc

    def execute_query(self, sql: str, max_rows: int) -> QueryResult:
        try:
            with self._connect() as conn:
                cursor = conn.execute(sql)
                columns = [description[0] for description in cursor.description or []]
                fetched_rows = cursor.fetchmany(max_rows + 1)
        except sqlite3.Error as exc:
            raise QueryExecutionError(str(exc)) from exc

        truncated = len(fetched_rows) > max_rows
        result_rows = [list(row) for row in fetched_rows[:max_rows]]
        return QueryResult(columns=columns, rows=result_rows, truncated=truncated)

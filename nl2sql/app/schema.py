from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str
    not_null: bool
    is_primary_key: bool


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[ColumnSchema, ...]

    @property
    def column_names(self) -> set[str]:
        return {column.name.lower() for column in self.columns}


@dataclass(frozen=True)
class DatabaseSchema:
    tables: dict[str, TableSchema]

    def has_table(self, table_name: str) -> bool:
        return table_name.lower() in self.tables

    def has_column(self, table_name: str, column_name: str) -> bool:
        table = self.tables.get(table_name.lower())
        if table is None:
            return False
        return column_name.lower() in table.column_names

    def format_for_prompt(self) -> str:
        lines: list[str] = []
        for table_name in sorted(self.tables):
            table = self.tables[table_name]
            lines.append(f"Table: {table.name}")
            for column in table.columns:
                details: list[str] = [column.data_type]
                if column.is_primary_key:
                    details.append("primary key")
                if column.not_null:
                    details.append("not null")
                lines.append(f"- {column.name} ({', '.join(details)})")
            lines.append("")

        lines.append("Relationship hints:")
        lines.append("- Join companies.cik = financial_facts.cik")
        lines.append("- Use companies.ticker to filter by stock symbol")
        lines.append("- Use financial_facts.concept, label, or category to identify metrics")
        lines.append("- Use fiscal_year, fiscal_quarter, period_end, filed_date, and is_annual for time filters")
        return "\n".join(lines).strip()


def load_database_schema(db_path: str) -> DatabaseSchema:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        table_rows = cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

        tables: dict[str, TableSchema] = {}
        for (table_name,) in table_rows:
            column_rows = cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            columns = tuple(
                ColumnSchema(
                    name=row[1],
                    data_type=row[2],
                    not_null=bool(row[3]),
                    is_primary_key=bool(row[5]),
                )
                for row in column_rows
            )
            tables[table_name.lower()] = TableSchema(name=table_name, columns=columns)

        return DatabaseSchema(tables=tables)
    finally:
        conn.close()

"""
XBRL SQLite Storage.

Stores normalized XBRL financial facts in a SQLite database
for SQL-queryable structured financial analysis.

Tables:
- financial_facts: Core fact data (value, period, concept, company)
- companies: Company metadata (CIK, name, ticker)

Supports:
- Time-series queries (revenue over 5 years)
- Cross-company comparisons (AAPL vs MSFT revenue)
- Financial statement reconstruction (full income statement)
- Ratio calculations via SQL
"""

import os
import sqlite3
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class XBRLStorage:
    """
    SQLite storage for XBRL financial facts.

    Usage:
        storage = XBRLStorage("data/xbrl/financials.db")
        storage.store_facts(facts)
        results = storage.query("SELECT * FROM financial_facts WHERE label='Revenue'")
    """

    def __init__(self, db_path: str = "data/xbrl/financials.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """Create the schema if it doesn't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                cik TEXT PRIMARY KEY,
                entity_name TEXT NOT NULL,
                ticker TEXT,
                last_updated TEXT
            );

            CREATE TABLE IF NOT EXISTS financial_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cik TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                taxonomy TEXT NOT NULL,
                concept TEXT NOT NULL,
                label TEXT NOT NULL,
                category TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL,
                period_start TEXT,
                period_end TEXT NOT NULL,
                fiscal_year INTEGER,
                fiscal_quarter INTEGER,
                filing_type TEXT NOT NULL,
                filed_date TEXT,
                accession_number TEXT,
                is_annual BOOLEAN,
                FOREIGN KEY (cik) REFERENCES companies(cik)
            );

            CREATE INDEX IF NOT EXISTS idx_facts_cik ON financial_facts(cik);
            CREATE INDEX IF NOT EXISTS idx_facts_concept ON financial_facts(concept);
            CREATE INDEX IF NOT EXISTS idx_facts_label ON financial_facts(label);
            CREATE INDEX IF NOT EXISTS idx_facts_category ON financial_facts(category);
            CREATE INDEX IF NOT EXISTS idx_facts_period ON financial_facts(period_end);
            CREATE INDEX IF NOT EXISTS idx_facts_fy ON financial_facts(fiscal_year);
            CREATE INDEX IF NOT EXISTS idx_facts_cik_concept ON financial_facts(cik, concept);
            CREATE INDEX IF NOT EXISTS idx_facts_cik_label_fy
                ON financial_facts(cik, label, fiscal_year);

            CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_unique
                ON financial_facts(cik, label, category, period_start, period_end);
        """)
        self.conn.commit()

    def store_company(self, cik: str, entity_name: str, ticker: str = ""):
        """Upsert company metadata."""
        self.conn.execute("""
            INSERT INTO companies (cik, entity_name, ticker, last_updated)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(cik) DO UPDATE SET
                entity_name = excluded.entity_name,
                ticker = CASE WHEN excluded.ticker != '' THEN excluded.ticker ELSE companies.ticker END,
                last_updated = datetime('now')
        """, (cik, entity_name, ticker))
        self.conn.commit()

    def store_facts(self, facts) -> int:
        """
        Store a list of FinancialFact objects. Uses INSERT OR REPLACE
        to handle deduplication at the DB level.

        Returns:
            Number of facts stored
        """
        if not facts:
            return 0

        rows = [
            (f.cik, f.entity_name, f.taxonomy, f.concept, f.label,
             f.category, f.value, f.unit, f.period_start, f.period_end,
             f.fiscal_year, f.fiscal_quarter, f.filing_type,
             f.filed_date, f.accession_number, f.is_annual)
            for f in facts
        ]

        self.conn.executemany("""
            INSERT OR REPLACE INTO financial_facts
            (cik, entity_name, taxonomy, concept, label, category,
             value, unit, period_start, period_end, fiscal_year,
             fiscal_quarter, filing_type, filed_date, accession_number, is_annual)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()

        logger.info(f"Stored {len(rows)} facts")
        return len(rows)

    def query(self, sql: str, params: tuple = ()) -> List[Dict]:
        """
        Execute a SQL query and return results as list of dicts.

        Args:
            sql: SQL query string
            params: Query parameters (for parameterized queries)

        Returns:
            List of row dicts
        """
        cursor = self.conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_income_statement(
        self, cik: str, fiscal_year: Optional[int] = None, annual_only: bool = True
    ) -> List[Dict]:
        """Get income statement line items for a company."""
        sql = """
            SELECT label, value, unit, fiscal_year, fiscal_quarter, period_end
            FROM financial_facts
            WHERE cik = ? AND category = 'income_statement'
        """
        params = [cik]
        if fiscal_year:
            sql += " AND fiscal_year = ?"
            params.append(fiscal_year)
        if annual_only:
            sql += " AND is_annual = 1"
        sql += " ORDER BY fiscal_year DESC, label"
        return self.query(sql, tuple(params))

    def get_balance_sheet(
        self, cik: str, fiscal_year: Optional[int] = None, annual_only: bool = True
    ) -> List[Dict]:
        """Get balance sheet line items for a company."""
        sql = """
            SELECT label, value, unit, fiscal_year, fiscal_quarter, period_end
            FROM financial_facts
            WHERE cik = ? AND category = 'balance_sheet'
        """
        params = [cik]
        if fiscal_year:
            sql += " AND fiscal_year = ?"
            params.append(fiscal_year)
        if annual_only:
            sql += " AND is_annual = 1"
        sql += " ORDER BY fiscal_year DESC, label"
        return self.query(sql, tuple(params))

    def get_cash_flow(
        self, cik: str, fiscal_year: Optional[int] = None, annual_only: bool = True
    ) -> List[Dict]:
        """Get cash flow statement line items for a company."""
        sql = """
            SELECT label, value, unit, fiscal_year, fiscal_quarter, period_end
            FROM financial_facts
            WHERE cik = ? AND category = 'cash_flow'
        """
        params = [cik]
        if fiscal_year:
            sql += " AND fiscal_year = ?"
            params.append(fiscal_year)
        if annual_only:
            sql += " AND is_annual = 1"
        sql += " ORDER BY fiscal_year DESC, label"
        return self.query(sql, tuple(params))

    def get_metric_timeseries(
        self, cik: str, label: str, annual_only: bool = True
    ) -> List[Dict]:
        """Get a single metric over time for a company."""
        sql = """
            SELECT value, unit, fiscal_year, fiscal_quarter, period_end
            FROM financial_facts
            WHERE cik = ? AND label = ?
        """
        params = [cik, label]
        if annual_only:
            sql += " AND is_annual = 1"
        sql += " ORDER BY fiscal_year ASC, fiscal_quarter ASC"
        return self.query(sql, tuple(params))

    def compare_companies(
        self, ciks: List[str], label: str, fiscal_year: Optional[int] = None
    ) -> List[Dict]:
        """Compare a metric across multiple companies."""
        placeholders = ",".join("?" * len(ciks))
        sql = f"""
            SELECT cik, entity_name, label, value, unit, fiscal_year, period_end
            FROM financial_facts
            WHERE cik IN ({placeholders}) AND label = ? AND is_annual = 1
        """
        params = list(ciks) + [label]
        if fiscal_year:
            sql += " AND fiscal_year = ?"
            params.append(fiscal_year)
        sql += " ORDER BY fiscal_year DESC, entity_name"
        return self.query(sql, tuple(params))

    def get_available_companies(self) -> List[Dict]:
        """List all companies in the database."""
        return self.query("SELECT * FROM companies ORDER BY entity_name")

    def get_available_metrics(self, cik: Optional[str] = None) -> List[Dict]:
        """List all available metric labels, optionally filtered by company."""
        if cik:
            return self.query("""
                SELECT DISTINCT label, category, COUNT(*) as data_points
                FROM financial_facts WHERE cik = ?
                GROUP BY label, category ORDER BY category, label
            """, (cik,))
        return self.query("""
            SELECT DISTINCT label, category, COUNT(*) as data_points
            FROM financial_facts
            GROUP BY label, category ORDER BY category, label
        """)

    def get_stats(self) -> Dict:
        """Get database statistics."""
        companies = self.query("SELECT COUNT(*) as cnt FROM companies")[0]["cnt"]
        facts = self.query("SELECT COUNT(*) as cnt FROM financial_facts")[0]["cnt"]
        years = self.query(
            "SELECT MIN(fiscal_year) as min_fy, MAX(fiscal_year) as max_fy FROM financial_facts"
        )[0]
        return {
            "companies": companies,
            "total_facts": facts,
            "min_fiscal_year": years["min_fy"],
            "max_fiscal_year": years["max_fy"],
        }

    def close(self):
        self.conn.close()

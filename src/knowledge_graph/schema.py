"""Neo4j schema for the knowledge graph layer."""

from __future__ import annotations

from neo4j import Driver

NODE_TYPES: dict[str, tuple[str, ...]] = {
    "Company": ("company_key", "name", "ticker", "cik", "sic", "sic_description"),
    "Subsidiary": ("subsidiary_id", "name", "parent_company_key", "source"),
    "BoardMember": ("name", "title"),
    "Filing": (
        "filing_id",
        "accession_number",
        "filing_type",
        "filing_date",
        "period_of_report",
        "source",
    ),
    "RiskFactor": ("risk_id", "text", "category"),
    "Patent": ("patent_id", "title", "date"),
    "Litigation": ("litigation_id", "text", "category"),
}

RELATIONSHIP_TYPES: tuple[str, ...] = (
    "HAS_SUBSIDIARY",
    "HAS_BOARD_MEMBER",
    "OVERSIGHT_BY",
    "ALSO_SERVES_AT",
    "HAS_FILING",
    "HAS_RISK",
    "DISCLOSES_RISK",
    "OWNS_PATENT",
    "HAS_LITIGATION",
    "DISCLOSES_LITIGATION",
    "HAS_COMPETITOR",
)

SCHEMA_CYPHER: tuple[str, ...] = (
    # Neo4j 5+ syntax with IF NOT EXISTS for idempotent setup.
    "CREATE CONSTRAINT company_key_unique IF NOT EXISTS "
    "FOR (c:Company) REQUIRE c.company_key IS UNIQUE",
    "CREATE CONSTRAINT subsidiary_id_unique IF NOT EXISTS "
    "FOR (s:Subsidiary) REQUIRE s.subsidiary_id IS UNIQUE",
    "CREATE CONSTRAINT board_member_name_unique IF NOT EXISTS "
    "FOR (b:BoardMember) REQUIRE b.name IS UNIQUE",
    "CREATE CONSTRAINT filing_id_unique IF NOT EXISTS "
    "FOR (f:Filing) REQUIRE f.filing_id IS UNIQUE",
    "CREATE CONSTRAINT patent_id_unique IF NOT EXISTS "
    "FOR (p:Patent) REQUIRE p.patent_id IS UNIQUE",
    "CREATE CONSTRAINT risk_factor_id_unique IF NOT EXISTS "
    "FOR (r:RiskFactor) REQUIRE r.risk_id IS UNIQUE",
    "CREATE CONSTRAINT litigation_id_unique IF NOT EXISTS "
    "FOR (l:Litigation) REQUIRE l.litigation_id IS UNIQUE",
    "CREATE INDEX company_ticker_idx IF NOT EXISTS "
    "FOR (c:Company) ON (c.ticker)",
    "CREATE INDEX company_name_idx IF NOT EXISTS "
    "FOR (c:Company) ON (c.name)",
    "CREATE INDEX filing_type_idx IF NOT EXISTS "
    "FOR (f:Filing) ON (f.filing_type)",
    "CREATE INDEX filing_date_idx IF NOT EXISTS "
    "FOR (f:Filing) ON (f.filing_date)",
    "CREATE INDEX risk_category_idx IF NOT EXISTS "
    "FOR (r:RiskFactor) ON (r.category)",
    "CREATE INDEX litigation_category_idx IF NOT EXISTS "
    "FOR (l:Litigation) ON (l.category)",
)


def schema_text() -> str:
    """Return a plain-text schema description for prompting."""
    return (
        "Nodes:\n"
        "- (:Company {company_key, name, ticker, cik, sic, sic_description})\n"
        "- (:Subsidiary {subsidiary_id, name, parent_company_key, source})\n"
        "- (:BoardMember {name, title})\n"
        "- (:Filing {filing_id, accession_number, filing_type, filing_date, period_of_report, source})\n"
        "- (:RiskFactor {risk_id, text, category})\n"
        "- (:Patent {patent_id, title, date})\n"
        "- (:Litigation {litigation_id, text, category})\n\n"
        "Relationships:\n"
        "- (:Company)-[:HAS_SUBSIDIARY]->(:Subsidiary)\n"
        "- (:Company)-[:HAS_BOARD_MEMBER]->(:BoardMember)\n"
        "- (:Subsidiary)-[:OVERSIGHT_BY]->(:BoardMember)\n"
        "- (:BoardMember)-[:ALSO_SERVES_AT]->(:Company)\n"
        "- (:Company)-[:HAS_FILING]->(:Filing)\n"
        "- (:Company)-[:HAS_RISK]->(:RiskFactor)\n"
        "- (:Filing)-[:DISCLOSES_RISK]->(:RiskFactor)\n"
        "- (:Company)-[:OWNS_PATENT]->(:Patent)\n"
        "- (:Company)-[:HAS_LITIGATION]->(:Litigation)\n"
        "- (:Filing)-[:DISCLOSES_LITIGATION]->(:Litigation)\n"
        "- (:Company)-[:HAS_COMPETITOR]->(:Company)\n"
    )


def initialize_schema(driver: Driver, database: str = "neo4j") -> None:
    """Create constraints/indexes if they do not already exist."""
    for statement in SCHEMA_CYPHER:
        driver.execute_query(statement, database_=database)

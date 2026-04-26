"""Build and populate the Neo4j knowledge graph."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase, RoutingControl
from neo4j.exceptions import Neo4jError

from src.knowledge_graph.extractor import extract_entities
from src.knowledge_graph.schema import NODE_TYPES, RELATIONSHIP_TYPES, initialize_schema

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(_REPO_ROOT / ".env")


def _env_or_raise(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var {name}. "
            "Set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD in .env."
        )
    return value


def _load_entities_file(path: str | os.PathLike[str]) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_entities_into_neo4j(
    entities: dict[str, Any],
    *,
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    clear_existing: bool = False,
) -> dict[str, Any]:
    """Load extracted entities into Neo4j with MERGE-based upserts."""
    database = database or os.environ.get("NEO4J_DATABASE", "neo4j")
    try:
        uri = uri or _env_or_raise("NEO4J_URI")
        user = user or _env_or_raise("NEO4J_USER")
        password = password or _env_or_raise("NEO4J_PASSWORD")
    except Exception as exc:
        return {
            "status": "error",
            "database": database,
            "error": str(exc),
        }

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        initialize_schema(driver, database=database)

        if clear_existing:
            driver.execute_query(
                "MATCH (n) WHERE any(lbl IN labels(n) WHERE lbl IN $labels) "
                "DETACH DELETE n",
                labels=list(NODE_TYPES.keys()),
                database_=database,
            )

        companies = entities.get("companies", []) or []
        subsidiaries = entities.get("subsidiaries", []) or []
        board_members = entities.get("board_members", []) or []
        filings = entities.get("filings", []) or []
        patents = entities.get("patents", []) or []
        risks = entities.get("risk_factors", []) or []
        litigations = entities.get("litigations", []) or []
        competitors = entities.get("competitors", []) or []

        if companies:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MERGE (c:Company {company_key: row.company_key})
                SET c.name = row.name,
                    c.ticker = row.ticker,
                    c.cik = row.cik,
                    c.sic = coalesce(row.sic, c.sic),
                    c.sic_description = coalesce(row.sic_description, c.sic_description)
                """,
                rows=companies,
                database_=database,
            )

        if filings:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (c:Company {company_key: row.company_key})
                MERGE (f:Filing {filing_id: row.filing_id})
                SET f.accession_number = row.accession_number,
                    f.filing_type = row.filing_type,
                    f.filing_date = row.filing_date,
                    f.period_of_report = row.period_of_report,
                    f.source = row.source
                MERGE (c)-[:HAS_FILING]->(f)
                """,
                rows=filings,
                database_=database,
            )

        if subsidiaries:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (c:Company {company_key: row.company_key})
                MERGE (s:Subsidiary {subsidiary_id: row.subsidiary_id})
                SET s.name = row.name,
                    s.parent_company_key = row.parent_company_key,
                    s.source = row.source
                MERGE (c)-[:HAS_SUBSIDIARY]->(s)
                """,
                rows=subsidiaries,
                database_=database,
            )

        if board_members:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (c:Company {company_key: row.company_key})
                MERGE (b:BoardMember {name: row.name})
                SET b.title = CASE
                    WHEN coalesce(row.title, '') <> '' THEN row.title
                    ELSE coalesce(b.title, 'Board Member')
                END,
                    b.source = coalesce(row.source, b.source)
                MERGE (c)-[:HAS_BOARD_MEMBER]->(b)
                """,
                rows=board_members,
                database_=database,
            )

        if patents:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (c:Company {company_key: row.company_key})
                MERGE (p:Patent {patent_id: row.patent_id})
                SET p.title = row.title,
                    p.date = row.date,
                    p.source = coalesce(row.source, p.source)
                MERGE (c)-[:OWNS_PATENT]->(p)
                """,
                rows=patents,
                database_=database,
            )

        if risks:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (c:Company {company_key: row.company_key})
                MERGE (r:RiskFactor {risk_id: row.risk_id})
                SET r.text = row.text,
                    r.category = row.category,
                    r.source = coalesce(row.source, r.source)
                MERGE (c)-[:HAS_RISK]->(r)
                FOREACH (_ IN CASE
                    WHEN coalesce(row.filing_id, '') <> ''
                    THEN [1] ELSE [] END |
                    MERGE (f:Filing {filing_id: row.filing_id})
                    MERGE (f)-[:DISCLOSES_RISK]->(r)
                )
                """,
                rows=risks,
                database_=database,
            )

        if litigations:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (c:Company {company_key: row.company_key})
                MERGE (l:Litigation {litigation_id: row.litigation_id})
                SET l.text = row.text,
                    l.category = row.category,
                    l.source = coalesce(row.source, l.source)
                MERGE (c)-[:HAS_LITIGATION]->(l)
                FOREACH (_ IN CASE
                    WHEN coalesce(row.filing_id, '') <> ''
                    THEN [1] ELSE [] END |
                    MERGE (f:Filing {filing_id: row.filing_id})
                    MERGE (f)-[:DISCLOSES_LITIGATION]->(l)
                )
                """,
                rows=litigations,
                database_=database,
            )

        if competitors:
            driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (c1:Company {company_key: row.company_key})
                MATCH (c2:Company {company_key: row.target_company_key})
                MERGE (c1)-[r:HAS_COMPETITOR]->(c2)
                SET r.reason = row.reason,
                    r.source = row.source,
                    r.confidence = coalesce(row.confidence, r.confidence)
                """,
                rows=competitors,
                database_=database,
            )

        # Connect subsidiaries to board members of the same parent company.
        driver.execute_query(
            """
            MATCH (c:Company)-[:HAS_SUBSIDIARY]->(s:Subsidiary)
            MATCH (c)-[:HAS_BOARD_MEMBER]->(b:BoardMember)
            MERGE (s)-[:OVERSIGHT_BY]->(b)
            """,
            database_=database,
        )

        # Cross-company board service links.
        driver.execute_query(
            """
            MATCH (b:BoardMember)<-[:HAS_BOARD_MEMBER]-(c1:Company)
            MATCH (b)<-[:HAS_BOARD_MEMBER]-(c2:Company)
            WHERE c1.company_key <> c2.company_key
            MERGE (b)-[:ALSO_SERVES_AT]->(c2)
            """,
            database_=database,
        )

        stats: dict[str, int] = {}
        for label in NODE_TYPES:
            records, _, _ = driver.execute_query(
                f"MATCH (n:{label}) RETURN count(n) AS count",
                database_=database,
                routing_=RoutingControl.READ,
            )
            stats[f"nodes_{label}"] = int(records[0]["count"]) if records else 0

        for rel in RELATIONSHIP_TYPES:
            records, _, _ = driver.execute_query(
                "MATCH ()-[r]->() WHERE type(r) = $rel RETURN count(r) AS count",
                rel=rel,
                database_=database,
                routing_=RoutingControl.READ,
            )
            stats[f"rels_{rel}"] = int(records[0]["count"]) if records else 0

        return {
            "status": "ok",
            "database": database,
            "stats": stats,
        }
    except Neo4jError as exc:
        return {
            "status": "error",
            "database": database,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    finally:
        driver.close()


def build_knowledge_graph(
    *,
    entities_path: str | os.PathLike[str] | None = None,
    output_entities_path: str | os.PathLike[str] = "output/knowledge_graph/entities.json",
    proxy_chunks_path: str | os.PathLike[str] = "output/proxy/chunked_documents.json",
    edgar_chunks_path: str | os.PathLike[str] = "output/edgar/chunked_documents.json",
    patents_chunks_path: str | os.PathLike[str] = "output/patents/chunked_documents.json",
    transcripts_chunks_path: str | os.PathLike[str] = "output/transcripts/chunked_documents.json",
    xbrl_db_path: str | os.PathLike[str] = "output/xbrl/financials.db",
    company_facts_path: str | os.PathLike[str] = "output/company_facts/companies.json",
    use_llm: bool = True,
    clear_existing: bool = False,
    database: str | None = None,
) -> dict[str, Any]:
    """Extract entities (if needed) and populate Neo4j."""
    if entities_path:
        entities = _load_entities_file(entities_path)
    else:
        entities = extract_entities(
            proxy_chunks_path=proxy_chunks_path,
            edgar_chunks_path=edgar_chunks_path,
            patents_chunks_path=patents_chunks_path,
            transcripts_chunks_path=transcripts_chunks_path,
            xbrl_db_path=xbrl_db_path,
            company_facts_path=company_facts_path,
            output_path=output_entities_path,
            use_llm=use_llm,
        )

    return load_entities_into_neo4j(
        entities,
        database=database,
        clear_existing=clear_existing,
    )


def build_knowledge_graph_from_files(
    entities_path: str | os.PathLike[str] = "output/knowledge_graph/entities.json",
    *,
    database: str | None = None,
    clear_existing: bool = False,
) -> dict[str, Any]:
    """Load a pre-extracted entities JSON file into Neo4j."""
    entities_file = Path(entities_path)
    if not entities_file.exists():
        return {
            "status": "error",
            "error": f"Entities file not found: {entities_file}",
        }
    entities = _load_entities_file(entities_file)
    return load_entities_into_neo4j(
        entities,
        database=database,
        clear_existing=clear_existing,
    )

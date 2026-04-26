"""Natural-language query interface for the Neo4j knowledge graph."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from src.contradiction._llm import build_llm_client
from src.knowledge_graph.export import export_graph_data_from_results
from src.knowledge_graph.schema import schema_text

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(_REPO_ROOT / ".env")

_COMPANY_TICKERS = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "nvidia": "NVDA",
    "amazon": "AMZN",
    "meta": "META",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "tesla": "TSLA",
    "salesforce": "CRM",
    "snowflake": "SNOW",
    "crowdstrike": "CRWD",
    "palo alto": "PANW",
    "fortinet": "FTNT",
}


def _env_or_raise(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var {name}. "
            "Set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD in .env."
        )
    return value


def _infer_tickers(question: str, tickers: list[str] | None) -> list[str]:
    out: set[str] = {t.strip().upper() for t in (tickers or []) if t and t.strip()}
    q = question.lower()
    for ticker in _COMPANY_TICKERS.values():
        if ticker.lower() in q:
            out.add(ticker)
    for name, ticker in _COMPANY_TICKERS.items():
        if name in q:
            out.add(ticker)
    return sorted(out)


def _rule_based_cypher(question: str) -> str:
    q = question.lower()

    if "->" in q or ("subsidiary" in q and "board" in q and "risk" in q and "patent" in q):
        return (
            "MATCH (c:Company)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "OPTIONAL MATCH (c)-[:HAS_SUBSIDIARY]->(s:Subsidiary)\n"
            "OPTIONAL MATCH (c)-[:HAS_BOARD_MEMBER]->(b:BoardMember)\n"
            "OPTIONAL MATCH (c)-[:HAS_FILING]->(f:Filing)\n"
            "OPTIONAL MATCH (f)-[:DISCLOSES_RISK]->(r:RiskFactor)\n"
            "OPTIONAL MATCH (c)-[:OWNS_PATENT]->(p:Patent)\n"
            "OPTIONAL MATCH (c)-[:HAS_LITIGATION]->(l:Litigation)\n"
            "OPTIONAL MATCH (c)-[:HAS_COMPETITOR]->(comp:Company)\n"
            "RETURN c.ticker AS ticker, c.name AS company,\n"
            "collect(DISTINCT s.name)[0..10] AS subsidiaries,\n"
            "collect(DISTINCT b.name)[0..15] AS board_members,\n"
            "collect(DISTINCT f.filing_type + ':' + coalesce(f.filing_date, ''))[0..10] AS filings,\n"
            "collect(DISTINCT r.category)[0..10] AS risk_categories,\n"
            "collect(DISTINCT p.patent_id)[0..10] AS patents,\n"
            "collect(DISTINCT l.category)[0..10] AS litigation_categories,\n"
            "collect(DISTINCT comp.ticker)[0..10] AS competitors\n"
            "ORDER BY c.ticker\n"
            "LIMIT 50"
        )

    if "also serves" in q or "serves at" in q or "cross-board" in q:
        return (
            "MATCH (b:BoardMember)-[:ALSO_SERVES_AT]->(c:Company)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN b.name AS name, c.ticker AS ticker, c.name AS company\n"
            "ORDER BY b.name, c.ticker\n"
            "LIMIT 100"
        )

    if "subsidiary" in q or "subsidiaries" in q:
        return (
            "MATCH (c:Company)-[:HAS_SUBSIDIARY]->(s:Subsidiary)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN c.ticker AS ticker, c.name AS company, s.name AS subsidiary, s.source AS source\n"
            "ORDER BY c.ticker, s.name\n"
            "LIMIT 200"
        )

    if "competitor" in q or "competition" in q or "rival" in q:
        return (
            "MATCH (c:Company)-[r:HAS_COMPETITOR]->(comp:Company)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN c.ticker AS ticker, c.name AS company, comp.ticker AS competitor_ticker,\n"
            "comp.name AS competitor, r.reason AS reason, r.confidence AS confidence\n"
            "ORDER BY c.ticker, comp.ticker\n"
            "LIMIT 200"
        )

    if "litigation" in q or "lawsuit" in q or "legal proceeding" in q:
        return (
            "MATCH (c:Company)-[:HAS_LITIGATION]->(l:Litigation)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN c.ticker AS ticker, c.name AS company, l.category AS category, l.text AS litigation_text\n"
            "ORDER BY c.ticker, l.category\n"
            "LIMIT 100"
        )

    if "transcript" in q:
        return (
            "MATCH (c:Company)-[:HAS_FILING]->(f:Filing)\n"
            "WHERE (size($tickers) = 0 OR c.ticker IN $tickers)\n"
            "AND toUpper(f.filing_type) CONTAINS 'TRANSCRIPT'\n"
            "RETURN c.ticker AS ticker, c.name AS company, f.filing_type AS filing_type,\n"
            "f.filing_date AS filing_date, f.source AS source, f.accession_number AS accession_number\n"
            "ORDER BY c.ticker, f.filing_date DESC\n"
            "LIMIT 100"
        )

    if "xbrl" in q:
        return (
            "MATCH (c:Company)-[:HAS_FILING]->(f:Filing)\n"
            "WHERE (size($tickers) = 0 OR c.ticker IN $tickers)\n"
            "AND toUpper(f.source) = 'XBRL'\n"
            "RETURN c.ticker AS ticker, c.name AS company, f.filing_type AS filing_type,\n"
            "f.filing_date AS filing_date, f.source AS source, f.accession_number AS accession_number\n"
            "ORDER BY c.ticker, f.filing_date DESC\n"
            "LIMIT 100"
        )

    if "filing" in q or "10-k" in q or "10-q" in q or "8-k" in q:
        return (
            "MATCH (c:Company)-[:HAS_FILING]->(f:Filing)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN c.ticker AS ticker, c.name AS company, f.filing_type AS filing_type,\n"
            "f.filing_date AS filing_date, f.source AS source, f.accession_number AS accession_number\n"
            "ORDER BY c.ticker, f.filing_date DESC\n"
            "LIMIT 200"
        )

    if "patent" in q:
        return (
            "MATCH (c:Company)-[:OWNS_PATENT]->(p:Patent)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN c.ticker AS ticker, c.name AS company, p.patent_id AS patent_id, "
            "p.title AS title, p.date AS date\n"
            "ORDER BY c.ticker, p.date DESC\n"
            "LIMIT 100"
        )

    if "risk" in q or "risk factor" in q:
        return (
            "MATCH (c:Company)-[:HAS_RISK]->(r:RiskFactor)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN c.ticker AS ticker, c.name AS company, r.category AS category, "
            "r.text AS risk_text\n"
            "ORDER BY c.ticker, r.category\n"
            "LIMIT 100"
        )

    if "board" in q or "director" in q or "who are" in q:
        return (
            "MATCH (c:Company)-[:HAS_BOARD_MEMBER]->(b:BoardMember)\n"
            "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
            "RETURN c.ticker AS ticker, c.name AS company, b.name AS name, b.title AS title\n"
            "ORDER BY c.ticker, b.name\n"
            "LIMIT 100"
        )

    return (
        "MATCH (c:Company)-[r]->(n)\n"
        "WHERE size($tickers) = 0 OR c.ticker IN $tickers\n"
        "RETURN c.ticker AS ticker, c.name AS company, type(r) AS relationship,\n"
        "coalesce(n.name, n.title, n.patent_id, n.category, n.filing_type, 'Entity') AS target\n"
        "ORDER BY c.ticker\n"
        "LIMIT 100"
    )


def _first_json_obj(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _is_safe_read_query(cypher: str) -> bool:
    upper = f" {cypher.upper()} "
    forbidden = (
        " CREATE ",
        " MERGE ",
        " DELETE ",
        " SET ",
        " DROP ",
        " REMOVE ",
        " CALL ",
        " LOAD ",
        " APOC ",
        " FOREACH ",
    )
    if any(tok in upper for tok in forbidden):
        return False
    trimmed = cypher.strip().upper()
    return trimmed.startswith("MATCH") or trimmed.startswith("WITH") or trimmed.startswith(
        "OPTIONAL MATCH"
    )


def _llm_generate_cypher(question: str) -> str | None:
    try:
        client, model = build_llm_client()
    except Exception:
        return None

    prompt = (
        "Convert the question into a read-only Cypher query for Neo4j.\n"
        "Use this schema:\n"
        f"{schema_text()}\n"
        "Requirements:\n"
        "- Return JSON only: {\"cypher\":\"...\"}\n"
        "- Use parameter $tickers when filtering companies.\n"
        "- No CREATE, MERGE, DELETE, SET, CALL, or APOC.\n"
        "- Keep result columns friendly for APIs.\n"
        "- Add LIMIT 100 if no limit is present.\n\n"
        f"Question: {question}"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are an expert Cypher generator."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    parsed = _first_json_obj(resp.choices[0].message.content or "")
    cypher = str(parsed.get("cypher", "")).strip()
    if not cypher:
        return None
    if " LIMIT " not in f" {cypher.upper()} ":
        cypher = f"{cypher}\nLIMIT 100"
    if not _is_safe_read_query(cypher):
        return None
    return cypher


def query_knowledge_graph(question: str, tickers: list | None = None) -> dict:
    """
    Query the knowledge graph with natural language.

    Returns:
        {
            "cypher": "...",
            "results": [...],
            "graph_data": {"nodes": [...], "edges": [...]}
        }
    """
    resolved_tickers = _infer_tickers(question, tickers=tickers)
    cypher = _rule_based_cypher(question)

    # Only use LLM generation when question is not clearly template-covered.
    if not any(
        key in question.lower()
        for key in (
            "board",
            "director",
            "risk",
            "patent",
            "serves",
            "relationship",
            "subsidiary",
            "competitor",
            "litigation",
            "filing",
            "transcript",
            "xbrl",
            "10-k",
            "10-q",
        )
    ):
        llm_cypher = _llm_generate_cypher(question)
        if llm_cypher:
            cypher = llm_cypher

    if not _is_safe_read_query(cypher):
        return {
            "cypher": cypher,
            "results": [],
            "graph_data": {"nodes": [], "edges": []},
            "error": "Generated query was not read-only safe.",
        }

    try:
        uri = _env_or_raise("NEO4J_URI")
        user = _env_or_raise("NEO4J_USER")
        password = _env_or_raise("NEO4J_PASSWORD")
        database = os.environ.get("NEO4J_DATABASE", "neo4j")
    except Exception as exc:
        return {
            "cypher": cypher,
            "results": [],
            "graph_data": {"nodes": [], "edges": []},
            "error": str(exc),
        }

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        records, _, _ = driver.execute_query(
            cypher,
            tickers=resolved_tickers,
            database_=database,
        )
        results = [record.data() for record in records]
        graph_data = export_graph_data_from_results(
            driver,
            results,
            fallback_tickers=resolved_tickers,
            database=database,
        )
        return {
            "cypher": cypher,
            "results": results,
            "graph_data": graph_data,
        }
    except Exception as exc:
        return {
            "cypher": cypher,
            "results": [],
            "graph_data": {"nodes": [], "edges": []},
            "error": str(exc),
        }
    finally:
        driver.close()

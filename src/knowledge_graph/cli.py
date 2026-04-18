"""CLI helpers for knowledge-graph extract/build/query/export workflows."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from neo4j import GraphDatabase

from src.knowledge_graph.builder import (
    build_knowledge_graph,
    build_knowledge_graph_from_files,
)
from src.knowledge_graph.export import export_graph_data
from src.knowledge_graph.extractor import extract_entities
from src.knowledge_graph.query import query_knowledge_graph


def _cmd_extract(args: argparse.Namespace) -> int:
    result = extract_entities(
        proxy_chunks_path=args.proxy_chunks,
        edgar_chunks_path=args.edgar_chunks,
        patents_chunks_path=args.patents_chunks,
        transcripts_chunks_path=args.transcripts_chunks,
        xbrl_db_path=args.xbrl_db,
        company_facts_path=args.company_facts,
        output_path=args.output,
        use_llm=not args.no_llm,
        max_proxy_chunks=args.max_proxy_chunks,
        max_risk_chunks=args.max_risk_chunks,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "output": args.output,
                "counts": {
                    "companies": len(result.get("companies", [])),
                    "subsidiaries": len(result.get("subsidiaries", [])),
                    "board_members": len(result.get("board_members", [])),
                    "filings": len(result.get("filings", [])),
                    "patents": len(result.get("patents", [])),
                    "risk_factors": len(result.get("risk_factors", [])),
                    "litigations": len(result.get("litigations", [])),
                    "competitors": len(result.get("competitors", [])),
                },
                "meta": result.get("meta", {}),
            },
            indent=2,
        )
    )
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    result = build_knowledge_graph(
        entities_path=args.entities_path,
        output_entities_path=args.output,
        proxy_chunks_path=args.proxy_chunks,
        edgar_chunks_path=args.edgar_chunks,
        patents_chunks_path=args.patents_chunks,
        transcripts_chunks_path=args.transcripts_chunks,
        xbrl_db_path=args.xbrl_db,
        company_facts_path=args.company_facts,
        use_llm=not args.no_llm,
        clear_existing=args.clear_existing,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def _cmd_load(args: argparse.Namespace) -> int:
    result = build_knowledge_graph_from_files(
        entities_path=args.entities_path,
        clear_existing=args.clear_existing,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def _cmd_query(args: argparse.Namespace) -> int:
    tickers = args.tickers or None
    result = query_knowledge_graph(args.question, tickers=tickers)
    print(json.dumps(result, indent=2))
    return 0 if not result.get("error") else 1


def _cmd_export(args: argparse.Namespace) -> int:
    uri = os.environ.get("NEO4J_URI", "").strip()
    user = os.environ.get("NEO4J_USER", "").strip()
    password = os.environ.get("NEO4J_PASSWORD", "").strip()
    database = os.environ.get("NEO4J_DATABASE", "neo4j").strip() or "neo4j"

    missing = [k for k, v in {
        "NEO4J_URI": uri,
        "NEO4J_USER": user,
        "NEO4J_PASSWORD": password,
    }.items() if not v]
    if missing:
        print(json.dumps({"status": "error", "error": f"Missing env vars: {', '.join(missing)}"}, indent=2))
        return 1

    tickers = args.tickers or None
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        graph_data = export_graph_data(
            driver,
            tickers=tickers,
            limit=args.limit,
            database=database,
        )
    finally:
        driver.close()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)

    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(out),
                "nodes": len(graph_data.get("nodes", [])),
                "edges": len(graph_data.get("edges", [])),
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Knowledge graph CLI (extract/build/query/export)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="Extract entities from chunk JSON files.")
    p_extract.add_argument(
        "--output",
        default="output/knowledge_graph/entities.json",
        help="Path to write extracted entities JSON.",
    )
    p_extract.add_argument("--proxy-chunks", default="output/proxy/chunked_documents.json")
    p_extract.add_argument("--edgar-chunks", default="output/edgar/chunked_documents.json")
    p_extract.add_argument("--patents-chunks", default="output/patents/chunked_documents.json")
    p_extract.add_argument("--transcripts-chunks", default="output/transcripts/chunked_documents.json")
    p_extract.add_argument("--xbrl-db", default="output/xbrl/financials.db")
    p_extract.add_argument("--company-facts", default="output/company_facts/companies.json")
    p_extract.add_argument("--max-proxy-chunks", type=int, default=120)
    p_extract.add_argument("--max-risk-chunks", type=int, default=180)
    p_extract.add_argument("--no-llm", action="store_true", help="Use regex fallback only.")
    p_extract.set_defaults(func=_cmd_extract)

    p_build = sub.add_parser("build", help="Extract entities (optional) and load into Neo4j.")
    p_build.add_argument(
        "--entities-path",
        default=None,
        help="Use existing entities JSON file instead of re-extracting.",
    )
    p_build.add_argument(
        "--output",
        default="output/knowledge_graph/entities.json",
        help="Where extracted entities JSON is written when re-extracting.",
    )
    p_build.add_argument("--proxy-chunks", default="output/proxy/chunked_documents.json")
    p_build.add_argument("--edgar-chunks", default="output/edgar/chunked_documents.json")
    p_build.add_argument("--patents-chunks", default="output/patents/chunked_documents.json")
    p_build.add_argument("--transcripts-chunks", default="output/transcripts/chunked_documents.json")
    p_build.add_argument("--xbrl-db", default="output/xbrl/financials.db")
    p_build.add_argument("--company-facts", default="output/company_facts/companies.json")
    p_build.add_argument("--clear-existing", action="store_true")
    p_build.add_argument("--no-llm", action="store_true", help="Use regex fallback only.")
    p_build.set_defaults(func=_cmd_build)

    p_load = sub.add_parser("load", help="Load a pre-extracted entities file into Neo4j.")
    p_load.add_argument(
        "--entities-path",
        default="output/knowledge_graph/entities.json",
        help="Existing entities JSON path.",
    )
    p_load.add_argument("--clear-existing", action="store_true")
    p_load.set_defaults(func=_cmd_load)

    p_query = sub.add_parser("query", help="Run NL question against knowledge graph.")
    p_query.add_argument("question", help="Natural language question.")
    p_query.add_argument("--tickers", nargs="*", default=None)
    p_query.set_defaults(func=_cmd_query)

    p_export = sub.add_parser("export", help="Export nodes/edges JSON from Neo4j.")
    p_export.add_argument(
        "--output",
        default="output/knowledge_graph/graph_data.json",
        help="Path to write graph_data JSON.",
    )
    p_export.add_argument("--tickers", nargs="*", default=None)
    p_export.add_argument("--limit", type=int, default=500)
    p_export.set_defaults(func=_cmd_export)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))

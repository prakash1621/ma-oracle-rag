"""Export Neo4j graph data as frontend-friendly nodes/edges JSON."""

from __future__ import annotations

from typing import Any

from neo4j import Driver


def _node_type(labels: list[str]) -> str:
    if not labels:
        return "Node"
    # Keep stable display order for known labels.
    for candidate in (
        "Company",
        "Subsidiary",
        "BoardMember",
        "Filing",
        "Patent",
        "RiskFactor",
        "Litigation",
    ):
        if candidate in labels:
            return candidate
    return labels[0]


def _node_label(node_type: str, props: dict[str, Any]) -> str:
    if node_type == "Company":
        return str(props.get("ticker") or props.get("name") or "Company")
    if node_type == "BoardMember":
        return str(props.get("name") or "BoardMember")
    if node_type == "Subsidiary":
        return str(props.get("name") or "Subsidiary")
    if node_type == "Filing":
        return str(props.get("filing_type") or props.get("accession_number") or "Filing")
    if node_type == "Patent":
        return str(props.get("patent_id") or props.get("title") or "Patent")
    if node_type == "RiskFactor":
        category = str(props.get("category") or "risk")
        text = str(props.get("text") or "")
        return f"{category}: {text[:40]}".strip()
    if node_type == "Litigation":
        category = str(props.get("category") or "litigation")
        text = str(props.get("text") or "")
        return f"{category}: {text[:40]}".strip()
    return str(props.get("name") or props.get("id") or node_type)


def export_graph_data(
    driver: Driver,
    *,
    tickers: list[str] | None = None,
    limit: int = 300,
    database: str = "neo4j",
) -> dict[str, Any]:
    """Export a graph slice as nodes + edges for frontend visualization."""
    ticker_filter = [t.strip().upper() for t in (tickers or []) if t and t.strip()]

    records, _, _ = driver.execute_query(
        """
        MATCH (c:Company)
        WHERE size($tickers) = 0 OR c.ticker IN $tickers
        OPTIONAL MATCH (c)-[r]->(n)
        RETURN
            c AS company,
            n AS neighbor,
            labels(c) AS company_labels,
            labels(n) AS neighbor_labels,
            properties(c) AS company_props,
            properties(n) AS neighbor_props,
            elementId(c) AS company_id,
            elementId(n) AS neighbor_id,
            type(r) AS rel_type,
            elementId(r) AS rel_id,
            CASE WHEN r IS NULL THEN NULL ELSE elementId(startNode(r)) END AS source_id,
            CASE WHEN r IS NULL THEN NULL ELSE elementId(endNode(r)) END AS target_id
        LIMIT $limit
        """,
        tickers=ticker_filter,
        limit=limit,
        database_=database,
    )

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for row in records:
        company_id = row.get("company_id")
        if company_id and company_id not in nodes:
            labels = [str(x) for x in (row.get("company_labels") or [])]
            props = dict(row.get("company_props") or {})
            kind = _node_type(labels)
            nodes[company_id] = {
                "id": company_id,
                "type": kind,
                "label": _node_label(kind, props),
                "properties": props,
            }

        neighbor_id = row.get("neighbor_id")
        if neighbor_id and neighbor_id not in nodes:
            labels = [str(x) for x in (row.get("neighbor_labels") or [])]
            props = dict(row.get("neighbor_props") or {})
            kind = _node_type(labels)
            nodes[neighbor_id] = {
                "id": neighbor_id,
                "type": kind,
                "label": _node_label(kind, props),
                "properties": props,
            }

        rel_id = row.get("rel_id")
        if rel_id and rel_id not in edges:
            edges[rel_id] = {
                "id": rel_id,
                "type": row.get("rel_type"),
                "source": row.get("source_id"),
                "target": row.get("target_id"),
            }

    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
    }


def export_graph_data_from_results(
    driver: Driver,
    results: list[dict[str, Any]],
    *,
    fallback_tickers: list[str] | None = None,
    limit: int = 300,
    database: str = "neo4j",
) -> dict[str, Any]:
    """Infer relevant tickers from query results and export matching graph slice."""
    inferred_tickers: set[str] = set()

    for row in results:
        for key in ("ticker", "company_ticker", "target_ticker"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                inferred_tickers.add(value.strip().upper())

    for ticker in fallback_tickers or []:
        if ticker and ticker.strip():
            inferred_tickers.add(ticker.strip().upper())

    return export_graph_data(
        driver,
        tickers=sorted(inferred_tickers),
        limit=limit,
        database=database,
    )

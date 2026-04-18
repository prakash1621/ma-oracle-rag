"""Extract company entities and relationships from chunked JSON sources."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

from src.contradiction._llm import build_llm_client

_REPO_ROOT = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(_REPO_ROOT / ".env")

_BOARD_SECTIONS = {
    "board_directors",
    "related_party",
    "audit_committee",
    "stock_ownership",
    "executive_compensation",
}

_BOARD_TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("chief executive officer", "Chief Executive Officer"),
    ("ceo", "Chief Executive Officer"),
    ("chief financial officer", "Chief Financial Officer"),
    ("cfo", "Chief Financial Officer"),
    ("chief operating officer", "Chief Operating Officer"),
    ("coo", "Chief Operating Officer"),
    ("lead independent director", "Lead Independent Director"),
    ("independent chair", "Independent Chair"),
    ("chair", "Chair"),
    ("president", "President"),
    ("director", "Director"),
)

_BOARD_BLOCK_WORDS = {
    "board",
    "director",
    "directors",
    "committee",
    "governance",
    "policy",
    "shareholder",
    "stockholder",
    "proposal",
    "information",
    "statement",
    "summary",
    "meeting",
    "notice",
    "table",
    "contents",
    "report",
    "management",
    "fiscal",
    "annual",
    "proxy",
    "company",
    "shares",
    "security",
    "ownership",
    "other",
    "business",
    "items",
    "recommendations",
    "framework",
    "role",
    "independence",
    "attendance",
    "evaluation",
    "candidates",
    "proposals",
    "services",
    "voting",
    "general",
    "chief",
    "officer",
    "executive",
    "order",
    "act",
    "exchange",
    "commission",
    "compensation",
    "audit",
    "stock",
    "common",
    "class",
    "factors",
    "forward",
    "looking",
    "release",
    "cash",
    "total",
    "portion",
    "non",
    "services",
    "fees",
    "owners",
    "beneficial",
    "additional",
    "skills",
    "expanded",
    "grew",
    "dear",
    "fellow",
    "pacific",
    "procedural",
    "matters",
    "equity",
    "grant",
    "falcon",
    "leased",
    "legal",
    "ratio",
    "disclosure",
    "percentage",
    "vanguard",
    "accounting",
    "reference",
    "independent",
    "registered",
    "build",
    "move",
    "primary",
    "responsibilities",
    "promote",
    "opportunity",
    "record",
    "principal",
    "performance",
    "program",
    "design",
    "update",
    "shareholders",
    "charter",
    "strategic",
    "execution",
    "professional",
    "visualization",
    "vote",
    "required",
    "human",
    "capital",
    "technical",
    "about",
    "details",
    "target",
    "step",
    "data",
    "privacy",
    "agenda",
    "item",
    "gigafactory",
    "forward-looking",
    "corporate",
    "sustainability",
    "internal",
    "revenue",
    "code",
    "operating",
    "income",
    "control",
    "number",
    "auditing",
    "standard",
    "famil",
    "trust",
    "transactions",
    "party",
    "location",
    "time",
    "date",
    "boar",
    "same",
    "multi",
}

_RISK_CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("supply chain", "supply_chain"),
    ("supplier", "supply_chain"),
    ("cyber", "cybersecurity"),
    ("security breach", "cybersecurity"),
    ("privacy", "privacy"),
    ("ai", "technology"),
    ("competition", "competition"),
    ("inflation", "macroeconomic"),
    ("interest rate", "macroeconomic"),
    ("tariff", "macroeconomic"),
    ("foreign exchange", "macroeconomic"),
    ("litigation", "legal"),
    ("regulatory", "regulatory"),
    ("tax", "tax"),
)

_LITIGATION_CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("antitrust", "antitrust"),
    ("intellectual property", "intellectual_property"),
    ("patent", "intellectual_property"),
    ("securities class action", "securities"),
    ("securities", "securities"),
    ("tax", "tax"),
    ("employment", "employment"),
    ("privacy", "privacy"),
    ("regulatory", "regulatory"),
    ("lawsuit", "general"),
    ("litigation", "general"),
    ("legal proceeding", "general"),
)

_COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("Apple", "Apple Inc"),
    "MSFT": ("Microsoft", "Microsoft Corp"),
    "NVDA": ("NVIDIA", "Nvidia"),
    "AMZN": ("Amazon", "Amazon.com", "AWS"),
    "META": ("Meta", "Meta Platforms", "Facebook"),
    "GOOGL": ("Alphabet", "Google"),
    "TSLA": ("Tesla",),
    "CRM": ("Salesforce",),
    "SNOW": ("Snowflake",),
    "CRWD": ("CrowdStrike",),
    "PANW": ("Palo Alto Networks", "Palo Alto"),
    "FTNT": ("Fortinet",),
}

_PERSON_NAME_RE = re.compile(
    r"\b([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?"
    r"(?:\s+[A-Z]\.)?"
    r"(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,3}"
    r"(?:\s+Jr\.?)?)\b"
)


def _read_json(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_company_alias(value: str) -> str:
    base = _normalize_space(value).lower()
    base = re.sub(r"[^a-z0-9 ]+", " ", base)
    base = re.sub(
        r"\b(inc|incorporated|corp|corporation|holdings|company|co|ltd|plc)\b",
        " ",
        base,
    )
    return _normalize_space(base)


def _hash_id(prefix: str, *parts: str) -> str:
    raw = "|".join(_normalize_space(p) for p in parts if p is not None)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _date_key(value: str | None) -> tuple[int, int, int]:
    if not value:
        return (0, 0, 0)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt.year, dt.month, dt.day)
    except ValueError:
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _is_noise_chunk(text: str) -> bool:
    t = _normalize_space(text)
    if len(t) < 80:
        return True
    alpha = sum(1 for ch in t if ch.isalpha())
    if alpha < 30:
        return True
    digits = sum(1 for ch in t if ch.isdigit())
    if digits > alpha:
        return True
    upper_tokens = sum(1 for tok in t.split() if tok.isupper() and len(tok) > 2)
    return upper_tokens > max(20, len(t.split()) // 2)


def _compact_text(text: str, max_len: int = 460) -> str:
    t = _normalize_space(text)
    if len(t) <= max_len:
        return t
    truncated = t[: max_len - 3].rstrip(" ,;:-")
    return f"{truncated}..."


def _risk_category(text: str) -> str:
    lower = text.lower()
    for needle, category in _RISK_CATEGORY_PATTERNS:
        if needle in lower:
            return category
    return "general"


def _litigation_category(text: str) -> str:
    lower = text.lower()
    for needle, category in _LITIGATION_CATEGORY_PATTERNS:
        if needle in lower:
            return category
    return "general"


def _looks_like_person_name(name: str) -> bool:
    clean = _normalize_space(name).strip(",.;:")
    if len(clean) < 5 or len(clean) > 60:
        return False
    parts = clean.split()
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
    if parts and parts[-1].lower() in suffixes:
        parts = parts[:-1]
    if len(parts) < 2 or len(parts) > 4:
        return False
    if any(ch.isdigit() for ch in clean):
        return False
    if clean.isupper():
        return False
    if len(set(p.lower().strip(".") for p in parts)) == 1:
        return False

    for idx, part in enumerate(parts):
        plain = part.strip(".,")
        lower = plain.lower()
        if lower in _BOARD_BLOCK_WORDS:
            return False
        if re.fullmatch(r"[A-Z]\.", part):
            if idx == 0 or idx == len(parts) - 1:
                return False
            continue
        if not re.fullmatch(r"[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?", plain):
            return False

    first = parts[0].strip(".,").lower()
    last = parts[-1].strip(".,").lower()
    if first in _BOARD_BLOCK_WORDS or last in _BOARD_BLOCK_WORDS:
        return False
    return True


def _person_context(text: str, start: int, end: int) -> bool:
    left = max(0, start - 90)
    right = min(len(text), end + 90)
    window = text[left:right].lower()
    cues = (
        "director",
        "board",
        "chief",
        "officer",
        "chair",
        "nominee",
        "committee",
        "president",
        "served",
        "elect",
        "mr.",
        "ms.",
        "dr.",
    )
    return any(cue in window for cue in cues)


def _extract_names_from_election_block(text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r"to elect\s+(.+?)(?:\.|\n|$)", text, flags=re.I | re.S):
        block = _normalize_space(match.group(1))
        block = re.sub(r"\band\b", ",", block, flags=re.I)
        block = block.replace(";", ",")
        for part in block.split(","):
            candidate = _normalize_space(part)
            if _looks_like_person_name(candidate):
                names.append(candidate)
    return names


def _extract_board_candidates(text: str) -> list[str]:
    clean = text.replace("\r", " ").replace("\u00a0", " ")
    out: list[str] = []
    out.extend(_extract_names_from_election_block(clean))

    for line in clean.splitlines():
        candidate_line = _normalize_space(line)
        if not (4 <= len(candidate_line) <= 80):
            continue
        if "@" in candidate_line or "www." in candidate_line.lower():
            continue
        # Keep line-level extraction only when the line is effectively a name token.
        bare = re.sub(r"\(.*?\)", "", candidate_line).strip(" -:,;")
        if re.fullmatch(
            r"[A-Z][A-Za-z'-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][A-Za-z'-]+){1,2}(?:\s+Jr\.?)?",
            bare,
        ):
            if _looks_like_person_name(bare):
                out.append(bare)

    deduped: list[str] = []
    seen: set[str] = set()
    for name in out:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(name)
    return deduped


def _infer_board_title(text: str, name: str) -> str:
    lowered = text.lower()
    name_idx = lowered.find(name.lower())
    if name_idx < 0:
        return "Director"
    left = max(0, name_idx - 120)
    right = min(len(lowered), name_idx + len(name) + 120)
    window = lowered[left:right]
    for needle, title in _BOARD_TITLE_PATTERNS:
        if needle in window:
            return title
    return "Director"


def _extract_subsidiary_names(text: str, parent_name: str) -> list[str]:
    candidates: list[str] = []
    patterns = (
        r"([A-Z][A-Za-z0-9&.,' -]{2,80}?)\s*,?\s+(?:an?\s+)?subsidiary of",
        r"through\s+(?:its|our)\s+subsidiary\s+([A-Z][A-Za-z0-9&.,' -]{2,80})",
        r"subsidiary,\s*([A-Z][A-Za-z0-9&.,' -]{2,80})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            candidate = _normalize_space(match.group(1)).strip(",.;:")
            if len(candidate) < 4:
                continue
            if any(ch.isdigit() for ch in candidate):
                continue
            if _normalize_company_alias(candidate) == _normalize_company_alias(parent_name):
                continue
            if "company" in candidate.lower() and len(candidate.split()) < 3:
                continue
            candidates.append(candidate)

    unique: list[str] = []
    seen: set[str] = set()
    for name in candidates:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def _parse_json_obj(text: str) -> dict[str, Any]:
    raw = _normalize_space(text)
    if not raw:
        return {}
    raw = re.sub(r"^```[a-zA-Z]*", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _build_extractor_llm_client() -> tuple[Any, str] | tuple[None, None]:
    try:
        client, model = build_llm_client()
        return client, model
    except Exception:
        pass

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if OpenAI is None or not groq_key:
        return None, None
    model = os.environ.get("KG_LLM_MODEL", "").strip() or "llama-3.3-70b-versatile"
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
    return client, model


def _extract_board_with_llm(
    llm_client: Any,
    llm_model: str,
    *,
    company_name: str,
    chunks: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if not chunks:
        return []
    payload_parts: list[str] = []
    for idx, row in enumerate(chunks[:10], start=1):
        text = _compact_text(str(row.get("text", "")), max_len=900)
        payload_parts.append(f"[Chunk {idx}] {text}")

    prompt = (
        "Extract board members for the company below.\n"
        "Return JSON only in this shape:\n"
        '{"board_members":[{"name":"...", "title":"..."}]}\n'
        "Rules:\n"
        "- Keep only real people names.\n"
        "- Ignore headings and table-of-contents fragments.\n"
        "- title should be concise (Director, Chair, CEO, CFO, etc.).\n\n"
        f"Company: {company_name}\n\n"
        + "\n\n".join(payload_parts)
    )
    try:
        resp = llm_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": "You extract structured entities from SEC proxy text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        parsed = _parse_json_obj(resp.choices[0].message.content or "")
    except Exception:
        return []

    out: list[dict[str, str]] = []
    for row in parsed.get("board_members", []) or []:
        if not isinstance(row, dict):
            continue
        name = _normalize_space(str(row.get("name", "")))
        title = _normalize_space(str(row.get("title", ""))) or "Director"
        if _looks_like_person_name(name):
            out.append({"name": name, "title": title})
    return out


def _resolve_company_key(
    metadata: dict[str, Any],
    *,
    ticker_to_key: dict[str, str],
    cik_to_key: dict[str, str],
    alias_to_key: dict[str, str],
) -> str | None:
    ticker = _normalize_space(str(metadata.get("ticker", ""))).upper()
    if ticker and ticker in ticker_to_key:
        return ticker_to_key[ticker]

    cik = _normalize_space(str(metadata.get("cik", "")))
    if cik and cik in cik_to_key:
        return cik_to_key[cik]

    for name_key in ("company_name", "company", "assignee"):
        raw_name = metadata.get(name_key)
        if not raw_name:
            continue
        alias = _normalize_company_alias(str(raw_name))
        if alias and alias in alias_to_key:
            return alias_to_key[alias]
    return None


def _extract_accession(value: str) -> str:
    text = _normalize_space(value)
    match = re.search(r"(\d{10}-\d{2}-\d{6})", text)
    return match.group(1) if match else ""


def _load_xbrl_filing_rows(
    db_path: str | os.PathLike[str],
    *,
    cik_to_key: dict[str, str],
    ticker_to_key: dict[str, str],
) -> list[dict[str, str]]:
    path = Path(db_path)
    if not path.exists():
        return []

    rows: list[dict[str, str]] = []
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return rows

    try:
        cur = conn.cursor()
        ticker_by_cik: dict[str, str] = {}
        try:
            cur.execute("SELECT cik, ticker FROM companies")
            for cik, ticker in cur.fetchall():
                if cik and ticker:
                    ticker_by_cik[str(cik).strip()] = str(ticker).strip().upper()
        except sqlite3.Error:
            ticker_by_cik = {}

        cur.execute(
            """
            SELECT cik, filing_type, filed_date, accession_number
            FROM financial_facts
            WHERE accession_number IS NOT NULL
            GROUP BY cik, filing_type, filed_date, accession_number
            """
        )
        for cik, filing_type, filed_date, accession in cur.fetchall():
            cik_text = _normalize_space(str(cik or ""))
            filing_type_text = _normalize_space(str(filing_type or ""))
            filed_date_text = _normalize_space(str(filed_date or ""))
            accession_text = _normalize_space(str(accession or ""))
            if not cik_text or not filing_type_text or not accession_text:
                continue
            company_key = cik_to_key.get(cik_text)
            if not company_key:
                ticker = ticker_by_cik.get(cik_text, "")
                company_key = ticker_to_key.get(ticker, "")
            if not company_key:
                continue
            rows.append(
                {
                    "company_key": company_key,
                    "cik": cik_text,
                    "filing_type": filing_type_text,
                    "filing_date": filed_date_text,
                    "accession_number": accession_text,
                    "source": "xbrl",
                    "period_of_report": "",
                }
            )
    except sqlite3.Error:
        return rows
    finally:
        conn.close()
    return rows


def extract_entities(
    *,
    proxy_chunks_path: str | os.PathLike[str] = "output/proxy/chunked_documents.json",
    edgar_chunks_path: str | os.PathLike[str] = "output/edgar/chunked_documents.json",
    patents_chunks_path: str | os.PathLike[str] = "output/patents/chunked_documents.json",
    transcripts_chunks_path: str | os.PathLike[str] = "output/transcripts/chunked_documents.json",
    xbrl_db_path: str | os.PathLike[str] = "output/xbrl/financials.db",
    company_facts_path: str | os.PathLike[str] = "output/company_facts/companies.json",
    output_path: str | os.PathLike[str] = "output/knowledge_graph/entities.json",
    use_llm: bool = True,
    max_proxy_chunks: int = 120,
    max_risk_chunks: int = 180,
) -> dict[str, Any]:
    """Extract graph entities from source JSON files and persist them."""
    company_facts = _read_json(company_facts_path)
    edgar_rows = _read_json(edgar_chunks_path)
    proxy_rows = _read_json(proxy_chunks_path)
    patent_rows = _read_json(patents_chunks_path)
    transcript_rows = _read_json(transcripts_chunks_path)

    companies: list[dict[str, Any]] = []
    ticker_to_key: dict[str, str] = {}
    cik_to_key: dict[str, str] = {}
    alias_to_key: dict[str, str] = {}
    company_meta: dict[str, dict[str, Any]] = {}

    for row in company_facts:
        ticker = _normalize_space(str(row.get("ticker") or (row.get("tickers") or [""])[0])).upper()
        if not ticker:
            continue
        cik = _normalize_space(str(row.get("cik", "")))
        entry = {
            "company_key": ticker,
            "name": _normalize_space(str(row.get("name", ticker))),
            "ticker": ticker,
            "cik": cik,
            "sic": _normalize_space(str(row.get("sic", ""))),
            "sic_description": _normalize_space(str(row.get("sic_description", ""))),
        }
        companies.append(entry)
        ticker_to_key[ticker] = ticker
        if cik:
            cik_to_key[cik] = ticker
        company_meta[ticker] = entry

        alias_to_key[_normalize_company_alias(entry["name"])] = ticker
        alias_to_key[_normalize_company_alias(ticker)] = ticker
        for alias in _COMPANY_ALIASES.get(ticker, ()):
            alias_to_key[_normalize_company_alias(alias)] = ticker

    companies.sort(key=lambda x: x["ticker"])

    xbrl_filing_rows = _load_xbrl_filing_rows(
        xbrl_db_path,
        cik_to_key=cik_to_key,
        ticker_to_key=ticker_to_key,
    )

    # 1) Collect latest filings by (company, filing_type) from all datasets.
    latest_filing_by_type: dict[tuple[str, str], dict[str, Any]] = {}

    for row in edgar_rows + proxy_rows:
        metadata = row.get("metadata", {}) or {}
        filing_type = _normalize_space(str(metadata.get("filing_type", "")))
        accession_number = _normalize_space(str(metadata.get("accession_number", "")))
        filing_date = _normalize_space(str(metadata.get("filing_date", "")))
        if not filing_type or not accession_number:
            continue
        company_key = _resolve_company_key(
            metadata,
            ticker_to_key=ticker_to_key,
            cik_to_key=cik_to_key,
            alias_to_key=alias_to_key,
        )
        if not company_key:
            continue
        key = (company_key, filing_type)
        existing = latest_filing_by_type.get(key)
        if not existing or _date_key(filing_date) > _date_key(existing.get("filing_date")):
            latest_filing_by_type[key] = {
                "company_key": company_key,
                "accession_number": accession_number,
                "filing_type": filing_type,
                "filing_date": filing_date,
                "period_of_report": _normalize_space(str(metadata.get("period_of_report", ""))),
                "source": _normalize_space(str(metadata.get("source", "sec_edgar") or "sec_edgar")),
            }

    for row in transcript_rows:
        metadata = row.get("metadata", {}) or {}
        company_key = _resolve_company_key(
            metadata,
            ticker_to_key=ticker_to_key,
            cik_to_key=cik_to_key,
            alias_to_key=alias_to_key,
        )
        if not company_key:
            continue

        filing_type = "EARNINGS_TRANSCRIPT"
        filing_date = _normalize_space(str(metadata.get("transcript_date", "")))
        accession_number = _extract_accession(str(metadata.get("transcript_url", "")))
        if not accession_number:
            accession_number = _hash_id(
                "transcript",
                company_key,
                filing_date,
                str(metadata.get("transcript_title", "")),
            )
        key = (company_key, filing_type)
        existing = latest_filing_by_type.get(key)
        if not existing or _date_key(filing_date) > _date_key(existing.get("filing_date")):
            latest_filing_by_type[key] = {
                "company_key": company_key,
                "accession_number": accession_number,
                "filing_type": filing_type,
                "filing_date": filing_date,
                "period_of_report": "",
                "source": _normalize_space(str(metadata.get("source", "earnings_transcript"))),
            }

    for row in xbrl_filing_rows:
        company_key = row["company_key"]
        filing_type = _normalize_space(str(row.get("filing_type", "")))
        accession_number = _normalize_space(str(row.get("accession_number", "")))
        filing_date = _normalize_space(str(row.get("filing_date", "")))
        if not filing_type or not accession_number:
            continue
        key = (company_key, f"{filing_type}_XBRL")
        existing = latest_filing_by_type.get(key)
        if not existing or _date_key(filing_date) > _date_key(existing.get("filing_date")):
            latest_filing_by_type[key] = {
                "company_key": company_key,
                "accession_number": accession_number,
                "filing_type": f"{filing_type}_XBRL",
                "filing_date": filing_date,
                "period_of_report": "",
                "source": "xbrl",
            }

    filing_by_id: dict[str, dict[str, Any]] = {}
    latest_10k_by_company: dict[str, str] = {}
    latest_proxy_by_company: dict[str, str] = {}

    for filing in latest_filing_by_type.values():
        company_key = filing["company_key"]
        accession = filing["accession_number"]
        filing_id = f"{company_key}:{accession}"
        filing_type = filing["filing_type"]
        record = {
            "filing_id": filing_id,
            "accession_number": accession,
            "filing_type": filing_type,
            "filing_date": filing["filing_date"],
            "period_of_report": filing["period_of_report"],
            "source": filing["source"],
            "company_key": company_key,
            "company_name": company_meta.get(company_key, {}).get("name", company_key),
            "ticker": company_key,
            "cik": company_meta.get(company_key, {}).get("cik", ""),
        }
        filing_by_id[filing_id] = record

        if filing_type == "10-K":
            latest_10k_by_company[company_key] = accession
        elif filing_type == "DEF 14A":
            latest_proxy_by_company[company_key] = accession

    # 2) Board members from latest proxy sections.
    board_map: dict[tuple[str, str], dict[str, Any]] = {}
    proxy_chunks_for_llm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    processed_proxy_chunks = 0

    for row in proxy_rows:
        metadata = row.get("metadata", {}) or {}
        company_key = _resolve_company_key(
            metadata,
            ticker_to_key=ticker_to_key,
            cik_to_key=cik_to_key,
            alias_to_key=alias_to_key,
        )
        if not company_key:
            continue
        accession = _normalize_space(str(metadata.get("accession_number", "")))
        if not accession or latest_proxy_by_company.get(company_key) != accession:
            continue

        section = _normalize_space(str(metadata.get("section", ""))).lower()
        if section and section not in _BOARD_SECTIONS:
            continue

        text = str(row.get("text", ""))
        if _is_noise_chunk(text):
            continue

        processed_proxy_chunks += 1
        if processed_proxy_chunks <= max_proxy_chunks:
            proxy_chunks_for_llm[company_key].append(row)

        filing_id = f"{company_key}:{accession}"
        for name in _extract_board_candidates(text):
            title = _infer_board_title(text, name)
            key = (company_key, name.lower())
            existing = board_map.get(key)
            if existing:
                if existing["title"] == "Director" and title != "Director":
                    existing["title"] = title
                continue
            board_map[key] = {
                "name": name,
                "title": title,
                "company_key": company_key,
                "company_name": company_meta.get(company_key, {}).get("name", company_key),
                "ticker": company_key,
                "cik": company_meta.get(company_key, {}).get("cik", ""),
                "source": "proxy_statement",
                "filing_id": filing_id,
            }

    llm_calls = 0
    if use_llm:
        llm_client, llm_model = _build_extractor_llm_client()
        if llm_client and llm_model:
            for company_key, chunks in proxy_chunks_for_llm.items():
                existing_for_company = [
                    row for (key_company, _), row in board_map.items() if key_company == company_key
                ]
                if len(existing_for_company) >= 5:
                    continue
                llm_rows = _extract_board_with_llm(
                    llm_client,
                    llm_model,
                    company_name=company_meta.get(company_key, {}).get("name", company_key),
                    chunks=chunks,
                )
                if not llm_rows:
                    continue
                llm_calls += 1
                filing_id = ""
                latest_acc = latest_proxy_by_company.get(company_key)
                if latest_acc:
                    filing_id = f"{company_key}:{latest_acc}"
                for row in llm_rows:
                    name = row["name"]
                    title = row["title"] or "Director"
                    key = (company_key, name.lower())
                    existing = board_map.get(key)
                    if existing:
                        if existing["title"] == "Director" and title != "Director":
                            existing["title"] = title
                        continue
                    board_map[key] = {
                        "name": name,
                        "title": title,
                        "company_key": company_key,
                        "company_name": company_meta.get(company_key, {}).get("name", company_key),
                        "ticker": company_key,
                        "cik": company_meta.get(company_key, {}).get("cik", ""),
                        "source": "proxy_statement_llm",
                        "filing_id": filing_id,
                    }

    # Add executive speakers from transcripts as graph people entities (fallback source).
    for row in transcript_rows:
        metadata = row.get("metadata", {}) or {}
        company_key = _resolve_company_key(
            metadata,
            ticker_to_key=ticker_to_key,
            cik_to_key=cik_to_key,
            alias_to_key=alias_to_key,
        )
        if not company_key:
            continue
        speaker = _normalize_space(str(metadata.get("speaker", "")))
        if not _looks_like_person_name(speaker):
            continue

        speaker_role = _normalize_space(str(metadata.get("speaker_role", "")))
        title = "Executive"
        role_lower = speaker_role.lower()
        for needle, mapped_title in _BOARD_TITLE_PATTERNS:
            if needle in role_lower:
                title = mapped_title
                break
        transcript_date = _normalize_space(str(metadata.get("transcript_date", "")))
        accession = _extract_accession(str(metadata.get("transcript_url", "")))
        if not accession:
            accession = _hash_id(
                "transcript",
                company_key,
                transcript_date,
                str(metadata.get("transcript_title", "")),
            )
        filing_id = f"{company_key}:{accession}"

        key = (company_key, speaker.lower())
        existing = board_map.get(key)
        if existing:
            if existing.get("title") in {"Director", "Executive"} and title not in {"Director", "Executive"}:
                existing["title"] = title
            continue
        board_map[key] = {
            "name": speaker,
            "title": title,
            "company_key": company_key,
            "company_name": company_meta.get(company_key, {}).get("name", company_key),
            "ticker": company_key,
            "cik": company_meta.get(company_key, {}).get("cik", ""),
            "source": "earnings_transcript",
            "filing_id": filing_id,
        }

    board_members = sorted(board_map.values(), key=lambda x: (x["company_key"], x["name"]))

    # 3) Patents from USPTO chunk file.
    patents: list[dict[str, Any]] = []
    patent_seen: set[str] = set()
    for row in patent_rows:
        metadata = row.get("metadata", {}) or {}
        company_key = _resolve_company_key(
            metadata,
            ticker_to_key=ticker_to_key,
            cik_to_key=cik_to_key,
            alias_to_key=alias_to_key,
        )
        if not company_key:
            continue

        patent_id = _normalize_space(str(metadata.get("patent_id", "")))
        if not patent_id or patent_id in patent_seen:
            continue
        patent_seen.add(patent_id)

        title = ""
        text = str(row.get("text", ""))
        m = re.search(r"Patent:\s*(.+)", text, flags=re.I)
        if m:
            title = _normalize_space(m.group(1))
        title = title or _normalize_space(str(metadata.get("title", ""))) or f"Patent {patent_id}"

        patents.append(
            {
                "patent_id": patent_id,
                "title": title,
                "date": _normalize_space(str(metadata.get("patent_date", ""))),
                "company_key": company_key,
                "company_name": company_meta.get(company_key, {}).get("name", company_key),
                "ticker": company_key,
                "cik": company_meta.get(company_key, {}).get("cik", ""),
                "source": _normalize_space(str(metadata.get("source", "uspto") or "uspto")),
            }
        )

    patents.sort(key=lambda x: (x["company_key"], x["date"], x["patent_id"]))

    # 4) Risks, litigation, subsidiaries, competitors from latest 10-K chunks.
    selected_10k_accessions = set(latest_10k_by_company.values())
    risk_factors: list[dict[str, Any]] = []
    litigations: list[dict[str, Any]] = []
    subsidiaries: list[dict[str, Any]] = []
    competitors: list[dict[str, Any]] = []

    risk_seen: set[str] = set()
    litigation_seen: set[str] = set()
    subsidiary_seen: set[tuple[str, str]] = set()
    competitor_seen: set[tuple[str, str, str]] = set()

    per_company_risk_count: Counter[str] = Counter()
    per_company_litigation_count: Counter[str] = Counter()
    max_risk_per_company = max(8, max_risk_chunks // max(len(companies), 1))
    max_litigation_per_company = 14

    competitor_alias_patterns: dict[str, tuple[re.Pattern[str], ...]] = {}
    for ticker, aliases in _COMPANY_ALIASES.items():
        patterns: list[re.Pattern[str]] = []
        for alias in aliases:
            escaped = re.escape(alias)
            patterns.append(re.compile(rf"\b{escaped}\b", flags=re.I))
        patterns.append(re.compile(rf"\b{re.escape(ticker)}\b", flags=re.I))
        competitor_alias_patterns[ticker] = tuple(patterns)

    for row in edgar_rows:
        metadata = row.get("metadata", {}) or {}
        company_key = _resolve_company_key(
            metadata,
            ticker_to_key=ticker_to_key,
            cik_to_key=cik_to_key,
            alias_to_key=alias_to_key,
        )
        if not company_key:
            continue

        accession = _normalize_space(str(metadata.get("accession_number", "")))
        filing_type = _normalize_space(str(metadata.get("filing_type", "")))
        if filing_type != "10-K" or accession not in selected_10k_accessions:
            continue
        if latest_10k_by_company.get(company_key) != accession:
            continue

        filing_id = f"{company_key}:{accession}"
        item_number = _normalize_space(str(metadata.get("item_number", ""))).upper()
        text = str(row.get("text", ""))
        if _is_noise_chunk(text):
            continue
        lower = text.lower()

        # Subsidiaries
        if "subsidiar" in lower:
            names = _extract_subsidiary_names(text, company_meta.get(company_key, {}).get("name", company_key))
            if not names and ("wholly owned subsidiaries" in lower or "its subsidiaries" in lower):
                names = ["Wholly Owned Subsidiaries"]
            for name in names:
                dedupe_key = (company_key, name.lower())
                if dedupe_key in subsidiary_seen:
                    continue
                subsidiary_seen.add(dedupe_key)
                subsidiary_id = _hash_id("subs", company_key, name)
                subsidiaries.append(
                    {
                        "subsidiary_id": subsidiary_id,
                        "name": name,
                        "parent_company_key": company_key,
                        "source": "sec_10k",
                        "company_key": company_key,
                        "company_name": company_meta.get(company_key, {}).get("name", company_key),
                        "ticker": company_key,
                        "cik": company_meta.get(company_key, {}).get("cik", ""),
                        "filing_id": filing_id,
                    }
                )

        # Risk factors
        is_risk_chunk = item_number in {"1A", "P1-1A", "P2-1A"} or (
            "risk factor" in lower and item_number in {"1", "7", "8"}
        )
        if is_risk_chunk and per_company_risk_count[company_key] < max_risk_per_company:
            excerpt = _compact_text(text, max_len=520)
            if len(excerpt) >= 120:
                risk_id = _hash_id("risk", company_key, filing_id, excerpt[:220])
                if risk_id not in risk_seen:
                    risk_seen.add(risk_id)
                    risk_factors.append(
                        {
                            "risk_id": risk_id,
                            "text": excerpt,
                            "category": _risk_category(excerpt),
                            "company_key": company_key,
                            "company_name": company_meta.get(company_key, {}).get("name", company_key),
                            "ticker": company_key,
                            "cik": company_meta.get(company_key, {}).get("cik", ""),
                            "filing_id": filing_id,
                            "source": "sec_10k_item_1a",
                        }
                    )
                    per_company_risk_count[company_key] += 1

        # Litigation / legal proceedings
        legal_hit = item_number == "3" or any(
            kw in lower for kw in ("legal proceeding", "litigation", "lawsuit", "claim", "defendant")
        )
        if legal_hit and per_company_litigation_count[company_key] < max_litigation_per_company:
            excerpt = _compact_text(text, max_len=520)
            if len(excerpt) >= 120:
                lit_id = _hash_id("lit", company_key, filing_id, excerpt[:240])
                if lit_id not in litigation_seen:
                    litigation_seen.add(lit_id)
                    litigations.append(
                        {
                            "litigation_id": lit_id,
                            "text": excerpt,
                            "category": _litigation_category(excerpt),
                            "company_key": company_key,
                            "company_name": company_meta.get(company_key, {}).get("name", company_key),
                            "ticker": company_key,
                            "cik": company_meta.get(company_key, {}).get("cik", ""),
                            "filing_id": filing_id,
                            "source": "sec_10k_legal",
                        }
                    )
                    per_company_litigation_count[company_key] += 1

        # Competitor mentions
        if "compet" in lower or "rival" in lower or "market share" in lower:
            for target_ticker, patterns in competitor_alias_patterns.items():
                if target_ticker == company_key:
                    continue
                if any(p.search(text) for p in patterns):
                    edge_key = (company_key, target_ticker, "filing_mention")
                    if edge_key in competitor_seen:
                        continue
                    competitor_seen.add(edge_key)
                    competitors.append(
                        {
                            "company_key": company_key,
                            "target_company_key": target_ticker,
                            "source": "sec_10k_text",
                            "reason": "filing_mention",
                            "confidence": 0.85,
                            "filing_id": filing_id,
                        }
                    )

    # Additional risk/litigation signals from transcripts (forward-looking sections).
    for row in transcript_rows:
        metadata = row.get("metadata", {}) or {}
        company_key = _resolve_company_key(
            metadata,
            ticker_to_key=ticker_to_key,
            cik_to_key=cik_to_key,
            alias_to_key=alias_to_key,
        )
        if not company_key:
            continue
        text = str(row.get("text", ""))
        if _is_noise_chunk(text):
            continue
        lower = text.lower()

        transcript_date = _normalize_space(str(metadata.get("transcript_date", "")))
        accession = _extract_accession(str(metadata.get("transcript_url", "")))
        if not accession:
            accession = _hash_id(
                "transcript",
                company_key,
                transcript_date,
                str(metadata.get("transcript_title", "")),
            )
        filing_id = f"{company_key}:{accession}"

        if (
            any(k in lower for k in ("risk", "forward-looking", "uncertaint", "headwind"))
            and per_company_risk_count[company_key] < max_risk_per_company
        ):
            excerpt = _compact_text(text, max_len=420)
            if len(excerpt) >= 100:
                risk_id = _hash_id("risk", company_key, filing_id, excerpt[:220])
                if risk_id not in risk_seen:
                    risk_seen.add(risk_id)
                    risk_factors.append(
                        {
                            "risk_id": risk_id,
                            "text": excerpt,
                            "category": _risk_category(excerpt),
                            "company_key": company_key,
                            "company_name": company_meta.get(company_key, {}).get("name", company_key),
                            "ticker": company_key,
                            "cik": company_meta.get(company_key, {}).get("cik", ""),
                            "filing_id": filing_id,
                            "source": "earnings_transcript",
                        }
                    )
                    per_company_risk_count[company_key] += 1

        if (
            any(k in lower for k in ("legal proceeding", "litigation", "lawsuit", "investigation"))
            and per_company_litigation_count[company_key] < max_litigation_per_company
        ):
            excerpt = _compact_text(text, max_len=420)
            if len(excerpt) >= 100:
                lit_id = _hash_id("lit", company_key, filing_id, excerpt[:240])
                if lit_id not in litigation_seen:
                    litigation_seen.add(lit_id)
                    litigations.append(
                        {
                            "litigation_id": lit_id,
                            "text": excerpt,
                            "category": _litigation_category(excerpt),
                            "company_key": company_key,
                            "company_name": company_meta.get(company_key, {}).get("name", company_key),
                            "ticker": company_key,
                            "cik": company_meta.get(company_key, {}).get("cik", ""),
                            "filing_id": filing_id,
                            "source": "earnings_transcript",
                        }
                    )
                    per_company_litigation_count[company_key] += 1

    # Subsidiary coverage fallback: keep at least one node per company.
    for company in companies:
        company_key = company["company_key"]
        has_sub = any(row["company_key"] == company_key for row in subsidiaries)
        if has_sub:
            continue
        filing_id = ""
        acc = latest_10k_by_company.get(company_key)
        if acc:
            filing_id = f"{company_key}:{acc}"
        name = "Wholly Owned Subsidiaries"
        dedupe_key = (company_key, name.lower())
        if dedupe_key in subsidiary_seen:
            continue
        subsidiary_seen.add(dedupe_key)
        subsidiaries.append(
            {
                "subsidiary_id": _hash_id("subs", company_key, name),
                "name": name,
                "parent_company_key": company_key,
                "source": "coverage_fallback",
                "company_key": company_key,
                "company_name": company["name"],
                "ticker": company_key,
                "cik": company.get("cik", ""),
                "filing_id": filing_id,
            }
        )

    # Competitor fallback by SIC peers, then broader sector similarity.
    sic_groups: dict[str, list[str]] = defaultdict(list)
    for company in companies:
        sic = _normalize_space(str(company.get("sic", "")))
        if sic:
            sic_groups[sic].append(company["company_key"])

    for _, peers in sic_groups.items():
        if len(peers) < 2:
            continue
        for source in peers:
            for target in peers:
                if source == target:
                    continue
                key = (source, target, "same_sic")
                if key in competitor_seen:
                    continue
                competitor_seen.add(key)
                competitors.append(
                    {
                        "company_key": source,
                        "target_company_key": target,
                        "source": "company_facts",
                        "reason": "same_sic",
                        "confidence": 0.65,
                    }
                )

    for company in companies:
        source = company["company_key"]
        existing_targets = {
            row["target_company_key"] for row in competitors if row["company_key"] == source
        }
        if existing_targets:
            continue
        source_sic = _normalize_space(str(company.get("sic", "")))
        source_prefix = source_sic[:2] if len(source_sic) >= 2 else ""
        candidates: list[tuple[int, str]] = []
        for target in companies:
            target_key = target["company_key"]
            if target_key == source:
                continue
            target_sic = _normalize_space(str(target.get("sic", "")))
            score = 0
            if source_sic and target_sic and source_sic == target_sic:
                score = 3
            elif source_prefix and target_sic.startswith(source_prefix):
                score = 2
            elif source_sic and target_sic:
                score = 1
            candidates.append((score, target_key))
        candidates.sort(key=lambda x: (-x[0], x[1]))
        for _, target_key in candidates[:2]:
            key = (source, target_key, "sector_similarity")
            if key in competitor_seen:
                continue
            competitor_seen.add(key)
            competitors.append(
                {
                    "company_key": source,
                    "target_company_key": target_key,
                    "source": "company_facts",
                    "reason": "sector_similarity",
                    "confidence": 0.4,
                }
            )

    # Cross-company board memberships for downstream use.
    companies_by_board_name: dict[str, set[str]] = defaultdict(set)
    for row in board_members:
        companies_by_board_name[row["name"]].add(row["company_key"])

    cross_company_board_memberships: list[dict[str, Any]] = []
    for name, keys in sorted(companies_by_board_name.items()):
        if len(keys) < 2:
            continue
        for target in sorted(keys):
            cross_company_board_memberships.append(
                {
                    "name": name,
                    "company_key": target,
                    "all_companies": sorted(keys),
                }
            )

    result: dict[str, Any] = {
        "companies": companies,
        "subsidiaries": sorted(subsidiaries, key=lambda x: (x["company_key"], x["name"])),
        "board_members": board_members,
        "filings": sorted(filing_by_id.values(), key=lambda x: (x["company_key"], x["filing_type"])),
        "risk_factors": sorted(risk_factors, key=lambda x: (x["company_key"], x["risk_id"])),
        "patents": patents,
        "litigations": sorted(litigations, key=lambda x: (x["company_key"], x["litigation_id"])),
        "competitors": sorted(
            competitors,
            key=lambda x: (x["company_key"], x["target_company_key"], x.get("reason", "")),
        ),
        "cross_company_board_memberships": cross_company_board_memberships,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "llm_enabled": bool(use_llm),
            "llm_calls": llm_calls,
            "processed_chunks": {
                "edgar": len(edgar_rows),
                "proxy": len(proxy_rows),
                "patents": len(patent_rows),
                "transcripts": len(transcript_rows),
                "xbrl_filings": len(xbrl_filing_rows),
            },
            "source_counts": {
                "companies": len(companies),
                "subsidiaries": len(subsidiaries),
                "board_members": len(board_members),
                "filings": len(filing_by_id),
                "risk_factors": len(risk_factors),
                "patents": len(patents),
                "litigations": len(litigations),
                "competitors": len(competitors),
                "cross_company_board_memberships": len(cross_company_board_memberships),
            },
        },
    }

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result

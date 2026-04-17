# Contradiction Detection Layer

> **Package:** `src/contradiction/`  
> **Entry point:** `from src.contradiction.detector import detect_contradictions`

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Architecture Overview](#2-architecture-overview)
3. [Data Flow](#3-data-flow)
4. [Module Reference](#4-module-reference)
   - [_llm.py — LLM Client Factory](#_llmpy--llm-client-factory)
   - [\_\_init\_\_.py — Shared JSON Parser](#__init__py--shared-json-parser)
   - [detector.py — Main Entry Point](#detectorpy--main-entry-point)
   - [claim\_extractor.py — Step 1: Extract Claims](#claim_extractorpy--step-1-extract-claims)
   - [fact\_extractor.py — Step 2: Extract Facts](#fact_extractorpy--step-2-extract-facts)
   - [comparator.py — Step 3: Compare & Flag](#comparatorpy--step-3-compare--flag)
5. [Transcript Ingestion & Scraper](#5-transcript-ingestion--scraper)
   - [Original Scraper Issue](#original-scraper-issue)
   - [EX-99 Press Release Fallback Fix](#ex-99-press-release-fallback-fix)
   - [Claim Extractor Fallback (MD&A)](#claim-extractor-fallback-mda)
6. [LLM Client Refactor](#6-llm-client-refactor)
   - [What Was Removed](#what-was-removed)
   - [New Home: `_llm.py`](#new-home-_llmpy)
7. [Configuration](#7-configuration)
8. [Output Schema](#8-output-schema)
9. [Design Decisions](#9-design-decisions)
10. [Running the Detector](#10-running-the-detector)

---

## 1. Purpose

The contradiction detection layer surfaces mismatches between what company **management says** in earnings calls and what is **legally disclosed** in SEC 10-K filings. A management claim that "pipeline growth is strong" sitting alongside a Risk Factor disclosure that "we face severe customer concentration risk" is a material contradiction that is directly relevant to M&A due diligence.

The layer is intentionally **read-only and stateless** — it reads pre-ingested JSON chunk files, sends batches to the LLM, and returns structured results. It has no direct database dependency.

---

## 2. Architecture Overview

```
src/contradiction/
├── _llm.py              # LLM client factory (config.yaml-only)
├── __init__.py          # Shared JSON parser (parse_llm_json)
├── detector.py          # Orchestrator — detect_contradictions(ticker)
├── claim_extractor.py   # Step 1: pull management claims with metrics
├── fact_extractor.py    # Step 2: pull disclosed facts with 4-tier prioritization
└── comparator.py        # Steps 3-6: Retrieval, Fast Path, LLM Classify, Post-process
```

**Data sources consumed (read-only):**

| File | Produced by | Used by |
|---|---|---|
| `output/transcripts/chunked_documents.json` | `ingestion/transcripts/pipeline.py` | `claim_extractor.py` |
| `output/edgar/chunked_documents.json` | `ingestion/edgar/` | `fact_extractor.py`, `claim_extractor.py` (fallback) |

---

## 3. Data Flow

```
detect_contradictions("NVDA")
         │
         ▼
  _build_llm_client()          ← reads config.yaml → groq / llama-3.3-70b
         │
   ┌─────┴──────────────────────────────────────────────────────┐
   │ Step 1: extract_claims(ticker, llm)                        │
   │  • load output/transcripts/chunked_documents.json          │
   │  • Extract claims with metric, direction, value fields     │
   │  • batch ≤6 chunks, up to 3 LLM calls                      │
   │  • if 0 claims → fallback to edgar MD&A sections           │
   └──────────────────────────┬─────────────────────────────────┘
                              │ List[ClaimDict]
   ┌──────────────────────────▼─────────────────────────────────┐
   │ Step 2: extract_facts(ticker, llm)                         │
   │  • load output/edgar/chunked_documents.json                │
   │  • filter by CIK, filing_type == "10-K"                    │
   │  • prioritisation: Item 1A → Item 8 → Item 7 → Rest        │
   │  • batch ≤6 chunks, up to 3 LLM calls                      │
   └──────────────────────────┬─────────────────────────────────┘
                              │ List[FactDict]
   ┌──────────────────────────▼─────────────────────────────────┐
   │ Steps 3-6: compare(claims, facts, llm)                     │
   │  • Step 3: Topic-based Retrieval                           │
   │      - filter by dates, rank facts by keyword overlap      │
   │      - extract top-5 most relevant facts per claim         │
   │  • Step 4: Rule-based Fast Path                            │
   │      - check matching (metric, opposite direction)         │
   │      - flags HIGH contradictions instantly                 │
   │  • Step 5: LLM 3-way Classification                        │
   │      - Classifies: contradicted | not_supported | verified │
   │  • Step 6: Post-processing                                 │
   │      - deduplicate, sort by severity, resolve sources      │
   └──────────────────────────┬─────────────────────────────────┘
                              ▼
        { "contradictions": [...], "not_supported": [...], "summary": "..." }
```

---

## 4. Module Reference

### `_llm.py` — LLM Client Factory

**Path:** `src/contradiction/_llm.py`

Builds and returns a single `(client, model_name)` tuple used by all three pipeline stages. This is the **single source of truth** for LLM configuration.

**Public API:**
```python
from src.contradiction._llm import build_llm_client, resolve_llm_config

resolved = resolve_llm_config()   # → {"provider", "api_key", "base_url", "model"}
client, model = build_llm_client()
```

**Resolution rules:**

| Setting | Source |
|---|---|
| Provider | `config.yaml → llm.provider` only |
| Model | `config.yaml → llm.<provider>.model_name` only |
| Base URL | `config.yaml → llm.<provider>.base_url` (fallback to provider default) |
| API Key | Environment variable (`GROQ_API_KEY`, `OPENAI_API_KEY`, etc.) |

No environment variable (e.g. `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`) can override provider/model/URL. This prevents accidental Azure OpenAI injection from the shell environment.

**Supported providers:**

| Provider | Default base URL | Key env var |
|---|---|---|
| `groq` | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `ollama` | `http://localhost:11434/v1` | *(no key needed)* |

All three use the standard `openai.OpenAI` client since they expose an OpenAI-compatible API.

---

### `__init__.py` — Shared JSON Parser

**Path:** `src/contradiction/__init__.py`

Exposes `parse_llm_json(raw, caller)` — the single JSON parser used by all three pipeline stages. Handles:

1. **`<think>…</think>` blocks** emitted by reasoning models (Qwen3, DeepSeek-R1, o1-mini) before the actual JSON.
2. **Markdown fences** (` ```json … ``` `).
3. **Preamble text** — if the model writes a sentence before the array, the parser finds the first `[` or `{`.
4. **JSONDecodeError fallback** — logs a warning and returns `None` instead of raising.

---

### `detector.py` — Main Entry Point

**Path:** `src/contradiction/detector.py`

```python
result = detect_contradictions("AAPL")
# Returns:
# {
#   "contradictions": [...],
#   "not_supported": [...],
#   "summary": "Apple Inc.: Found 3 contradictions (2 high, 1 medium); 2 claims not supported by 10-K disclosures"
# }
```

**What it does:**
- Builds **one shared LLM client** and passes it down to all pipeline stages.
- Logs provider, model, and endpoint at startup for auditability.
- Calls `extract_claims → extract_facts → compare` (which handles steps 3-6) in sequence.
- Builds a human-readable summary line with severity and "not supported" counts.

**CLI smoke-test:**
```powershell
python -m src.contradiction.detector NVDA
# Saves full JSON to output/contradictions_NVDA.json
```

**Ticker → company name map** is embedded directly in the module (12 tickers). Add new tickers here to get proper summary labels.

---

### `claim_extractor.py` — Step 1: Extract Claims

**Path:** `src/contradiction/claim_extractor.py`

Reads `output/transcripts/chunked_documents.json` and uses the LLM to pull forward-looking or assertive management claims.

**Filtering by ticker:**  
Chunks are matched by the `company_name` metadata field using a case-insensitive substring list (e.g. `"NVDA"` → `["nvidia"]`). This tolerates minor variations in company name formatting.

**Token budget control:**

| Constant | Value | Purpose |
|---|---|---|
| `_MAX_CHUNKS_PER_CALL` | 6 | Max transcript chunks combined per LLM call |
| `_MAX_LLM_CALLS` | 3 | Max LLM calls total (covers multiple earnings releases) |

Chunks are grouped by `transcript_title` (each title = one earnings release), then one LLM call per release, up to the call limit. A 1.5 s sleep between calls throttles against Groq's token-per-minute limit.

**LLM prompt goal:**  
Extract claims about revenue growth, product pipeline, market position, customer demand, profitability outlook, competitive advantages, or forward-looking statements.

**Output per claim:**
```json
{
  "claim":     "Revenue grew 6% year-over-year driven by strong services adoption",
  "topic":     "revenue growth",
  "metric":    "revenue",
  "direction": "increase",
  "value":     "6%",
  "source":    "Apple Inc. 8-K Earnings Release (2026-01-29)"
}
```

**Fallback — EDGAR MD&A:**  
If 0 claims are extracted from transcripts (because 8-K wrappers are bare legal shells with no body text), the extractor falls back to the `output/edgar/chunked_documents.json` file and reads Item 7 MD&A sections where management narrates their own results.

Sections matched for fallback: `item 7`, `item 2`, `results of operations`, `management`, `revenue`, `net sales`, `operating income`, `outlook`.

**Non-ASCII sanitisation (`_sanitise`):**  
SEC filings extracted from PDFs frequently contain Windows-1252 curly quotes (`'`, `"`) and em-dashes (`—`) that cause incomplete Unicode escapes inside LLM-emitted JSON strings. These are replaced with ASCII equivalents before the text is sent to the LLM.

---

### `fact_extractor.py` — Step 2: Extract Facts

**Path:** `src/contradiction/fact_extractor.py`

Reads `output/edgar/chunked_documents.json` and extracts material disclosed facts from 10-K filings.

**Filtering logic:**  
- Matches by `cik` metadata first (exact CIK lookup via `_TICKER_TO_CIK` map), with `ticker` field as fallback.
- Only accepts chunks where `filing_type == "10-K"` (ignores 10-Q and 8-K chunks in the same file).

**Section prioritisation (`_prioritise_chunks`):**  
Chunks are sorted into four tiers to ensure the LLM token budget is spent on high-signal content:

1. **Tier 1 (Highest):** Item 1A Risk Factors — qualitative contradictions.
2. **Tier 2:** Item 8 Financial Statements — quantitative contradiction detection.
3. **Tier 3:** Item 7 MD&A — management narrative context.
4. **Tier 4:** All other sections.

The match checks `section`, `item_number`, and `item_title` metadata fields, plus the chunk text itself.

**Token budget:** Same constants as `claim_extractor` (`_MAX_CHUNKS_PER_CALL = 6`, `_MAX_LLM_CALLS = 3`).

**LLM prompt goal:**  
Extract risk factors, financial performance data, customer concentration risks, revenue trends, competitive risks, litigation, regulatory issues, cost pressures, margin disclosures, and material negative developments.

**Output per fact:**
```json
{
  "fact":      "Item 1A discloses significant customer concentration — one customer represents >20% of revenue",
  "section":   "Item 1A Risk Factors",
  "topic":     "customer concentration",
  "metric":    "revenue",
  "direction": "stable",
  "value":     ">20%",
  "source":    "10-K 2024-09-01"
}
```

---

**Path:** `src/contradiction/comparator.py`

Takes the outputs of Steps 1 and 2 and runs an upgraded 4-phase comparison pipeline.

#### Step 3: Topic-based Retrieval
For each claim, the system retrieves only the most relevant facts.
- **Temporal Filter:** Drops stale facts (>400 days), same-source pairs, or facts filed after the claim.
- **Keyword Overlap:** Ranks surviving facts by overlap between claim (topic + metric) and fact (topic + section).
- **Token Efficiency:** Only the top-5 most relevant facts per claim are sent to the LLM.

#### Step 4: Rule-based Fast Path
Deterministic quantitative check that bypasses the LLM.
- **Logic:** If a claim and fact share the same normalised metric (e.g., "revenue") but report opposite directions (e.g., "increase" vs. "decrease"), it is immediately flagged as a **HIGH** severity contradiction.
- **Metric Aliases:** Supports dozens of aliases (e.g., "net sales" → "revenue").

#### Step 5: LLM 3-way Classification
Remaining pairs are batched (5 claims per call) and classified into three outcomes:
1. **contradicted**: Management claim conflicts with the 10-K disclosure.
2. **not_supported**: The 10-K provides no disclosure to support or refute the claim.
3. **verified**: The 10-K disclosure is consistent with the management claim (silently dropped).

#### Step 6: Post-processing
- **Source Resolution:** Maps results back to original JSON objects to prevent LLM hallucinations.
- **Deduplication:** Aggregates redundant contradictions across batches.
- **Sorting:** Orders contradictions by severity (High → Medium → Low).

---

## 5. Transcript Ingestion & Scraper

**Path:** `ingestion/transcripts/`

### Original Scraper Issue

SEC 8-K filings for earnings come in two forms:
1. **Substantive** — the filing body contains the full press release text.
2. **Bare wrapper** — the 8-K document is a minimal legal shell that just states "Refer to Exhibit 99.1" and attaches the press release as a separate `htm` file in the filing index.

The original scraper called `client.download_filing(filing)` which downloaded only the wrapper document. This produced HTML with fewer than 200 characters of body text — the `TranscriptParser` minimum threshold — so the parser returned `[]` and no chunks were produced. The `claim_extractor` would then find 0 transcript chunks and fall back to MD&A sections, reducing signal quality.

### EX-99 Press Release Fallback Fix

The `fetch_from_8k` method in `ingestion/transcripts/scraper.py` was updated to:

1. Call `client.get_filing_index(filing)` to retrieve the list of documents in the filing.
2. Scan the document list for the actual press release by filename pattern:

```python
is_press_release = (
    "ex99"        in name_lower   # AAPL: a8-kex991...htm, MSFT: msft-ex99_1.htm
    or "ex-99"    in name_lower
    or name_lower.endswith("pr.htm")        # NVDA: q4fy26pr.htm
    or "pressrelease"  in name_lower
    or "press-release" in name_lower
    or "earnings-release" in name_lower
    or "exhibit991"  in name_lower          # META, GOOGL, TSLA, CRM
    or "exhibit99"   in name_lower          # TSLA: exhibit9911111.htm
    or name_lower.endswith("earnings.htm")  # SNOW: fy2026q4earnings.htm
)
```

3. If found, download the exhibit URL directly using `requests.get` with the EDGAR `User-Agent` header.
4. If no exhibit URL is found, fall back to the original `client.download_filing(filing)`.

This pattern map was built by inspecting actual filing indexes across the 12 tickers in the project. Different company filing conventions required separate rules:

| Company | Press release filename convention |
|---|---|
| Apple (AAPL) | `a8-kex991q1fy2026.htm` |
| Microsoft (MSFT) | `msft-ex99_1.htm` |
| NVIDIA (NVDA) | `q4fy26pr.htm` |
| Meta / Alphabet / CRM | `exhibit9911111.htm` (or similar) |
| Snowflake (SNOW) | `fy2026q4earnings.htm` |

After this fix, the scraper reliably extracts substantive press release text (typically 10,000–50,000 characters) from all tested tickers, enabling the claim extractor to find management claims without falling back to the MD&A fallback path.

### Claim Extractor Fallback (MD&A)

Even with the scraper fix, the MD&A fallback was retained as a defensive layer for tickers where the 8-K structure cannot be automatically detected. If `extract_claims` returns an empty list after checking all transcript chunks, it loads `output/edgar/chunked_documents.json` and filters for Item 7 management narrative sections, applying the same `_extract_claims_from_text` logic.

---

## 6. LLM Client Refactor

### What Was Removed

The file `src/llm_client.py` has been **deleted**. It was a shared module that previously:
- Read `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL` from environment variables, allowing shell-level overrides to bypass `config.yaml`.
- Contained a full Azure OpenAI (`AzureOpenAI`) branch, including `api_version` and `azure_endpoint` resolution.

Two specific problems with the old approach:
1. **Azure injection risk:** If `AZURE_OPENAI_ENDPOINT` or `LLM_PROVIDER=azure` was set in the environment (e.g. from another project), the contradiction detection pipeline would silently use Azure OpenAI instead of the configured Groq endpoint.
2. **Scattered location:** A shared factory in `src/llm_client.py` was logically separate from the code that used it; all callers were inside `src/contradiction/`.

### New Home: `_llm.py`

The factory was moved to `src/contradiction/_llm.py` with three changes:

| Change | Detail |
|---|---|
| **Deleted Azure branch** | `AzureOpenAI` client construction entirely removed |
| **Removed env overrides** | `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL` env vars no longer consulted |
| **Path anchor adjusted** | `_REPO_ROOT = Path(__file__).resolve().parents[2]` (was `parents[1]` in `src/`) |

All four callers were updated:

| File | Old import | New import |
|---|---|---|
| `detector.py` | `from src.llm_client import build_llm_client, resolve_llm_config` | `from src.contradiction._llm import ...` |
| `claim_extractor.py` | `from src.llm_client import build_llm_client` | `from src.contradiction._llm import ...` |
| `fact_extractor.py` | `from src.llm_client import build_llm_client` | `from src.contradiction._llm import ...` |
| `comparator.py` | `from src.llm_client import build_llm_client` | `from src.contradiction._llm import ...` |

`src/pipeline.py` was **not** changed — its `_build_llm_client` is a separate function that uses `nl2sql.app.config` settings, not this package.

---

## 7. Configuration

All relevant settings in `config.yaml`:

```yaml
llm:
  provider: "groq"          # ← ONLY this value is read; no env override

  groq:
    model_name: "llama-3.3-70b-versatile"
    base_url: "https://api.groq.com/openai/v1"
    temperature: 0

  openai:
    model_name: "gpt-4o-mini"
    temperature: 0

  ollama:
    model_name: "llama3.1"
    base_url: "http://localhost:11434"
    temperature: 0
```

**Required environment variables (in `.env`):**

```env
GROQ_API_KEY=gsk_...          # if provider = groq
OPENAI_API_KEY=sk-...         # if provider = openai
SEC_USER_AGENT=MAOracle user@example.com   # for EDGAR scraping
```

To switch provider: change `llm.provider` in `config.yaml` and set the corresponding API key env var.

---

## 8. Output Schema

```json
{
  "contradictions": [
    {
      "claim":        "We see continued strong momentum in our data center business",
      "fact":         "Item 1A discloses that export restrictions may materially limit data center GPU sales",
      "severity":     "high",
      "explanation":  "Management projected growth while the same-period filing disclosed active regulatory risk to that exact business line",
      "claim_source": "NVIDIA Corporation 8-K Earnings Release (2025-02-26)",
      "fact_source":  "10-K 2025-01-26"
    }
  ],
  "not_supported": [
    {
        "claim": "We expects to gain market share in the automotive segment by late 2025",
        "claim_source": "NVIDIA Corporation 8-K Earnings Release (2025-02-26)",
        "explanation": "No specific disclosure found in the 10-K regarding automotive market share projections."
    }
  ],
  "summary": "NVIDIA Corporation: Found 1 contradiction (1 high); 1 claim not supported by 10-K disclosures"
}
```

JSON output is also saved to `output/contradictions_<TICKER>.json` when running via the CLI.

---

## 9. Design Decisions

**One LLM client, shared across all stages.**  
Building three separate clients would make three cold-start connections. The detector builds one client and passes it down to all pipeline stages.

**Topic-based retrieval before LLM calls (Step 3).**  
Comparing every management claim against every risk factor created too much noise for the LLM. By pre-filtering for temporal relevance and then ranking facts by keyword overlap, we provide a dense, high-signal context for each comparison, improving accuracy and reducing token usage.

**Rule-based fast-path for quantitative claims (Step 4).**  
LLMs can occasionally struggle with precise numeric directionality mismatches. A deterministic Python rule that flags opposite directions (e.g., "grew" in transcript vs. "declined" in 10-K) for the same metric provides a 100% reliable baseline for core financial contradictions.

**3-way classification including `not_supported`.**  
Traditional contradiction detectors often skip "neutral" cases. By explicitly identifying claims that are `not_supported` by any filing disclosure, we surface "silent risks" where management is making assertions that are legally absent from SEC filings.

**Post-LLM exact-pair validation.**  
LLMs sometimes paraphrase or hallucinate text when generating JSON. The comparator resolves each result back to the original Python objects using normalized comparison. Results that cannot be mapped are discarded to prevent false positives.

**`STALE_DAYS = 400` window.**  
Allows a prior-year 10-K to be checked against current calls while excluding truly obsolete data.

**Fallback chain for transcripts.**  
The detection system is designed to always produce results even when the primary data source (Motley Fool transcripts) is unavailable or when 8-Ks are bare wrappers. The fallback chain is:
1. Motley Fool transcript HTML scraping
2. SEC 8-K EX-99 press release direct download
3. EDGAR MD&A sections (Item 7) as management narrative

**No Azure OpenAI.**  
Azure was removed entirely because the project's `config.yaml` does not define an `azure` provider block. Keeping dead code paths that can be inadvertently activated by environment variables is a reliability risk.

---

## 10. Running the Detector

**Single ticker (CLI):**
```powershell
python -m src.contradiction.detector NVDA
```

**Programmatic:**
```python
from src.contradiction.detector import detect_contradictions

result = detect_contradictions("AAPL")
print(result["summary"])
for item in result["contradictions"]:
    print(f"[{item['severity'].upper()}] {item['claim'][:80]}")
    print(f"  ↳ {item['fact'][:80]}")
```

**Required data (must be ingested first):**
```powershell
# Ingest EDGAR 10-K filings
python run_ingestion.py --sources edgar --tickers AAPL

# Ingest earnings transcripts (8-K press releases)
python run_ingestion.py --sources transcripts --tickers AAPL
```

**Expected output files:**
```
output/
├── edgar/
│   └── chunked_documents.json      ← 10-K facts source
├── transcripts/
│   └── chunked_documents.json      ← management claims source
└── contradictions_AAPL.json        ← detector output
```

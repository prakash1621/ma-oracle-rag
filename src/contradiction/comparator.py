"""Contradiction comparator — 6-step pipeline to flag management vs. filing mismatches.

Pipeline stages executed inside compare():

  Step 3 — Topic/metric-based retrieval
      For each claim, apply temporal filtering then score all surviving facts
      by keyword overlap (topic + metric + text). Keep the top-5 most relevant
      facts per claim. Eliminates irrelevant claim×fact pairs before any LLM call.

  Step 4 — Rule-based fast path (no LLM)
      If a claim and fact share the same normalised metric (e.g. "revenue") but
      report opposite directions (grew vs. declined), the pair is immediately
      flagged HIGH. Zero token cost; deterministic.

  Step 5 — LLM 3-way classification
      Remaining (claim, top-facts) pairs are sent to the LLM in batches of 5.
      Each claim is paired with only its retrieved top-5 facts — the LLM never
      sees irrelevant facts. Classification outcomes:
          contradicted   → added to the "contradictions" output list
          not_supported  → added to the "not_supported" output list
          verified       → silently dropped

  Step 6 — Post-processing
      Deduplicate by (claim[:80], fact[:80]) key.
      Sort contradictions: high → medium → low.
      Deduplicate not_supported by claim[:80] key.

Temporal filtering runs inside _retrieve_relevant_facts (Step 3):
  - Same-source pairs are dropped.
  - Facts filed after the claim date are dropped.
  - Facts older than STALE_DAYS (400 days) relative to the claim are dropped.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date

from src.contradiction import parse_llm_json

logger = logging.getLogger(__name__)

# Severity levels
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_NONE = "none"

# Facts older than this many days before the claim date are considered stale.
STALE_DAYS = 400  # ~13 months — allows prior-year 10-K vs. current earnings call

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# ── Metric normalisation ───────────────────────────────────────────────────────

_METRIC_ALIASES: dict[str, str] = {
    "revenue":                 "revenue",
    "net revenue":             "revenue",
    "net sales":               "revenue",
    "sales":                   "revenue",
    "total revenue":           "revenue",
    "gross margin":            "gross_margin",
    "gross profit margin":     "gross_margin",
    "operating margin":        "operating_margin",
    "operating income margin": "operating_margin",
    "net income":              "net_income",
    "net profit":              "net_income",
    "operating income":        "operating_income",
    "operating profit":        "operating_income",
    "eps":                     "eps",
    "earnings per share":      "eps",
    "free cash flow":          "free_cash_flow",
    "fcf":                     "free_cash_flow",
    "customers":               "customers",
    "customer count":          "customers",
    "market share":            "market_share",
    "headcount":               "headcount",
    "employees":               "headcount",
    "data center":             "data_center_revenue",
    "data center revenue":     "data_center_revenue",
    "gaming":                  "gaming_revenue",
    "gaming revenue":          "gaming_revenue",
    "cloud":                   "cloud_revenue",
    "cloud revenue":           "cloud_revenue",
}

_INCREASE_WORDS = frozenset({
    "increase", "increased", "increases", "grew", "grow", "growth",
    "up", "higher", "strong", "stronger", "record", "expanded", "expand",
    "exceeded", "beat", "positive", "rise", "rose", "rising", "accelerated",
    "outperformed", "gain", "gained", "surge", "surged",
})

_DECREASE_WORDS = frozenset({
    "decrease", "decreased", "decreases", "decline", "declined", "declines",
    "fell", "fall", "down", "lower", "weak", "weaker", "miss", "missed",
    "below", "negative", "loss", "drop", "dropped", "reduced", "reduce",
    "shrink", "shrank", "contracted", "contraction", "deteriorated", "slowed",
})

_STOP_WORDS = frozenset({
    "that", "with", "from", "this", "they", "have", "been", "will",
    "were", "said", "also", "more", "than", "which", "their", "about",
    "into", "some", "over", "when", "than", "its", "our", "the", "and",
    "for", "are", "but", "not", "you", "all", "can", "had", "was",
    "one", "out", "use", "per", "may", "each", "both", "such",
})


# ── Date helpers ───────────────────────────────────────────────────────────────

def _parse_date(source: str) -> date | None:
    """Extract the first YYYY-MM-DD date from a source label string."""
    m = _DATE_RE.search(source or "")
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


def _is_valid_pair(claim: dict, fact: dict) -> bool:
    """Return True if the (claim, fact) pair is temporally valid for comparison.

    Rules:
      - Drop if claim_source == fact_source  (same document cannot contradict itself)
      - Drop if fact_date > claim_date       (later filing is a new development, not a contradiction)
      - Drop if fact is more than STALE_DAYS before claim date
      - Allow if neither date can be parsed  (fallback: let LLM decide)
    """
    claim_src = claim.get("source", "")
    fact_src = fact.get("source", "")

    if claim_src and fact_src and claim_src == fact_src:
        return False

    claim_date = _parse_date(claim_src)
    fact_date = _parse_date(fact_src)

    if claim_date and fact_date:
        if fact_date > claim_date:
            return False
        if (claim_date - fact_date).days > STALE_DAYS:
            return False

    return True


# ── Text normalisation ─────────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """Normalize free-form LLM text for exact-pair validation."""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


# ── Metric and direction helpers ───────────────────────────────────────────────

def _normalize_metric(m: str) -> str:
    """Map a metric string to its canonical name, or return lowercased input."""
    if not m:
        return ""
    return _METRIC_ALIASES.get(m.lower().strip(), m.lower().strip())


def _directions_conflict(d1: str, d2: str) -> bool:
    """Return True if d1 and d2 are semantically opposite directions."""
    if not d1 or not d2:
        return False
    d1_lower = d1.lower()
    d2_lower = d2.lower()
    d1_inc = d1_lower in _INCREASE_WORDS
    d1_dec = d1_lower in _DECREASE_WORDS
    d2_inc = d2_lower in _INCREASE_WORDS
    d2_dec = d2_lower in _DECREASE_WORDS
    return (d1_inc and d2_dec) or (d1_dec and d2_inc)


def _rule_based_check(claim: dict, fact: dict) -> str | None:
    """Fast-path quantitative contradiction detector.

    Fires when:
      - claim and fact reference the same normalised metric name
      - they report opposite directions of change (e.g. "grew" vs "declined")

    Returns severity string "high", or None if the rule does not fire.
    """
    c_metric = _normalize_metric(claim.get("metric", ""))
    f_metric = _normalize_metric(fact.get("metric", ""))

    if not c_metric or not f_metric or c_metric != f_metric:
        return None

    c_dir = claim.get("direction", "").lower()
    f_dir = fact.get("direction", "").lower()

    if _directions_conflict(c_dir, f_dir):
        return SEVERITY_HIGH

    return None


# ── Topic-based retrieval ──────────────────────────────────────────────────────

def _topic_keywords(obj: dict) -> set[str]:
    """Build a keyword set from topic, metric, and the first 120 chars of text."""
    words: set[str] = set()
    for field in ("topic", "metric"):
        val = obj.get(field, "")
        if val:
            words.update(re.findall(r"\b[a-z]{3,}\b", val.lower()))

    # Supplement with key words from the main text
    text = obj.get("claim", obj.get("fact", ""))[:120]
    words.update(
        w for w in re.findall(r"\b[a-z]{4,}\b", text.lower())
        if w not in _STOP_WORDS
    )
    return words


def _retrieve_relevant_facts(claim: dict, facts: list[dict], k: int = 5) -> list[dict]:
    """Return the top-k facts most relevant to the claim.

    Applies temporal pre-filtering first, then ranks surviving facts by keyword
    overlap between claim topic/metric/text and fact topic/section/text.
    """
    claim_keywords = _topic_keywords(claim)
    scored: list[tuple[int, dict]] = []

    for fact in facts:
        if not _is_valid_pair(claim, fact):
            continue
        fact_keywords = _topic_keywords(fact)
        score = len(claim_keywords & fact_keywords)
        scored.append((score, fact))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:k]]


# ── LLM result validation ──────────────────────────────────────────────────────

def _validate_result(
    item: dict,
    claim_fact_pairs: list[tuple[dict, list[dict]]],
) -> bool:
    """Return True if the LLM result maps back to a real (claim, fact) pair we sent."""
    c_text = _normalize_text(item.get("claim", ""))
    f_text = _normalize_text(item.get("fact", ""))

    for claim, facts in claim_fact_pairs:
        if _normalize_text(claim.get("claim", "")) == c_text:
            # For not_supported results, fact may be empty — that's valid
            if not f_text:
                return True
            for fact in facts:
                if _normalize_text(fact.get("fact", "")) == f_text:
                    return True
    return False


# ── LLM client ────────────────────────────────────────────────────────────────

def _build_llm_client():
    """Build an OpenAI-compatible LLM client from config.yaml."""
    from src.contradiction._llm import build_llm_client
    return build_llm_client()


# ── LLM batch ─────────────────────────────────────────────────────────────────

def _compare_batch(
    claim_fact_pairs: list[tuple[dict, list[dict]]],
    llm,
    model: str,
) -> tuple[list[dict], list[dict]]:
    """Send a batch of (claim, relevant_facts) pairs to the LLM for 3-way classification.

    Each claim is paired with only its own top-retrieved facts — the LLM never
    sees unrelated facts from other claims.

    Args:
        claim_fact_pairs: List of (claim_dict, [fact_dict, ...]) tuples.
        llm:   OpenAI-compatible client.
        model: Model name string.

    Returns:
        (contradictions, not_supported)

        contradictions — list of dicts with keys:
            claim, fact, verdict, severity, explanation, claim_source, fact_source
        not_supported — list of dicts with keys:
            claim, claim_source, explanation
    """
    # Build the structured prompt body — one section per claim
    sections: list[str] = []
    for i, (claim, facts) in enumerate(claim_fact_pairs):
        claim_line = (
            f"CLAIM {i + 1} [filed: {claim.get('source', 'unknown')}]:\n"
            f"\"{claim.get('claim', '')}\""
        )
        facts_lines = "\n".join(
            f"  FACT {i + 1}.{j + 1}"
            f" [{f.get('section', 'unknown')} | filed: {f.get('source', 'unknown')}]:"
            f" {f.get('fact', '')}"
            for j, f in enumerate(facts)
        )
        sections.append(f"{claim_line}\n\nRELEVANT FACTS:\n{facts_lines}")

    prompt_body = "\n\n---\n\n".join(sections)

    system_prompt = (
        "You are a financial due-diligence analyst performing a contradiction check.\n\n"
        "For each CLAIM below you are given RELEVANT FACTS extracted from the same company's "
        "10-K filings. Filing dates are shown — use them to judge contemporaneity.\n\n"
        "Classify each (CLAIM, FACT) pair as exactly one of:\n"
        "  \"contradicted\"  — management's claim directly conflicts with what the filing discloses "
        "(overstated performance, omitted a known material risk, or asserted the opposite of a disclosed fact)\n"
        "  \"not_supported\" — the 10-K provides no evidence to support the claim "
        "(no related disclosure exists, or the filing is silent on the topic)\n"
        "  \"verified\"      — the fact confirms or is consistent with the claim\n\n"
        "Severity (only for contradicted):\n"
        "  \"high\"   — claim directly contradicts a fact from the same or an earlier period\n"
        "  \"medium\" — claim omits or significantly downplays a material risk disclosed simultaneously\n"
        "  \"low\"    — claim is technically accurate but the filing adds important negative context\n\n"
        "Return ONLY a JSON array. Include contradicted AND not_supported pairs. Omit verified pairs.\n"
        "Each element must have:\n"
        "  \"claim\":        exact claim text (copy verbatim from the input)\n"
        "  \"fact\":         exact fact text (copy verbatim; use \"\" for not_supported)\n"
        "  \"verdict\":      \"contradicted\" | \"not_supported\"\n"
        "  \"severity\":     \"high\" | \"medium\" | \"low\" | \"\" (empty for not_supported)\n"
        "  \"explanation\":  one sentence explaining the conflict or gap\n"
        "  \"claim_source\": the claim source label\n"
        "  \"fact_source\":  the fact source label (use \"\" for not_supported)\n"
    )
    user_content = f"CLAIMS AND THEIR RELEVANT 10-K FACTS:\n\n{prompt_body}"

    try:
        response = llm.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content.strip()
        result = parse_llm_json(raw, "[comparator]")
        if not isinstance(result, list):
            return [], []

        contradictions: list[dict] = []
        not_supported: list[dict] = []

        for item in result:
            if not _validate_result(item, claim_fact_pairs):
                logger.info(
                    "[comparator] Dropped unverifiable LLM result: claim=%r",
                    item.get("claim", "")[:60],
                )
                continue

            verdict = item.get("verdict", "")
            if verdict == "contradicted":
                contradictions.append(item)
            elif verdict == "not_supported":
                not_supported.append({
                    "claim":        item.get("claim", ""),
                    "claim_source": item.get("claim_source", ""),
                    "explanation":  item.get("explanation", ""),
                })

        return contradictions, not_supported

    except Exception as exc:
        logger.warning("[comparator] LLM comparison failed: %s", exc)
        return [], []


# ── Main entry point ───────────────────────────────────────────────────────────

def compare(
    claims: list[dict],
    facts: list[dict],
    llm=None,
    model: str = "",
) -> tuple[list[dict], list[dict]]:
    """Compare claims against facts using the upgraded 4-step pipeline.

    Steps:
        3. Topic/metric retrieval  — per-claim top-5 relevant facts
                                     (temporal filter + keyword overlap scoring)
        4. Rule-based fast path    — metric + direction mismatch → HIGH instantly
        5. LLM 3-way classification — contradicted / not_supported / verified
        6. Post-processing          — dedup + sort

    Args:
        claims: Output of claim_extractor.extract_claims()
        facts:  Output of fact_extractor.extract_facts()
        llm:    Optional pre-built OpenAI client
        model:  LLM model name

    Returns:
        (contradictions, not_supported)

        contradictions: list[dict] with keys:
            claim, fact, severity, explanation, claim_source, fact_source
        not_supported: list[dict] with keys:
            claim, claim_source, explanation
    """
    if not claims:
        logger.info("[comparator] No claims to compare.")
        return [], []
    if not facts:
        logger.info("[comparator] No facts to compare against.")
        return [], []

    if llm is None:
        llm, model = _build_llm_client()

    # ── Step 3: Topic-based retrieval + temporal pre-filter ───────────────────
    # For each claim, retrieve its top-5 most topically-relevant facts.
    claim_fact_pairs: list[tuple[dict, list[dict]]] = []
    total_before = len(claims[:15]) * len(facts)

    for claim in claims[:15]:
        relevant = _retrieve_relevant_facts(claim, facts, k=5)
        if relevant:
            claim_fact_pairs.append((claim, relevant))

    if not claim_fact_pairs:
        logger.info("[comparator] No valid (claim, fact) pairs after topic retrieval.")
        return [], []

    total_after = sum(len(f) for _, f in claim_fact_pairs)
    logger.info(
        "[comparator] Topic retrieval: %d/%d pairs kept (%.0f%% reduction) — "
        "%d claims × avg %.1f facts each",
        total_after, total_before,
        100 * (1 - total_after / max(total_before, 1)),
        len(claim_fact_pairs),
        total_after / len(claim_fact_pairs),
    )

    all_contradictions: list[dict] = []
    all_not_supported: list[dict] = []
    fast_path_keys: set[tuple[str, str]] = set()

    # ── Step 4: Rule-based fast path (quantitative direction mismatches) ──────
    for claim, relevant_facts in claim_fact_pairs:
        for fact in relevant_facts:
            severity = _rule_based_check(claim, fact)
            if severity is None:
                continue

            entry: dict = {
                "claim":    claim.get("claim", ""),
                "fact":     fact.get("fact", ""),
                "severity": severity,
                "explanation": (
                    f"Rule-based detection: management claimed "
                    f"{claim.get('direction', 'positive')} "
                    f"'{claim.get('metric', claim.get('topic', 'metric'))}'"
                    f"{' (' + claim.get('value', '') + ')' if claim.get('value') else ''}"
                    f" while the 10-K discloses the opposite direction"
                    f"{' (' + fact.get('value', '') + ')' if fact.get('value') else ''}."
                ),
                "claim_source": claim.get("source", ""),
                "fact_source":  fact.get("source", ""),
            }
            key = (entry["claim"][:80], entry["fact"][:80])
            if key not in fast_path_keys:
                fast_path_keys.add(key)
                all_contradictions.append(entry)
                logger.info(
                    "[comparator] Fast-path HIGH: metric=%s | '%s'",
                    claim.get("metric", "?"),
                    entry["claim"][:60],
                )

    # ── Step 5: LLM 3-way classification ─────────────────────────────────────
    batch_size = 5
    total_batches = (len(claim_fact_pairs) + batch_size - 1) // batch_size

    for i in range(0, len(claim_fact_pairs), batch_size):
        batch = claim_fact_pairs[i : i + batch_size]
        contradictions, not_supported = _compare_batch(batch, llm, model)

        for c in contradictions:
            key = (c.get("claim", "")[:80], c.get("fact", "")[:80])
            if key not in fast_path_keys:   # skip if already caught by rule-based
                all_contradictions.append(c)

        all_not_supported.extend(not_supported)

        logger.info(
            "[comparator] Batch %d/%d → %d contradictions, %d not_supported",
            i // batch_size + 1, total_batches,
            len(contradictions), len(not_supported),
        )
        time.sleep(1.5)  # Groq token-per-minute throttle

    # ── Step 6: Deduplication and sorting ────────────────────────────────────
    seen_c: set[tuple[str, str]] = set()
    unique_contradictions: list[dict] = []
    for c in all_contradictions:
        key = (c.get("claim", "")[:80], c.get("fact", "")[:80])
        if key not in seen_c:
            seen_c.add(key)
            unique_contradictions.append(c)

    order = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}
    unique_contradictions.sort(key=lambda x: order.get(x.get("severity", "low"), 2))

    seen_ns: set[str] = set()
    unique_not_supported: list[dict] = []
    for ns in all_not_supported:
        key = ns.get("claim", "")[:80]
        if key not in seen_ns:
            seen_ns.add(key)
            unique_not_supported.append(ns)

    logger.info(
        "[comparator] Final: %d unique contradictions (%d from fast-path), %d not_supported",
        len(unique_contradictions), len(fast_path_keys), len(unique_not_supported),
    )
    return unique_contradictions, unique_not_supported

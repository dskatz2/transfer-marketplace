"""Normalizes employer names and fuzzy-matches disclosure-data employers to Seso
customer entities, so multi-entity enterprises (see active_customers_enterprises.csv)
are recognized as a single customer regardless of which legal entity filed."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

_SUFFIXES = re.compile(
    r"\b(llc|l\.l\.c|inc|incorporated|corp|corporation|co|company|ltd|l\.l\.p|llp|lp|"
    r"l\.p|gp|dba|partnership|farms?|farming|enterprises?|group)\b\.?",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^a-z0-9 ]")
_WS = re.compile(r"\s+")

# Auto-accept a disclosure employer as this customer without human review.
AUTO_MATCH_THRESHOLD = 92
# Below this, don't even bother surfacing it as a maybe-match.
REVIEW_MATCH_THRESHOLD = 78


def normalize_name(name: str) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    s = _PUNCT.sub(" ", s)
    s = _SUFFIXES.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def best_match(normalized_query: str, candidates: list[tuple[str, int]]) -> tuple[int, float] | None:
    """candidates: list of (normalized_name, enterprise_id). Returns (enterprise_id, score) or None."""
    if not normalized_query or not candidates:
        return None
    best_id = None
    best_score = 0.0
    for cand_name, enterprise_id in candidates:
        if not cand_name:
            continue
        score = fuzz.token_sort_ratio(normalized_query, cand_name)
        if score > best_score:
            best_score = score
            best_id = enterprise_id
    if best_id is None:
        return None
    return best_id, best_score


def classify(score: float) -> str:
    if score >= AUTO_MATCH_THRESHOLD:
        return "auto"
    if score >= REVIEW_MATCH_THRESHOLD:
        return "review"
    return "prospect"

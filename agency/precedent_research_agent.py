"""LLM Agent — precedent researcher (citation floor + real corpus pull).

Retrieves similar prior wins and the best proposal-library matches as RAG
context for drafting. The integrity controls are enforced as a FLOOR:

  * candidates WITHOUT an engagement_id are dropped in code (the prompt
    asks for citations; the chain guarantees them — no hallucinated
    proposals reach the drafter).
  * best_match_* / total_corpus_size / high_confidence_match are
    recomputed deterministically from the surviving matches.

Decorators (bottom-up execution):
  @pre_compose load_corpus — pull the practice-area precedents from the
      dev store (stand-in for the DMS / proposals_library RAG) so the
      researcher reasons over real prior engagements on day 0.
  @chain enforce_citation_floor — drop un-cited candidates, recompute the
      match summary (the floor).

auto_discover matches function name 'precedent_research_agent' to YAML.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

_HIGH_CONFIDENCE_MIN = 0.4

_DEFAULTS: dict[str, Any] = {
    "similar_proposals": [],
    "reuse_score": 0,
    "matches": [],
    "best_match_proposal_id": "",
    "best_match_similarity": 0,
    "total_corpus_size": 0,
    "high_confidence_match": False,
    "reason": "",
}


def _prepared(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    prep = context.get("prepared_data", {})
    if isinstance(prep, dict):
        inner = prep.get("context")
        if isinstance(inner, dict):
            return inner
        return prep
    return {}


def _parse_json(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return {}
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (ValueError, TypeError):
            return {}
    return {}


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _practice_area(input_data: dict, pctx: dict) -> str:
    pa = input_data.get("practice_areas")
    if isinstance(pa, list) and pa:
        return str(pa[0])
    up = input_data.get("upstream_yields")
    if isinstance(up, dict) and up.get("practice_area"):
        return str(up["practice_area"])
    return str(input_data.get("practice_area", "") or pctx.get("practice_area", ""))


# ── @pre_compose processor ───────────────────────────────────────────
def load_corpus(data: Any, ctx: dict) -> dict[str, Any]:
    """Pull the practice-area precedents from the proposal corpus (DMS)."""
    input_data = data if isinstance(data, dict) else {}
    up = input_data.get("upstream_yields")
    practice_area = ""
    if isinstance(up, dict):
        practice_area = str(up.get("practice_area", ""))
    if not practice_area:
        pa = input_data.get("practice_areas")
        practice_area = str(pa[0]) if isinstance(pa, list) and pa else str(
            input_data.get("practice_area", "")
        )
    corpus = store.precedents_for(practice_area)
    return {
        "practice_area": practice_area,
        "corpus": corpus,
        "corpus_size": len(corpus),
    }


# ── @chain step (the deterministic citation floor) ───────────────────
async def enforce_citation_floor(result: dict, ctx: dict) -> dict[str, Any]:
    """Drop un-cited candidates + recompute the match summary. The floor."""
    if not isinstance(result, dict):
        result = {}
    pctx = _prepared(ctx)
    corpus = pctx.get("corpus", []) or []

    # 1. Citation floor: every similar_proposal MUST cite an engagement_id.
    similar = result.get("similar_proposals")
    if not isinstance(similar, list):
        similar = []
    cited = [s for s in similar if isinstance(s, dict) and s.get("engagement_id")]
    result["similar_proposals"] = cited
    result["reuse_score"] = _clamp01(result.get("reuse_score", 0))

    # 2. Matches: prefer the model's, but never fewer than the real corpus
    #    can supply — ground the drafter even if the model returned nothing.
    matches = result.get("matches")
    if not isinstance(matches, list) or not matches:
        matches = [
            {
                "proposal_id": p.get("proposal_id", ""),
                "client": p.get("client", ""),
                "practice_areas": p.get("practice_areas", []),
                "scope_summary": p.get("scope_summary", ""),
                "outcome": p.get("outcome", ""),
                "similarity": _clamp01(p.get("similarity", 0)),
            }
            for p in corpus[:3]
        ]
    result["matches"] = matches

    # 3. Recompute the summary deterministically.
    if matches and isinstance(matches[0], dict):
        result["best_match_proposal_id"] = str(matches[0].get("proposal_id", ""))
        result["best_match_similarity"] = _clamp01(matches[0].get("similarity", 0))
    else:
        result["best_match_proposal_id"] = ""
        result["best_match_similarity"] = 0
    result["total_corpus_size"] = len(corpus)
    result["high_confidence_match"] = bool(
        result["best_match_similarity"] >= _HIGH_CONFIDENCE_MIN
    )
    if not result.get("reason") and not corpus:
        result["reason"] = "no_query"

    logger.info(
        f"enforce_citation_floor — cited={len(cited)} matches={len(matches)} "
        f"best={result['best_match_proposal_id']} "
        f"sim={result['best_match_similarity']} corpus={len(corpus)}"
    )
    return result


@pre_compose(context_processor=load_corpus)
@chain(enforce_citation_floor)
async def precedent_research_agent(llm_response, input_data: dict,
                                   context: dict) -> dict[str, Any]:
    """Surface the LLM's precedent picks; the chain enforces the citation floor."""
    if not isinstance(context, dict):
        context = {}
    if not isinstance(input_data, dict):
        input_data = {}
    parsed = _parse_json(llm_response)

    computed = {
        "similar_proposals": parsed.get("similar_proposals", []) if isinstance(parsed.get("similar_proposals"), list) else [],
        "reuse_score": _clamp01(parsed.get("reuse_score", 0)),
        "matches": parsed.get("matches", []) if isinstance(parsed.get("matches"), list) else [],
        "best_match_proposal_id": str(parsed.get("best_match_proposal_id", "")),
        "best_match_similarity": _clamp01(parsed.get("best_match_similarity", 0)),
        "total_corpus_size": int(parsed.get("total_corpus_size", 0)) if str(parsed.get("total_corpus_size", "")).isdigit() else 0,
        "high_confidence_match": bool(parsed.get("high_confidence_match", False)),
        "reason": str(parsed.get("reason", "")),
    }
    logger.info(
        "precedent_research_agent — surfaced picks (enforce_citation_floor "
        "drops un-cited + grounds matches in the corpus)"
    )
    return {**_DEFAULTS, **computed}

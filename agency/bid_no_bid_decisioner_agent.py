"""LLM Agent — bid/no-bid strategist (deterministic decision floor).

Scores RFP fit on five axes, then enforces the firm's go/no-go criteria
as a FLOOR the LLM cannot waive:

  * overall_score is RECOMPUTED from the five axes with the exact weights
    (the model cannot fudge the weighted score to flip a recommendation).
  * recommendation is RECOMPUTED from overall_score + confidence per the
    firm thresholds.
  * requires_partner_review is FORCED true on a no_bid / low confidence /
    weak score — we never silently no-bid an opportunity.

Decorators (bottom-up execution):
  @pre_compose load_win_loss_history — pull the practice-area win/loss
      history + the captured RFP from the dev store so the model scores
      against the firm's real track record, not vibes.
  @chain enforce_decision_floor — recompute score / recommendation /
      partner-review deterministically (the floor).

auto_discover matches function name 'bid_no_bid_decisioner_agent' to YAML.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

# Firm go/no-go criteria — applied in code, not left to the prompt.
_WEIGHTS = {
    "fit_strategic": 0.25,
    "fit_capability": 0.25,
    "fit_economics": 0.20,
    "fit_relationship": 0.20,
    "fit_competitive": 0.10,
}
_BID_SCORE_MIN = 0.65
_BID_CONFIDENCE_MIN = 0.6
_QUALIFY_SCORE_MIN = 0.40

_DEFAULTS: dict[str, Any] = {
    "rfp_id": "",
    "fit_strategic": 0,
    "fit_capability": 0,
    "fit_economics": 0,
    "fit_relationship": 0,
    "fit_competitive": 0,
    "overall_score": 0,
    "confidence": 0,
    "recommendation": "",
    "risk_flags": [],
    "win_themes": [],
    "requires_partner_review": False,
    "decision_briefing": "",
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


# ── @pre_compose processor ───────────────────────────────────────────
def load_win_loss_history(data: Any, ctx: dict) -> dict[str, Any]:
    """Pull the practice-area win/loss track record + the captured RFP."""
    input_data = data if isinstance(data, dict) else {}
    rfp_id = str(input_data.get("rfp_id", ""))
    upstream = input_data.get("upstream_yields")
    if isinstance(upstream, dict) and not rfp_id:
        rfp_id = str(upstream.get("rfp_id", ""))
    opp = store.get_opportunity(rfp_id) if rfp_id else {}
    practice_area = str(input_data.get("practice_area", "")) or str(
        opp.get("practice_area", "")
    )
    history = store.win_loss_for(practice_area)
    return {
        "rfp_id": rfp_id,
        "practice_area": practice_area,
        "opportunity": opp,
        "win_loss_history": history,
        "practice_area_win_rate": store.win_rate(practice_area),
    }


# ── @chain step (the deterministic decision floor) ───────────────────
async def enforce_decision_floor(result: dict, ctx: dict) -> dict[str, Any]:
    """Recompute score / recommendation / partner-review in code. The floor."""
    if not isinstance(result, dict):
        result = {}
    pctx = _prepared(ctx)

    axes = {k: _clamp01(result.get(k, 0)) for k in _WEIGHTS}
    for k, v in axes.items():
        result[k] = v
    overall = round(sum(axes[k] * w for k, w in _WEIGHTS.items()), 2)
    result["overall_score"] = overall
    confidence = _clamp01(result.get("confidence", 0))
    result["confidence"] = confidence

    if overall >= _BID_SCORE_MIN and confidence >= _BID_CONFIDENCE_MIN:
        rec = "bid"
    elif overall >= _QUALIFY_SCORE_MIN:
        rec = "qualify_further"
    else:
        rec = "no_bid"
    result["recommendation"] = rec

    # Never silently no-bid: weak signal / low confidence / no-bid → partner.
    result["requires_partner_review"] = bool(
        rec == "no_bid" or confidence < 0.5 or overall < _QUALIFY_SCORE_MIN
    )

    if not result.get("rfp_id"):
        result["rfp_id"] = pctx.get("rfp_id", "")
    if not result.get("decision_briefing"):
        result["decision_briefing"] = (
            f"Recommendation {rec} at overall {overall} (confidence {confidence}); "
            f"practice-area win rate {pctx.get('practice_area_win_rate', 0)}."
        )

    logger.info(
        f"enforce_decision_floor — rfp_id={result.get('rfp_id','')} "
        f"overall={overall} confidence={confidence} rec={rec} "
        f"partner_review={result['requires_partner_review']}"
    )
    return result


@pre_compose(context_processor=load_win_loss_history)
@chain(enforce_decision_floor)
async def bid_no_bid_decisioner_agent(llm_response, input_data: dict,
                                      context: dict) -> dict[str, Any]:
    """Surface the LLM's fit scores; the chain enforces the decision floor."""
    if not isinstance(context, dict):
        context = {}
    if not isinstance(input_data, dict):
        input_data = {}
    pctx = _prepared(context)
    parsed = _parse_json(llm_response)

    computed = {
        "rfp_id": str(parsed.get("rfp_id", "")) or pctx.get("rfp_id", ""),
        "fit_strategic": _clamp01(parsed.get("fit_strategic", 0)),
        "fit_capability": _clamp01(parsed.get("fit_capability", 0)),
        "fit_economics": _clamp01(parsed.get("fit_economics", 0)),
        "fit_relationship": _clamp01(parsed.get("fit_relationship", 0)),
        "fit_competitive": _clamp01(parsed.get("fit_competitive", 0)),
        "confidence": _clamp01(parsed.get("confidence", 0)),
        "risk_flags": parsed.get("risk_flags", []) if isinstance(parsed.get("risk_flags"), list) else [],
        "win_themes": parsed.get("win_themes", []) if isinstance(parsed.get("win_themes"), list) else [],
        "decision_briefing": str(parsed.get("decision_briefing", "")),
    }
    logger.info(
        f"bid_no_bid_decisioner_agent — rfp_id={computed['rfp_id']} "
        f"(enforce_decision_floor recomputes score/recommendation)"
    )
    return {**_DEFAULTS, **computed}

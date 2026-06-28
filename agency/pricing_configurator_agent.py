"""LLM Agent — pricing configurator (deterministic approval floor).

Builds line-item pricing for a drafted proposal, then enforces the
firm's pricing controls as a FLOOR the LLM cannot waive:

  * total_cents is RECOMPUTED from the line items (sum of subtotals) —
    the model cannot under-report a total to dodge a sign-off tier.
  * within_band is RECOMPUTED from the RFP's budget bounds.
  * the approval tiers are computed deterministically:
        total > $1,000,000           → requires_partner_signoff
        discount > 20%               → requires_practice_lead_signoff
    These flags drive the can_call edges, so the partner / practice-lead
    gates fire on the COMPUTED numbers, not on whatever the LLM claimed.

Decorators (bottom-up execution):
  @pre_compose load_rate_card — pull the practice-area rate card + the
      captured RFP's budget bounds from the dev store so the model prices
      against real day-rates (not invented ones) and the band check has
      real bounds.
  @compose per-peer payloads — the partner / practice-lead approvers get
      a focused approval brief; contracts_review gets the full priced
      package.
  @chain enforce_pricing_floor — recompute total / band / approval tiers
      deterministically (the floor).

auto_discover matches function name 'pricing_configurator_agent' to YAML.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain, compose, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

# Approval thresholds — the firm's pricing controls. The LLM may not
# waive these; they are applied in code.
_PARTNER_SIGNOFF_TOTAL_CENTS = 100_000_000   # > $1,000,000 → partner
_PRACTICE_LEAD_DISCOUNT_PCT = 20             # > 20% discount → practice lead

_DEFAULTS: dict[str, Any] = {
    "rfp_id": "",
    "pricing_breakdown": [],
    "total_cents": 0,
    "within_band": True,
    "discount_pct": 0,
    "requires_partner_signoff": False,
    "requires_practice_lead_signoff": False,
    "pricing_floor_applied": False,
}


def _prepared(context: Any) -> dict[str, Any]:
    """Read the @pre_compose output, tolerant of SDK wrapping depth."""
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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


# ── @pre_compose processor ───────────────────────────────────────────
def load_rate_card(data: Any, ctx: dict) -> dict[str, Any]:
    """Pull the practice-area rate card + the RFP's budget bounds."""
    input_data = data if isinstance(data, dict) else {}
    practice_area = str(input_data.get("practice_area", ""))
    rfp_id = str(input_data.get("rfp_id", ""))
    opp = store.get_opportunity(rfp_id) if rfp_id else {}
    if not practice_area:
        practice_area = str(opp.get("practice_area", ""))
    budget = input_data.get("budget_range_cents")
    if not isinstance(budget, dict) or not budget:
        budget = opp.get("budget_range_cents", {}) or {}
    return {
        "rfp_id": rfp_id,
        "practice_area": practice_area,
        "rate_card": store.rate_card(practice_area),
        "budget_range_cents": budget,
    }


# ── @chain step (the deterministic pricing floor) ────────────────────
async def enforce_pricing_floor(result: dict, ctx: dict) -> dict[str, Any]:
    """Recompute total / band / approval tiers in code. The floor."""
    if not isinstance(result, dict):
        result = {}
    pctx = _prepared(ctx)

    # 1. total_cents = EXACT sum of line-item subtotals (never trust the
    #    LLM's arithmetic on a number that gates a human sign-off).
    breakdown = result.get("pricing_breakdown")
    if not isinstance(breakdown, list):
        breakdown = []
    computed_total = 0
    for line in breakdown:
        if isinstance(line, dict):
            sub = line.get("subtotal_cents")
            if sub is None:
                sub = _as_int(line.get("unit_cents", 0)) * _as_int(line.get("quantity", 0))
            computed_total += _as_int(sub)
    if breakdown:
        result["total_cents"] = computed_total
    else:
        result["total_cents"] = _as_int(result.get("total_cents", 0))
    total = result["total_cents"]

    # 2. within_band from the RFP's real budget bounds.
    budget = pctx.get("budget_range_cents", {}) or {}
    low = _as_int(budget.get("low", 0))
    high = _as_int(budget.get("high", 0))
    if high > 0:
        result["within_band"] = bool(low <= total <= high)
    else:
        result["within_band"] = True

    # 3. discount clamp + approval tiers (the controls the LLM can't waive).
    discount = result.get("discount_pct", 0)
    try:
        discount = max(0.0, min(100.0, float(discount)))
    except (TypeError, ValueError):
        discount = 0.0
    result["discount_pct"] = discount

    result["requires_partner_signoff"] = bool(total > _PARTNER_SIGNOFF_TOTAL_CENTS)
    result["requires_practice_lead_signoff"] = bool(
        discount > _PRACTICE_LEAD_DISCOUNT_PCT
        and total <= _PARTNER_SIGNOFF_TOTAL_CENTS
    )
    result["pricing_floor_applied"] = True
    if not result.get("rfp_id"):
        result["rfp_id"] = pctx.get("rfp_id", "")

    logger.info(
        f"enforce_pricing_floor — rfp_id={result.get('rfp_id','')} "
        f"total_cents={total} within_band={result['within_band']} "
        f"discount={discount} partner={result['requires_partner_signoff']} "
        f"practice_lead={result['requires_practice_lead_signoff']}"
    )
    return result


# ── @compose per-peer payloads ───────────────────────────────────────
def _to_approver(result: dict, ctx: dict) -> dict[str, Any]:
    """Focused approval brief for the partner / practice-lead human gate."""
    return {
        "rfp_id": result.get("rfp_id", ""),
        "total_cents": result.get("total_cents", 0),
        "discount_pct": result.get("discount_pct", 0),
        "within_band": result.get("within_band", True),
    }


def _to_contracts(result: dict, ctx: dict) -> dict[str, Any]:
    """Full priced package for contracts review."""
    return {
        "rfp_id": result.get("rfp_id", ""),
        "pricing_breakdown": result.get("pricing_breakdown", []),
        "total_cents": result.get("total_cents", 0),
        "discount_pct": result.get("discount_pct", 0),
        "within_band": result.get("within_band", True),
    }


@pre_compose(context_processor=load_rate_card)
@compose(
    partner_human=_to_approver,
    practice_lead_human=_to_approver,
    contracts_review_agent=_to_contracts,
)
@chain(enforce_pricing_floor)
async def pricing_configurator_agent(llm_response, input_data: dict,
                                     context: dict) -> dict[str, Any]:
    """Surface the LLM's pricing; the chain enforces the deterministic floor."""
    if not isinstance(context, dict):
        context = {}
    if not isinstance(input_data, dict):
        input_data = {}
    pctx = _prepared(context)
    parsed = _parse_json(llm_response)

    breakdown = parsed.get("pricing_breakdown", [])
    if not isinstance(breakdown, list):
        breakdown = []

    computed = {
        "rfp_id": str(parsed.get("rfp_id", "")) or pctx.get("rfp_id", ""),
        "pricing_breakdown": breakdown,
        "total_cents": _as_int(parsed.get("total_cents", 0)),
        "within_band": bool(parsed.get("within_band", True)),
        "discount_pct": parsed.get("discount_pct", 0),
    }
    logger.info(
        f"pricing_configurator_agent — rfp_id={computed['rfp_id']} "
        f"lines={len(breakdown)} (enforce_pricing_floor recomputes total/tiers)"
    )
    return {**_DEFAULTS, **computed}

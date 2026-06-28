"""LLM Agent — contracts reviewer (unacceptable-clause floor + context pull).

One legal-adjacent role, mode-dispatched (regulatory / playbook). The LLM
extracts the clauses and proposes a stance; the integrity controls are
enforced as a FLOOR the LLM cannot waive:

  * an UNACCEPTABLE clause (uncapped liability, net-90 payment, client
    owns pre-existing IP, immediate termination, …) FORCES
    requires_legal_review and a "blocked" clearance — the model cannot
    wave a banned clause through to the audit sink.
  * the severity counts / per-severity clause lists / risk_score are
    RECOMPUTED from the review entries (the model cannot under-report).
  * a captured compliance MUST-HAVE that the contract does not address is
    a blocking concern → legal review (a compliance obligation is never
    silently dropped).

Decorators (bottom-up execution):
  @pre_compose load_contract_context — pull the draft contract + clauses
      and the captured RFP's compliance must-haves from the dev store
      (stand-in for the contract-management system + capture tool) so the
      reviewer works the REAL clauses + obligations on day 0.
  @chain enforce_unacceptable_clause_floor — recompute severity, force
      legal review on any unacceptable clause / unmet must-have (the floor).

auto_discover matches function name 'contracts_review_agent' to YAML.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

_SEVERITIES = ("acceptable", "negotiable", "unacceptable", "unmapped")

_DEFAULTS: dict[str, Any] = {
    "mode": "",
    "rfp_id": "",
    "clearance": "",
    "reasons": [],
    "requires_legal_review": False,
    "partner_briefing": "",
    "clauses_reviewed": 0,
    "review": [],
    "severity_counts": {},
    "unacceptable_clauses": [],
    "negotiable_clauses": [],
    "unmapped_clauses": [],
    "counter_proposals": [],
    "risk_score": 0,
    "requires_deal_desk_review": False,
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


def _rfp_id(input_data: dict, pctx: dict) -> str:
    rid = str(input_data.get("rfp_id", "") or "")
    if rid:
        return rid
    up = input_data.get("upstream_yields")
    if isinstance(up, dict) and up.get("rfp_id"):
        return str(up["rfp_id"])
    return str(pctx.get("rfp_id", "") or "")


# ── @pre_compose processor ───────────────────────────────────────────
def load_contract_context(data: Any, ctx: dict) -> dict[str, Any]:
    """Pull the draft contract + clauses and the captured compliance
    must-haves from the dev store (CLM + capture tool stand-ins)."""
    input_data = data if isinstance(data, dict) else {}
    up = input_data.get("upstream_yields")
    rfp_id = str(input_data.get("rfp_id", "") or "")
    if not rfp_id and isinstance(up, dict):
        rfp_id = str(up.get("rfp_id", "") or "")
    contract = store.contract_for(rfp_id)
    return {
        "rfp_id": rfp_id,
        "contract": contract,
        "contract_clauses": contract.get("clauses", []),
        "compliance_must_haves": store.compliance_must_haves(rfp_id),
    }


# ── @chain step (the unacceptable-clause floor) ──────────────────────
async def enforce_unacceptable_clause_floor(result: dict, ctx: dict) -> dict[str, Any]:
    """Recompute severity from the review entries and FORCE legal review on
    any unacceptable clause OR an unmet compliance must-have. The floor."""
    if not isinstance(result, dict):
        result = {}
    pctx = _prepared(ctx)

    # 1. Recompute the per-severity buckets from the review entries — the
    #    model's own counts are not trusted.
    review = result.get("review")
    if not isinstance(review, list):
        review = []
    buckets: dict[str, list[str]] = {s: [] for s in _SEVERITIES}
    for entry in review:
        if not isinstance(entry, dict):
            continue
        sev = str(entry.get("severity", "")).lower()
        ctype = str(entry.get("clause_type", ""))
        if sev in buckets and ctype:
            buckets[sev].append(ctype)
    result["review"] = review
    result["clauses_reviewed"] = len(review)
    result["unacceptable_clauses"] = buckets["unacceptable"]
    result["negotiable_clauses"] = buckets["negotiable"]
    result["unmapped_clauses"] = buckets["unmapped"]
    result["severity_counts"] = {s: len(buckets[s]) for s in _SEVERITIES}
    result["risk_score"] = round(
        min(
            1.0,
            0.4 * len(buckets["unacceptable"])
            + 0.15 * len(buckets["negotiable"])
            + 0.05 * len(buckets["unmapped"]),
        ),
        2,
    )

    # 2. Compliance must-haves the contract does not address are blocking.
    must_haves = pctx.get("compliance_must_haves") or []
    addressed = " ".join(
        str(e.get("clause_type", "")) + " " + str(e.get("clause_text", ""))
        for e in review if isinstance(e, dict)
    ).lower()
    unmet = [m for m in must_haves if str(m).lower() not in addressed]

    # 3. THE FLOOR — any unacceptable clause OR an unmet must-have forces
    #    legal review + a blocked clearance. The LLM cannot wave it through.
    has_unacceptable = bool(buckets["unacceptable"])
    requires_legal = bool(result.get("requires_legal_review")) or has_unacceptable or bool(unmet)
    result["requires_legal_review"] = requires_legal

    # Deal-desk review: 2+ negotiable OR 3+ unmapped clauses.
    result["requires_deal_desk_review"] = bool(
        len(buckets["negotiable"]) >= 2 or len(buckets["unmapped"]) >= 3
    )

    # Clearance mirrors the gates.
    if requires_legal:
        result["clearance"] = "blocked"
    elif result["requires_deal_desk_review"] or str(result.get("clearance", "")).lower() == "needs_review":
        result["clearance"] = "needs_review"
    else:
        result["clearance"] = result.get("clearance") or "ok"

    # Surface the unmet must-haves in reasons so the human sees WHY.
    reasons = result.get("reasons")
    if not isinstance(reasons, list):
        reasons = []
    for m in unmet:
        msg = f"compliance must-have not addressed: {m}"
        if msg not in reasons:
            reasons.append(msg)
    result["reasons"] = reasons

    if not result.get("rfp_id"):
        result["rfp_id"] = pctx.get("rfp_id", "")

    logger.warning(
        f"enforce_unacceptable_clause_floor — rfp_id={result.get('rfp_id','')} "
        f"unacceptable={len(buckets['unacceptable'])} unmet_must_haves={len(unmet)} "
        f"legal_review={requires_legal} clearance={result['clearance']} "
        f"risk={result['risk_score']}"
    )
    return result


@pre_compose(context_processor=load_contract_context)
@chain(enforce_unacceptable_clause_floor)
async def contracts_review_agent(llm_response, input_data: dict,
                                 context: dict) -> dict[str, Any]:
    """Surface the LLM's clause review; the chain enforces the
    unacceptable-clause floor + the compliance must-have check."""
    if not isinstance(context, dict):
        context = {}
    if not isinstance(input_data, dict):
        input_data = {}
    pctx = _prepared(context)
    parsed = _parse_json(llm_response)

    result = dict(_DEFAULTS)
    for k in result:
        if k in parsed:
            result[k] = parsed[k]
    result["mode"] = str(parsed.get("mode", "")) or "regulatory"
    result["rfp_id"] = str(parsed.get("rfp_id", "")) or _rfp_id(input_data, pctx)
    logger.info(
        f"contracts_review_agent — mode={result['mode']} rfp_id={result['rfp_id']} "
        f"(enforce_unacceptable_clause_floor recomputes severity + forces legal review)"
    )
    return result

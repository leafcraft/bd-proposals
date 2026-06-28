"""LLM Agent — opportunity-intake specialist (completeness + compliance floor).

Normalises an inbound RFP and extracts structured requirements, then
enforces the firm's intake controls as a FLOOR the LLM cannot waive:

  * completeness_score is RECOMPUTED in code from the extracted fields
    (exact rubric) and extraction_complete is derived from it (or vacuous
    when the RFP arrived with no documents) — the model cannot mark a
    thin extraction "complete" to skip the partner review.
  * compliance must-haves the captured opportunity declares (e.g. FedRAMP,
    NDA) are MERGED into compliance_required even if the model missed
    them in the body — a compliance obligation is never silently dropped.

Decorators (bottom-up execution):
  @pre_compose load_opportunity — pull the captured opportunity record
      (its declared compliance must-haves + budget) from the dev store /
      capture tool so intake reconciles against what we already know.
  @chain enforce_intake_floor — recompute completeness, merge compliance
      must-haves (the floor).

auto_discover matches function name 'rfp_intake_agent' to YAML.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

# Exact completeness rubric — applied in code so the verdict is auditable.
_RUBRIC = [
    ("requirements", 0.20),
    ("deliverables", 0.20),
    ("evaluation_criteria", 0.20),
    ("pricing_constraints", 0.20),
    ("key_dates", 0.10),
    ("compliance_frameworks", 0.10),
]
_COMPLETE_MIN = 0.6

_DEFAULTS: dict[str, Any] = {
    "rfp_id": "",
    "client_org": "",
    "practice_area": "",
    "due_date": "",
    "budget_range_cents": {},
    "compliance_required": [],
    "deal_breakers": [],
    "document_count": 0,
    "requirements": [],
    "requirements_must_count": 0,
    "requirements_should_count": 0,
    "compliance_frameworks": [],
    "deliverables": [],
    "evaluation_criteria": {},
    "pricing_constraints": {},
    "key_dates": {},
    "completeness_score": 0,
    "extraction_complete": False,
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


def _nonempty(value: Any) -> bool:
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return value is not None


# ── @pre_compose processor ───────────────────────────────────────────
def load_opportunity(data: Any, ctx: dict) -> dict[str, Any]:
    """Pull the captured opportunity record (compliance must-haves + budget)."""
    input_data = data if isinstance(data, dict) else {}
    payload = input_data.get("payload")
    payload = payload if isinstance(payload, dict) else input_data
    rfp_id = str(payload.get("rfp_id", "") or input_data.get("rfp_id", ""))
    opp = store.get_opportunity(rfp_id) if rfp_id else {}
    return {
        "rfp_id": rfp_id,
        "opportunity": opp,
        "captured_compliance": opp.get("compliance_required", []) or [],
        "captured_budget": opp.get("budget_range_cents", {}) or {},
        "captured_practice_area": opp.get("practice_area", ""),
    }


# ── @chain step (the deterministic completeness + compliance floor) ──
async def enforce_intake_floor(result: dict, ctx: dict) -> dict[str, Any]:
    """Recompute completeness + merge compliance must-haves. The floor."""
    if not isinstance(result, dict):
        result = {}
    pctx = _prepared(ctx)

    # rfp_id: keep the model's, else the captured one, else mint one.
    if not result.get("rfp_id"):
        result["rfp_id"] = pctx.get("rfp_id", "") or f"rfp-{uuid.uuid4().hex[:10]}"

    # 1. Completeness rubric — recomputed in code (exact, auditable).
    score = round(sum(w for field, w in _RUBRIC if _nonempty(result.get(field))), 2)
    result["completeness_score"] = score
    doc_count = result.get("document_count", 0)
    try:
        doc_count = int(doc_count)
    except (TypeError, ValueError):
        doc_count = 0
    result["document_count"] = doc_count
    # Vacuously complete when no documents arrived (body-only RFP flows on).
    result["extraction_complete"] = bool(score >= _COMPLETE_MIN or doc_count == 0)

    # 2. Compliance must-haves: union the model's findings with what the
    #    captured opportunity already declares — never silently drop one.
    declared = result.get("compliance_required")
    declared = declared if isinstance(declared, list) else []
    captured = pctx.get("captured_compliance", []) or []
    merged = sorted({str(c) for c in (declared + list(captured)) if c})
    result["compliance_required"] = merged

    # Backfill identity/budget from the captured record when the body omitted it.
    if not result.get("budget_range_cents"):
        result["budget_range_cents"] = pctx.get("captured_budget", {}) or {}
    if not result.get("practice_area"):
        result["practice_area"] = pctx.get("captured_practice_area", "") or ""

    logger.info(
        f"enforce_intake_floor — rfp_id={result['rfp_id']} score={score} "
        f"complete={result['extraction_complete']} "
        f"compliance={merged} docs={doc_count}"
    )
    return result


@pre_compose(context_processor=load_opportunity)
@chain(enforce_intake_floor)
async def rfp_intake_agent(llm_response, input_data: dict,
                           context: dict) -> dict[str, Any]:
    """Surface the LLM's extraction; the chain enforces the intake floor."""
    if not isinstance(context, dict):
        context = {}
    if not isinstance(input_data, dict):
        input_data = {}
    parsed = _parse_json(llm_response)
    # Pass the parsed extraction through; the chain owns the floors.
    return {**_DEFAULTS, **{k: parsed[k] for k in _DEFAULTS if k in parsed}}

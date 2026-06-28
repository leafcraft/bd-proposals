"""LLM Agent — competitive-intelligence analyst (real-data context pull).

Win/loss post-mortems, competitor takeaways, quarterly reviews. The
judgement (what we did well/poorly, learnings, next action) is the LLM's;
this module makes the analyst SELF-RELIANT — it pulls the firm's real
competitor signals + win/loss track record from the store so it reasons
over actual moves, not invented ones.

Decorators:
  @pre_compose load_competitive_context — pull the practice-area
      competitor signals (CRM / intel-store stand-in), the win/loss
      history and the practice-area win rate so the post-mortem is
      grounded in the firm's real record on day 0.

No @chain floor: this role produces analysis, not a control/actuator —
the surfaced competitor_intelligence is forwarded to the CRM ledger by a
deterministic can_call edge in the config (not by this module). Adding a
@chain here would be decorator theater.

auto_discover matches function name 'competitive_intel_agent' to YAML.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "decision": "",
    "executive_summary": "",
    "what_we_did_well": [],
    "what_we_did_poorly": [],
    "competitor_intelligence": [],
    "learnings_for_library": [],
    "next_action_for_relationship": "",
    "confidence": 0,
}


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


def _practice_area(event: dict) -> str:
    for key in ("practice_area", "practiceArea"):
        if event.get(key):
            return str(event[key])
    return ""


# ── @pre_compose processor ───────────────────────────────────────────
def load_competitive_context(data: Any, ctx: dict) -> dict[str, Any]:
    """Pull the firm's real competitor signals + win/loss track record so
    the analyst reasons over actual data. PROD: CRM / intel-store query."""
    input_data = data if isinstance(data, dict) else {}
    event = input_data.get("decision_event")
    event = event if isinstance(event, dict) else {}
    practice_area = _practice_area(event) or _practice_area(input_data)
    competitor = str(event.get("competitor", "") or input_data.get("competitor", ""))
    return {
        "practice_area": practice_area,
        "competitor": competitor,
        "competitor_signals": store.competitor_signals(practice_area, competitor),
        "top_competitors": store.top_competitors(practice_area),
        "win_loss_history": store.win_loss_for(practice_area),
        "practice_area_win_rate": store.win_rate(practice_area),
    }


@pre_compose(context_processor=load_competitive_context)
async def competitive_intel_agent(llm_response, input_data: dict,
                                  context: dict) -> dict[str, Any]:
    """Surface the LLM's post-mortem; the @pre_compose pull grounds it in
    the firm's real competitor signals + win/loss record."""
    if not isinstance(input_data, dict):
        input_data = {}
    parsed = _parse_json(llm_response)

    result = dict(_DEFAULTS)
    for k in result:
        if k in parsed:
            result[k] = parsed[k]
    result["confidence"] = _clamp01(parsed.get("confidence", 0))
    if str(result.get("decision", "")).lower() not in (
        "won", "lost", "no_decision", "withdrawn"
    ):
        result["decision"] = "no_decision"
    for list_key in ("what_we_did_well", "what_we_did_poorly",
                     "competitor_intelligence", "learnings_for_library"):
        if not isinstance(result.get(list_key), list):
            result[list_key] = []
    logger.info(
        f"competitive_intel_agent — decision={result['decision']} "
        f"(load_competitive_context grounded the analysis in real signals)"
    )
    return result

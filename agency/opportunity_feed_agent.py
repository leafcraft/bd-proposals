"""Programmatic Agent — opportunity feed (the fan-out sweep).

The firm's capture-tool scout. On a scheduled sweep (or a manual trigger), it
pulls the NEW, pre-deduplicated notices from the capture tool (GovWin / SAM.gov /
FedConnect saved searches) and routes high-fit finds to the partner.

This agent runs with `scaling.copies.count: N` (see the configuration): one activation fans out
into N parallel copies of THIS function, and each copy CLAIMS a disjoint batch
from the discovery queue via `store.claim_opportunities` — an atomic claim so the
copies never double-process the same notice (the doctrine's "a lease is a slot").
With `scaling.copies.handoff: last` the SDK combines the copies deterministically
(lists concatenate, `discovered_count`/`high_fit_count` SUM), so the routing
below fires once on the merged sweep.

Day-0 it reads the seeded discovery queue in the dev store and ANNOUNCES itself
(`available: false`) when the queue is empty and no connector is wired — never a
synthetic "0 new" that looks like a real empty sweep. To go live, create the
vault record 'opportunity_feed_n8n' (Infrastructure → Integrations → n8n: the
workflow against your saved searches) and uncomment the connector lines on this
agent; "wired" is decided by that record existing, never by .env.

auto_discover matches function name 'opportunity_feed_agent' to YAML.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any

from leafmesh import LeafMeshLogger

try:
    from agency._shared import store
    from agency._shared.wired import OPPORTUNITY_FEED_RECORD, vault_record_exists
except ImportError:  # pragma: no cover — direct-module execution
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from _shared import store  # type: ignore[no-redef]
    from _shared.wired import OPPORTUNITY_FEED_RECORD, vault_record_exists  # type: ignore[no-redef]

logger = LeafMeshLogger(__name__)

_BATCH_SIZE = 2   # each copy claims up to this many notices per sweep
                  # (small so parallel copies each get a disjoint slice day-0;
                  #  a real connector caps each claim to its page size)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def opportunity_feed_agent(llm_response: Any, input_data: dict, context: dict) -> dict[str, Any]:
    """Claim a disjoint batch of new opportunities and fit-score it.

    Programmatic agents receive the SDK's standard (llm_response, input_data,
    context) triple; llm_response is None for a non-LLM role.
    """
    if not isinstance(input_data, dict):
        input_data = {}

    wired = await vault_record_exists(OPPORTUNITY_FEED_RECORD)
    claim = store.claim_opportunities(_BATCH_SIZE, connector_wired=wired)

    # Stub announces itself: no queue + no connector => unreachable, NOT "0 new".
    if not claim.get("available"):
        logger.info(f"[opportunity_feed] no notices to claim — {claim.get('reason')}")
        return {
            "available": False,
            "reason": str(claim.get("reason", "")),
            "discovered_count": 0,
            "discovered_rfps": [],
            "high_fit_count": 0,
            "high_fit_rfps": [],
            "skipped_duplicates": 0,
            "requires_partner_review": False,
            "swept_at_utc": _now(),
        }

    claimed = claim.get("claimed", []) or []
    high_fit_min = float(claim.get("high_fit_min", 0.70))
    high_fit = [r for r in claimed if float(r.get("fit_score", 0)) >= high_fit_min]

    logger.info(
        f"[opportunity_feed] claimed={len(claimed)} high_fit={len(high_fit)} "
        f"remaining={claim.get('remaining')}"
    )
    return {
        "available": True,
        "reason": "",
        "discovered_count": len(claimed),
        "discovered_rfps": claimed,
        "high_fit_count": len(high_fit),
        "high_fit_rfps": high_fit,
        "skipped_duplicates": 0,   # the capture tool dedups upstream
        # High-fit finds go to the partner for triage; otherwise just audited.
        "requires_partner_review": bool(high_fit),
        "swept_at_utc": _now(),
    }

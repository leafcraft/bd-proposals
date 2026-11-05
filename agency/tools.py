"""Global tools for the BD-proposals pod — the section drafter's day-0 surface.

These are the tools the `section_drafter_agent` super-agent calls, IN the turn,
to PULL reusable raw material while it plans and writes sections: prior-proposal
prose it can adapt and firm boilerplate it must reuse verbatim. Each reads the
dev store (seeded corpus) so the pod drafts with no connector wired, and **each
announces itself**: when there is no real source and no seed, it returns
`available: false` and says why — never a synthetic success that reads like a
real corpus hit. To go live, create the vault record 'dms_mcp' (Infrastructure →
Integrations → MCP) and uncomment the DMS `mcp` block on section_drafter_agent in
config.yaml (each named action becomes its own tool); these dev tools are the
fallback contract.

Distinct from `precedent_research_agent`, which produces CITATIONS (which prior
wins to cite): the drafter pulls the reusable TEXT to assemble the sections.
"""
import os

from leafmesh import global_tool, LeafMeshLogger

try:
    from ._shared import store
    from ._shared.wired import DMS_RECORD, vault_record_exists
except ImportError:  # pragma: no cover — direct-run fallback
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore
    from _shared.wired import DMS_RECORD, vault_record_exists  # type: ignore

logger = LeafMeshLogger(__name__)


@global_tool(category="drafting")
async def read_reusable_sections(practice_area: str) -> dict:
    """Pull reusable prior-proposal section prose for a practice area, to adapt
    into the draft (approach, team bios, case studies). Announces
    `available: false` when there is genuinely nothing to reuse.

    Args:
        practice_area: The RFP's practice area (e.g. "infrastructure_advisory").
    """
    result = store.read_reusable_sections(
        str(practice_area).strip(), connector_wired=await vault_record_exists(DMS_RECORD))
    logger.info(f"read_reusable_sections practice_area={practice_area} available={result.get('available')}")
    return result


@global_tool(category="drafting")
def read_boilerplate(kind: str = "terms") -> dict:
    """Pull firm boilerplate the drafter must reuse verbatim so wording stays
    consistent and pre-reviewed.

    Args:
        kind: "terms" (standard contract terms) or "compliance_language"
            (per-framework attestation wording).
    """
    return store.read_boilerplate(str(kind or "terms").strip())

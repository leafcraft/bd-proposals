"""Dev-mode store for the BD-proposals operation.

Lets the full RFP chain (intake → precedent → draft → pricing → bid/no-bid
→ contracts) run end-to-end BEFORE any connector is wired. Everything here
is a stand-in for a real system of record:

  * opportunities / RFPs    → your capture tool (GovWin / SAM.gov) + DMS
  * proposal precedents      → your proposal archive / DMS (proposals_library)
  * rate cards               → your pricing / deal-desk system (rate_cards)
  * win/loss history         → your CRM (win_loss_archive)

In production you replace the read calls with connector/RAG calls; the
SHAPE the rest of the mesh reads stays the same — these function
signatures are the contract.

Single-process JSON files under ./data/, lazily seeded on first read so
the demo works out of the box. Swap for Redis/Postgres for a
multi-replica deployment.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DIR = Path("./data")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _path(kind: str) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / f"{kind}.json"


def _load(kind: str) -> dict[str, Any]:
    p = _path(kind)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save(kind: str, data: dict[str, Any]) -> None:
    p = _path(kind)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


# ── Seed data ────────────────────────────────────────────────────────
# A realistic sample opportunity + precedents + rate cards + win/loss
# history so the chain has real material to reason over on day 0.

_OPPORTUNITY_SEED: list[dict[str, Any]] = [
    {
        "rfp_id": "RFP-2026-08813",
        "client_org": "State Department of Transportation — Region IV",
        "practice_area": "infrastructure_advisory",
        "received_at_utc": "2026-06-04T11:00:00Z",
        "due_date": "2026-07-09T17:00:00Z",
        # budget bounds in cents — used by the deterministic in-band check
        "budget_range_cents": {"low": 70000000, "high": 110000000},
        "compliance_required": ["NDA", "FedRAMP"],
        "fit_score": 0.82,
        "scope_summary": (
            "Five-year roadmap consulting for I-95 corridor modernisation — "
            "traffic modelling, environmental review, federal funding strategy."
        ),
    }
]

# Past-proposal precedents — the firm's proposal corpus (DMS). Each is a
# prior engagement the precedent researcher can reuse.
_PRECEDENT_SEED: list[dict[str, Any]] = [
    {
        "proposal_id": "PROP-2024-0431",
        "engagement_id": "ENG-2024-0431",
        "client": "State DOT — Region II",
        "practice_areas": ["infrastructure_advisory", "transportation"],
        "scope_summary": "Highway corridor modernisation roadmap + funding strategy.",
        "outcome": "won",
        "deal_size_cents": 88000000,
        "similarity": 0.78,
    },
    {
        "proposal_id": "PROP-2023-0188",
        "engagement_id": "ENG-2023-0188",
        "client": "Metro Transit Authority",
        "practice_areas": ["infrastructure_advisory", "environmental_review"],
        "scope_summary": "Light-rail environmental review + traffic modelling.",
        "outcome": "won",
        "deal_size_cents": 64000000,
        "similarity": 0.61,
    },
    {
        "proposal_id": "PROP-2023-0042",
        "engagement_id": "ENG-2023-0042",
        "client": "County Public Works",
        "practice_areas": ["infrastructure_advisory"],
        "scope_summary": "Bridge inspection program + capital planning.",
        "outcome": "lost",
        "deal_size_cents": 41000000,
        "similarity": 0.44,
    },
]

# Rate cards — role × day-rate in cents. The pricing floor recomputes
# totals from these; the LLM cannot invent cheaper rates.
_RATE_CARD_SEED: dict[str, Any] = {
    "infrastructure_advisory": {
        "currency": "USD",
        "day_rates_cents": {
            "partner": 650000,
            "principal": 480000,
            "senior_consultant": 320000,
            "consultant": 220000,
            "analyst": 140000,
        },
        # Standard discount band — anything beyond this needs sign-off.
        "standard_discount_pct_max": 10,
    },
    "_default": {
        "currency": "USD",
        "day_rates_cents": {
            "partner": 600000,
            "principal": 450000,
            "senior_consultant": 300000,
            "consultant": 200000,
            "analyst": 130000,
        },
        "standard_discount_pct_max": 10,
    },
}

# Contract drafts / redlines — keyed by rfp_id. The contracts reviewer
# pulls the draft clauses (DMS / contract-management system in prod, e.g.
# Ironclad / DocuSign CLM) so it reviews the REAL clauses, not invented
# ones. The seeded draft carries an UNACCEPTABLE clause (uncapped
# liability) so the unacceptable-clause floor fires on day 0.
_CONTRACT_SEED: dict[str, Any] = {
    "RFP-2026-08813": {
        "rfp_id": "RFP-2026-08813",
        "contract_id": "CON-2026-08813",
        "status": "draft",
        "clauses": [
            {"clause_type": "liability_cap",
             "clause_text": "Consultant's liability under this Agreement shall be unlimited and uncapped."},
            {"clause_type": "payment_terms",
             "clause_text": "Client shall pay all invoices net 30 days from receipt."},
            {"clause_type": "ip_assignment",
             "clause_text": "Client owns all deliverables produced under this engagement."},
            {"clause_type": "termination_for_convenience",
             "clause_text": "Either party may terminate for convenience on 60 days written notice."},
        ],
    },
}

# Approved-proposal content — the drafted sections + priced package +
# compliance attestations, keyed by rfp_id. In production this is the
# DMS / proposal-authoring system of record that the drafting + pricing
# + contracts chain writes into; the proposal_assembler reads the
# APPROVED package from here when a post-HITL run has lost upstream_yields
# (just like the procurement PO executor recovers its plan). The seed
# carries a fully-approved package so the assembler renders a real file
# on day 0. compliance_flags / pricing_flags are EMPTY here — a clean,
# approved package the fail-closed floor will let through.
_APPROVED_PROPOSAL_SEED: dict[str, Any] = {
    "RFP-2026-08813": {
        "rfp_id": "RFP-2026-08813",
        "client_org": "State Department of Transportation — Region IV",
        "practice_area": "infrastructure_advisory",
        "approved": True,
        "approval_reference": "APPROVED-PARTNER",
        "compliance_flags": [],
        "pricing_flags": [],
        "compliance_attestations": [
            {"framework": "NDA", "status": "met",
             "note": "Mutual NDA executed; data-handling addendum attached."},
            {"framework": "FedRAMP", "status": "met",
             "note": "Hosting on FedRAMP-Moderate authorized environment."},
        ],
        "sections": [
            {"title": "Executive Summary",
             "body": ("Our firm proposes a five-year roadmap-consulting "
                      "engagement for the I-95 corridor modernisation, "
                      "combining traffic modelling, environmental review, and "
                      "a federal-funding strategy proven on two prior State "
                      "DOT wins.")},
            {"title": "Approach",
             "body": ("A three-phase approach: (1) baseline traffic + "
                      "environmental assessment, (2) corridor modernisation "
                      "options modelling, (3) a federal-funding capture plan "
                      "aligned to FHWA programs.")},
            {"title": "Team & Qualifications",
             "body": ("A partner-led team including two former FHWA-adjacent "
                      "principals and senior transportation consultants who "
                      "delivered the Region II corridor roadmap (ENG-2024-0431).")},
            {"title": "Timeline",
             "body": ("18-month base period with two option years; phase-gate "
                      "reviews quarterly.")},
            {"title": "Case Studies",
             "body": ("State DOT Region II corridor modernisation (won, "
                      "$880k) and Metro Transit light-rail environmental "
                      "review (won, $640k).")},
        ],
        "pricing": {
            "currency": "USD",
            "total_cents": 92000000,
            "discount_pct": 6,
            "within_band": True,
            "line_items": [
                {"item": "Partner oversight", "role_or_sku": "partner",
                 "quantity": 40, "unit_cents": 650000, "subtotal_cents": 26000000},
                {"item": "Principal lead", "role_or_sku": "principal",
                 "quantity": 60, "unit_cents": 480000, "subtotal_cents": 28800000},
                {"item": "Senior consulting", "role_or_sku": "senior_consultant",
                 "quantity": 90, "unit_cents": 320000, "subtotal_cents": 28800000},
                {"item": "Analyst support", "role_or_sku": "analyst",
                 "quantity": 60, "unit_cents": 140000, "subtotal_cents": 8400000},
            ],
        },
        "terms": [
            "Net 30 payment terms.",
            "Liability capped at 12 months of fees.",
            "Client owns all deliverables produced under this engagement.",
        ],
    },
}

# Win/loss history — what the bid/no-bid strategist reasons over.
_WIN_LOSS_SEED: list[dict[str, Any]] = [
    {
        "rfp_id": "RFP-2025-07120",
        "client_org": "State DOT — Region II",
        "practice_area": "infrastructure_advisory",
        "decision": "won",
        "competitor": "Beacon Advisory",
        "deal_size_cents": 88000000,
    },
    {
        "rfp_id": "RFP-2025-06044",
        "client_org": "Metro Transit Authority",
        "practice_area": "infrastructure_advisory",
        "decision": "won",
        "competitor": "Keystone Partners",
        "deal_size_cents": 64000000,
    },
    {
        "rfp_id": "RFP-2024-05512",
        "client_org": "County Public Works",
        "practice_area": "infrastructure_advisory",
        "decision": "lost",
        "competitor": "Beacon Advisory",
        "deal_size_cents": 41000000,
    },
]


# Competitor signals — the firm's CRM / intel store (Salesforce, Klue,
# Crayon) stand-in. The competitive-intelligence analyst reasons over
# these real moves rather than inventing competitor behaviour. In prod the
# competitor_signal_ledger_agent connector serves these from the CRM.
_COMPETITOR_SIGNAL_SEED: list[dict[str, Any]] = [
    {
        "competitor": "Beacon Advisory",
        "signal_kind": "pricing",
        "summary": "Beacon undercut on the County Public Works bridge program by ~18%.",
        "practice_area": "infrastructure_advisory",
        "impact_score": 0.7,
        "observed_at_utc": "2026-05-12T00:00:00Z",
    },
    {
        "competitor": "Beacon Advisory",
        "signal_kind": "capability",
        "summary": "Beacon hired two former FHWA officials — stronger federal-funding angle.",
        "practice_area": "infrastructure_advisory",
        "impact_score": 0.8,
        "observed_at_utc": "2026-04-30T00:00:00Z",
    },
    {
        "competitor": "Keystone Partners",
        "signal_kind": "relationship",
        "summary": "Keystone has an incumbent seat at Metro Transit Authority.",
        "practice_area": "infrastructure_advisory",
        "impact_score": 0.5,
        "observed_at_utc": "2026-03-18T00:00:00Z",
    },
]


def _seeded(kind: str, seed: Any, key: str | None = None) -> Any:
    """Load a store kind, lazily writing the seed on first access."""
    data = _load(kind)
    if data:
        return data
    if isinstance(seed, dict):
        data = dict(seed)
    elif key:
        data = {item[key]: item for item in seed}
    else:
        data = {"items": list(seed)}
    _save(kind, data)
    return data


# ── Opportunities / RFPs ─────────────────────────────────────────────
def get_opportunity(rfp_id: str) -> dict[str, Any]:
    """Return the captured opportunity record for an rfp_id ({} if none)."""
    if not rfp_id:
        return {}
    return _seeded("opportunities", _OPPORTUNITY_SEED, key="rfp_id").get(rfp_id, {})


def put_opportunity(opp: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _seeded("opportunities", _OPPORTUNITY_SEED, key="rfp_id")
        rid = opp.get("rfp_id") or _new_id("rfp")
        opp["rfp_id"] = rid
        opp["updated_at"] = _now()
        data[rid] = {**data.get(rid, {}), **opp}
        _save("opportunities", data)
        return data[rid]


# ── Proposal precedents (the DMS corpus) ─────────────────────────────
def precedents_for(practice_area: str) -> list[dict[str, Any]]:
    """Prior engagements relevant to a practice area, won-first then by
    similarity. Past WINS are better template fodder."""
    corpus = _seeded("precedents", _PRECEDENT_SEED, key="proposal_id").values()
    pa = (practice_area or "").strip().lower()
    matches = [
        p for p in corpus
        if not pa or pa in [str(x).lower() for x in p.get("practice_areas", [])]
    ]
    if not matches:  # never starve the researcher — fall back to whole corpus
        matches = list(corpus)
    return sorted(
        matches,
        key=lambda p: (p.get("outcome") != "won", -float(p.get("similarity", 0))),
    )


def all_precedents() -> list[dict[str, Any]]:
    return list(_seeded("precedents", _PRECEDENT_SEED, key="proposal_id").values())


# ── Rate cards (pricing) ─────────────────────────────────────────────
def rate_card(practice_area: str) -> dict[str, Any]:
    """Day-rate card for a practice area, falling back to the default."""
    cards = _seeded("rate_cards", _RATE_CARD_SEED)
    return cards.get((practice_area or "").strip().lower()) or cards.get("_default", {})


# ── Win/loss history ─────────────────────────────────────────────────
def win_loss_for(practice_area: str) -> list[dict[str, Any]]:
    rows = _seeded("win_loss", _WIN_LOSS_SEED, key="rfp_id").values()
    pa = (practice_area or "").strip().lower()
    return [r for r in rows if not pa or str(r.get("practice_area", "")).lower() == pa]


def win_rate(practice_area: str) -> float:
    rows = win_loss_for(practice_area) or list(
        _seeded("win_loss", _WIN_LOSS_SEED, key="rfp_id").values()
    )
    decided = [r for r in rows if r.get("decision") in ("won", "lost")]
    if not decided:
        return 0.0
    return round(sum(1 for r in decided if r["decision"] == "won") / len(decided), 2)


def record_decision(row: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        data = _seeded("win_loss", _WIN_LOSS_SEED, key="rfp_id")
        rid = row.get("rfp_id") or _new_id("rfp")
        row["rfp_id"] = rid
        row["recorded_at"] = _now()
        data[rid] = {**data.get(rid, {}), **row}
        _save("win_loss", data)
        return data[rid]


# ── Contract drafts / clauses (the contracts-reviewer source) ────────
def contract_for(rfp_id: str) -> dict[str, Any]:
    """The draft contract + clauses for an rfp_id ({} if none). PROD:
    contract-management system (Ironclad / DocuSign CLM) read."""
    if not rfp_id:
        return {}
    return _seeded("contracts", _CONTRACT_SEED).get(rfp_id, {})


def compliance_must_haves(rfp_id: str) -> list[str]:
    """The captured opportunity's declared compliance must-haves — the
    obligations a contract review must never silently drop."""
    opp = get_opportunity(rfp_id)
    req = opp.get("compliance_required") or []
    return [str(r) for r in req] if isinstance(req, list) else []


# ── Approved-proposal content (the assembler source) ─────────────────
def approved_proposal(rfp_id: str) -> dict[str, Any]:
    """The APPROVED proposal package (sections + pricing + compliance
    attestations) for an rfp_id ({} if none). PROD: DMS / proposal-
    authoring system read. Used by proposal_assembler_agent to recover the
    approved content after the HITL gate drops upstream_yields."""
    if not rfp_id:
        return {}
    return _seeded("approved_proposals", _APPROVED_PROPOSAL_SEED).get(rfp_id, {})


def put_approved_proposal(rfp_id: str, package: dict[str, Any]) -> dict[str, Any]:
    """Persist (or merge) an approved proposal package keyed by rfp_id so
    the assembler can recover it post-HITL. Returns the stored record."""
    with _LOCK:
        data = _seeded("approved_proposals", _APPROVED_PROPOSAL_SEED)
        rid = rfp_id or package.get("rfp_id") or _new_id("rfp")
        package = {**package, "rfp_id": rid, "updated_at": _now()}
        data[rid] = {**data.get(rid, {}), **package}
        _save("approved_proposals", data)
        return data[rid]


# ── Competitor signals (the competitive-intel source) ────────────────
def competitor_signals(practice_area: str = "", competitor: str = "") -> list[dict[str, Any]]:
    """Competitor signals from the firm's CRM / intel store, optionally
    filtered by practice area and/or competitor. PROD: CRM query."""
    rows = _seeded("competitor_signals", _COMPETITOR_SIGNAL_SEED,
                   key=None).get("items", [])
    pa = (practice_area or "").strip().lower()
    cp = (competitor or "").strip().lower()
    out = [
        r for r in rows
        if (not pa or str(r.get("practice_area", "")).lower() == pa)
        and (not cp or str(r.get("competitor", "")).lower() == cp)
    ]
    return sorted(out, key=lambda r: -float(r.get("impact_score", 0)))


def top_competitors(practice_area: str = "") -> list[str]:
    """Distinct competitors seen in the signal ledger, by aggregate impact."""
    agg: dict[str, float] = {}
    for s in competitor_signals(practice_area):
        agg[s.get("competitor", "")] = agg.get(s.get("competitor", ""), 0.0) + float(
            s.get("impact_score", 0)
        )
    return [c for c, _ in sorted(agg.items(), key=lambda kv: -kv[1]) if c]


new_id = _new_id

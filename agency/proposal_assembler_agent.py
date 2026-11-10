"""Programmatic Agent — Proposal assembler (the artifact-producing executor).

This is the role that FINISHES the BD-proposals job. Every other agent
drafts, prices, reviews, or routes; this one RENDERS the actual proposal
document a partner can send to the client — turning a draft-and-route
team into one that ships a deliverable.

It runs AFTER the proposal is approved (the proposal_writer_human gate
returns approve / submit) and assembles the APPROVED package into a real
file on disk:

    cover · executive summary · scope/approach · pricing table ·
    compliance attestations · terms

Render strategy (mirrors procurement-ops/purchase_order_agent):
  * ReportLab present  → a REAL PDF at ./out/<proposal>.pdf
  * ReportLab absent   → a deterministic Markdown render at ./out/<proposal>.md
Either way the function returns a real artifact_path that exists and is
non-empty, plus a summary.

Content recovery (mirrors the PO executor's post-HITL recovery): a human
approval step drops upstream_yields, so the assembler resolves the
approved content from, in priority order:
  1. direct upstream_yields (no-HITL / direct-call path)
  2. the in-process session stash
  3. Redis session storage (recovered via session_id)
  4. the dev store's approved-proposal record (DMS stand-in) — seeded so
     the day-0 demo renders a real file with no connectors wired.

@chain fail-closed floor (enforce_assembly_floor): NEVER assemble a
proposal that wasn't approved, or that carries unresolved compliance /
pricing flags. The floor recomputes approval + flags from the resolved
package and BLOCKS — deleting any partially-written artifact — when the
gate is not clean. The LLM/human cannot talk an unapproved or flagged
proposal into a finished document.

auto_discover matches function name 'proposal_assembler_agent' to YAML.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger, chain

try:
    from leafmesh.redis import RedisManager
except ImportError:  # pragma: no cover — Redis optional in dev
    RedisManager = None  # type: ignore[assignment]

try:
    from agency._shared import store
    from agency._shared.session_stash import stash_get
except ImportError:  # pragma: no cover — direct-module execution
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from _shared import store  # type: ignore[no-redef]
    from _shared.session_stash import stash_get  # type: ignore[no-redef]

logger = LeafMeshLogger(__name__)

_OUT_DIR = Path("./out")

_APPROVE_WORDS = frozenset({"approve", "approved", "submit", "submitted", "send", "yes", "ship"})
_REJECT_WORDS = frozenset({"reject", "rejected", "deny", "denied", "cancel", "cancelled", "no", "hold", "halt"})


def _cents(value: Any) -> str:
    try:
        return f"${int(round(float(value))) / 100:,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _slug(rfp_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in (rfp_id or "proposal"))
    return safe or "proposal"


def _parse_json(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return text
    if isinstance(text, str):
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


# ─── Approved-package resolution (post-HITL recovery) ─────────────────
def _resolve_package(input_data: dict, context: dict) -> tuple[dict, str]:
    """Resolve the APPROVED proposal package (sections + pricing +
    compliance attestations) and the human verdict, recovering it across
    the HITL boundary the way purchase_order_agent recovers its plan."""
    upstream = input_data.get("upstream_yields") or {}
    if not upstream:
        upstream = input_data.get("upstream_results") or {}
    if not upstream:
        upstream = (
            context.get("upstream_yields")
            or context.get("session_yields")
            or context.get("agent_yields")
            or {}
        )

    # The human verdict from proposal_writer_human (or a direct call).
    human_message = str(
        input_data.get("human_message")
        or context.get("human_message")
        or upstream.get("human_message", "")
        or ""
    ).lower()

    # rfp_id resolves the stored record.
    rfp_id = str(
        input_data.get("rfp_id")
        or context.get("rfp_id")
        or upstream.get("rfp_id")
        or input_data.get("original_webhook_data", {}).get("rfp_id")
        or ""
    )

    # Drafted sections + priced package, if they rode along on upstream.
    drafter = upstream.get("section_drafter_agent") or {}
    drafter = drafter.get("main_result") or drafter
    pricer = upstream.get("pricing_configurator_agent") or {}
    pricer = pricer.get("main_result") or pricer
    contracts = upstream.get("contracts_review_agent") or {}
    contracts = contracts.get("main_result") or contracts

    if not rfp_id:
        rfp_id = str(pricer.get("rfp_id") or contracts.get("rfp_id") or "")

    session_id = str(
        context.get("session_id")
        or input_data.get("session_id")
        or input_data.get("original_webhook_data", {}).get("session_id")
        or ""
    )

    # 2. in-process session stash (Redis-independent post-HITL path).
    stash = stash_get(session_id) if session_id else {}
    if not rfp_id:
        rfp_id = str(stash.get("rfp_id") or "")
    if not rfp_id and session_id:
        # The writer's reply carries only the verdict; the pursuit's rfp_id
        # was bound to this session by pricing / contracts review.
        rfp_id = store.rfp_for_session(session_id)

    # 3. Redis session storage.
    redis_pkg: dict = {}
    if session_id and RedisManager is not None and not (drafter and pricer):
        try:
            # The project has no configuration file: the agency's name and
            # where its store is come from the environment (.env).
            from leafmesh.core.config_document import boot_config_from_env
            cfg = boot_config_from_env()
            rm = RedisManager(cfg.redis, project_name=cfg.name)
            import asyncio

            async def _pull() -> dict:
                await rm.connect()
                raw = await rm.get_agent_yields(session_id, "section_drafter_agent") or {}
                return raw.get("yields") or raw

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    redis_pkg = {}
                else:
                    redis_pkg = loop.run_until_complete(_pull())
            except RuntimeError:
                redis_pkg = asyncio.run(_pull())
        except Exception as e:  # pragma: no cover — Redis optional
            logger.warning(f"proposal_assembler_agent — Redis lookup failed: {e}")

    # 4. dev store approved-proposal record (DMS stand-in / day-0 seed).
    stored = store.approved_proposal(rfp_id) if rfp_id else {}

    # Assemble the package, preferring live upstream over the stored record.
    sections = (
        drafter.get("sections")
        or stash.get("sections")
        or redis_pkg.get("sections")
        or stored.get("sections")
        or []
    )
    pricing = (
        ({"line_items": pricer.get("pricing_breakdown"),
          "total_cents": pricer.get("total_cents"),
          "discount_pct": pricer.get("discount_pct"),
          "within_band": pricer.get("within_band")}
         if pricer.get("pricing_breakdown") else {})
        or stash.get("pricing")
        or redis_pkg.get("pricing")
        or stored.get("pricing")
        or {}
    )
    attestations = (
        stash.get("compliance_attestations")
        or stored.get("compliance_attestations")
        or []
    )
    # Compliance / pricing flags that must be CLEAR before assembly.
    compliance_flags = list(
        contracts.get("reasons", [])
        if str(contracts.get("clearance", "")).lower() == "blocked"
        else (stored.get("compliance_flags") or [])
    )
    if contracts.get("requires_legal_review"):
        compliance_flags = compliance_flags or ["legal review still required"]
    pricing_flags = list(stored.get("pricing_flags") or [])
    if pricing and pricing.get("within_band") is False:
        pricing_flags = pricing_flags or ["pricing not within budget band"]

    package = {
        "rfp_id": rfp_id or stored.get("rfp_id", ""),
        "client_org": stored.get("client_org") or drafter.get("client_org", ""),
        "practice_area": stored.get("practice_area", ""),
        "sections": sections,
        "pricing": pricing,
        "compliance_attestations": attestations,
        "terms": stored.get("terms") or [],
        "compliance_flags": compliance_flags,
        "pricing_flags": pricing_flags,
        "approval_reference": (
            stored.get("approval_reference")
            or input_data.get("approval_reference")
            or ("APPROVED" if any(w in human_message for w in _APPROVE_WORDS) else "")
        ),
        # `approved` is recomputed by the floor — this is only the hint.
        "approved": bool(stored.get("approved")),
    }
    return package, human_message


# ─── Artifact rendering ───────────────────────────────────────────────
def _render_markdown(pkg: dict) -> str:
    """Deterministic Markdown render (the ReportLab-absent fallback)."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = _OUT_DIR / f"{_slug(pkg.get('rfp_id', 'proposal'))}.md"
    rfp_id = pkg.get("rfp_id", "")
    client = pkg.get("client_org", "")
    issued = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines: list[str] = []
    lines.append(f"# Proposal — {rfp_id}")
    lines.append("")
    lines.append(f"**Prepared for:** {client or '—'}  ")
    lines.append(f"**Practice area:** {pkg.get('practice_area', '') or '—'}  ")
    lines.append(f"**Date:** {issued}  ")
    lines.append(f"**Approval reference:** {pkg.get('approval_reference', '') or '—'}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for sec in pkg.get("sections", []):
        if isinstance(sec, dict):
            title = sec.get("title") or sec.get("name") or "Section"
            body = sec.get("body") or sec.get("content") or sec.get("text") or ""
        else:
            title, body = "Section", str(sec)
        lines.append(f"## {title}")
        lines.append("")
        lines.append(str(body))
        lines.append("")

    pricing = pkg.get("pricing") or {}
    items = pricing.get("line_items") or []
    if items:
        lines.append("## Pricing")
        lines.append("")
        lines.append("| Item | Role / SKU | Qty | Unit | Subtotal |")
        lines.append("|------|-----------|-----|------|----------|")
        for it in items:
            lines.append(
                f"| {it.get('item', '')} | {it.get('role_or_sku', '')} "
                f"| {it.get('quantity', '')} | {_cents(it.get('unit_cents', 0))} "
                f"| {_cents(it.get('subtotal_cents', 0))} |"
            )
        lines.append(f"| **Total** | | | | **{_cents(pricing.get('total_cents', 0))}** |")
        if pricing.get("discount_pct"):
            lines.append("")
            lines.append(f"_Discount applied: {pricing.get('discount_pct')}%_")
        lines.append("")

    attestations = pkg.get("compliance_attestations") or []
    if attestations:
        lines.append("## Compliance Attestations")
        lines.append("")
        for a in attestations:
            lines.append(
                f"- **{a.get('framework', '')}** — {a.get('status', '')}: "
                f"{a.get('note', '')}"
            )
        lines.append("")

    terms = pkg.get("terms") or []
    if terms:
        lines.append("## Terms")
        lines.append("")
        for t in terms:
            lines.append(f"- {t}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _render_pdf(pkg: dict) -> str:
    """Render the approved proposal to a real PDF via ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
    )

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = _OUT_DIR / f"{_slug(pkg.get('rfp_id', 'proposal'))}.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("PTitle", parent=styles["Title"], fontSize=20, spaceAfter=4)
    sub_style = ParagraphStyle("PSub", parent=styles["Normal"], fontSize=10, textColor=colors.grey)
    h2 = ParagraphStyle("PH2", parent=styles["Heading2"], fontSize=13,
                        textColor=colors.HexColor("#1a3a5c"), spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("PBody", parent=styles["Normal"], fontSize=9.5, leading=13)

    brand = colors.HexColor("#1a3a5c")
    accent = colors.HexColor("#2e86c1")
    issued = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    el: list[Any] = []
    # Cover
    el.append(Paragraph("PROPOSAL", title_style))
    el.append(Paragraph(f"<b>{pkg.get('rfp_id', '')}</b>", sub_style))
    el.append(HRFlowable(width="100%", thickness=2, color=brand))
    el.append(Spacer(1, 6 * mm))
    cover = [
        ["Prepared For", pkg.get("client_org", "") or "—"],
        ["Practice Area", pkg.get("practice_area", "") or "—"],
        ["Date", issued],
        ["Approval Reference", pkg.get("approval_reference", "") or "—"],
    ]
    ctbl = Table(cover, colWidths=[50 * mm, 115 * mm])
    ctbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), brand),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f4f8fb")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0dce8")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    el.append(ctbl)
    el.append(Spacer(1, 8 * mm))

    # Sections
    for sec in pkg.get("sections", []):
        if isinstance(sec, dict):
            title = sec.get("title") or sec.get("name") or "Section"
            text = sec.get("body") or sec.get("content") or sec.get("text") or ""
        else:
            title, text = "Section", str(sec)
        el.append(Paragraph(str(title), h2))
        el.append(Paragraph(str(text), body))

    # Pricing table
    pricing = pkg.get("pricing") or {}
    items = pricing.get("line_items") or []
    if items:
        el.append(Paragraph("Pricing", h2))
        rows = [["Item", "Role / SKU", "Qty", "Unit", "Subtotal"]]
        for it in items:
            rows.append([
                str(it.get("item", "")), str(it.get("role_or_sku", "")),
                str(it.get("quantity", "")), _cents(it.get("unit_cents", 0)),
                _cents(it.get("subtotal_cents", 0)),
            ])
        rows.append(["Total", "", "", "", _cents(pricing.get("total_cents", 0))])
        ptbl = Table(rows, colWidths=[55 * mm, 40 * mm, 18 * mm, 26 * mm, 26 * mm], repeatRows=1)
        ptbl.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), brand),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f4f8fb")]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0dce8")),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (-1, -1), (-1, -1), accent),
            ("LINEABOVE", (0, -1), (-1, -1), 1, brand),
        ]))
        el.append(ptbl)
        if pricing.get("discount_pct"):
            el.append(Spacer(1, 2 * mm))
            el.append(Paragraph(f"Discount applied: {pricing.get('discount_pct')}%", sub_style))

    # Compliance attestations
    attestations = pkg.get("compliance_attestations") or []
    if attestations:
        el.append(Paragraph("Compliance Attestations", h2))
        for a in attestations:
            el.append(Paragraph(
                f"<b>{a.get('framework', '')}</b> — {a.get('status', '')}: "
                f"{a.get('note', '')}", body))

    # Terms
    terms = pkg.get("terms") or []
    if terms:
        el.append(Paragraph("Terms", h2))
        for t in terms:
            el.append(Paragraph(f"• {t}", body))

    el.append(Spacer(1, 8 * mm))
    el.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    el.append(Paragraph(
        "System-assembled from the approved proposal package.",
        ParagraphStyle("foot", fontSize=7, textColor=colors.grey)))

    doc.build(el)
    return str(pdf_path)


def _render(pkg: dict) -> tuple[str, str]:
    """Render to PDF if ReportLab is available, else Markdown. Returns
    (artifact_path, artifact_format)."""
    try:
        import reportlab  # noqa: F401
        return _render_pdf(pkg), "pdf"
    except Exception as e:
        logger.info(f"proposal_assembler_agent — ReportLab unavailable ({e}); rendering Markdown")
        return _render_markdown(pkg), "markdown"


# ─── @chain fail-closed floor ─────────────────────────────────────────
# Runs AFTER proposal_assembler_agent. A proposal document is a binding,
# client-facing artifact: it is NEVER produced unless the package was
# approved AND carries no unresolved compliance / pricing flags. If the
# floor finds the gate unclean, it deletes any artifact that was written
# and returns a blocked result — fail closed, like the PO-validity floor.

def enforce_assembly_floor(result, context):
    if not isinstance(result, dict):
        return result

    approved = bool(result.get("approved"))
    compliance_flags = result.get("compliance_flags") or []
    pricing_flags = result.get("pricing_flags") or []
    blockers: list[str] = []
    if not approved:
        blockers.append("proposal not approved")
    if compliance_flags:
        blockers.append(f"unresolved compliance flags: {compliance_flags}")
    if pricing_flags:
        blockers.append(f"unresolved pricing flags: {pricing_flags}")

    if blockers:
        # Fail closed: never leave a binding artifact on disk for a
        # proposal that wasn't cleanly approved.
        path = result.get("artifact_path")
        if path:
            try:
                p = Path(path)
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        result["artifact_path"] = ""
        result["artifact_produced"] = False
        result["status"] = "assembly_blocked"
        result["blocked_reasons"] = blockers
        logger.error(
            f"enforce_assembly_floor BLOCKED rfp_id={result.get('rfp_id','')} — {blockers}"
        )
        return result

    result.setdefault("blocked_reasons", [])
    logger.info(
        f"enforce_assembly_floor CLEARED rfp_id={result.get('rfp_id','')} "
        f"artifact={result.get('artifact_path','')}"
    )
    return result


@chain(enforce_assembly_floor)
async def proposal_assembler_agent(llm_response, input_data: dict, context: dict) -> dict[str, Any]:
    """Render the approved proposal package into a real document file.

    Programmatic agents receive the SDK's standard (llm_response,
    input_data, context) triple; llm_response is None for a non-LLM role.
    """
    if not isinstance(input_data, dict):
        input_data = _parse_json(input_data)
    if not isinstance(context, dict):
        context = {}

    package, human_message = _resolve_package(input_data, context)
    rfp_id = package.get("rfp_id", "")

    # Approval verdict: explicit reject wins; otherwise approved when the
    # human said approve/submit OR the stored record is already approved
    # (and a direct call may pass approved=True). The floor re-checks this.
    rejected = any(w in human_message for w in _REJECT_WORDS)
    approved = (
        not rejected
        and (
            any(w in human_message for w in _APPROVE_WORDS)
            or bool(package.get("approved"))
            or bool(input_data.get("approved"))
        )
    )
    package["approved"] = approved

    base = {
        "rfp_id": rfp_id,
        "approved": approved,
        "compliance_flags": package.get("compliance_flags", []),
        "pricing_flags": package.get("pricing_flags", []),
        "approval_reference": package.get("approval_reference", ""),
        "section_count": len(package.get("sections") or []),
    }

    # No clean approval, or unresolved flags → do NOT render. The floor
    # also enforces this, but we avoid writing a file we'd only delete.
    if (not approved) or package.get("compliance_flags") or package.get("pricing_flags"):
        logger.warning(
            f"proposal_assembler_agent — not assembling rfp_id={rfp_id}: "
            f"approved={approved} compliance_flags={package.get('compliance_flags')} "
            f"pricing_flags={package.get('pricing_flags')}"
        )
        return {
            **base,
            "artifact_path": "",
            "artifact_format": "",
            "artifact_produced": False,
            "status": "not_assembled",
            "summary": (
                f"Proposal {rfp_id or '(unknown)'} NOT assembled — "
                f"{'rejected/unapproved' if not approved else 'unresolved flags'}."
            ),
        }

    if not package.get("sections"):
        logger.warning(f"proposal_assembler_agent — no sections for rfp_id={rfp_id}; nothing to render")
        return {
            **base,
            "artifact_path": "",
            "artifact_format": "",
            "artifact_produced": False,
            "status": "no_content",
            "summary": f"Proposal {rfp_id or '(unknown)'} has no approved sections to render.",
        }

    artifact_path, artifact_format = _render(package)
    exists = bool(artifact_path) and Path(artifact_path).exists() and Path(artifact_path).stat().st_size > 0
    total = (package.get("pricing") or {}).get("total_cents", 0)

    logger.info(
        f"proposal_assembler_agent — rendered {artifact_format.upper()} for "
        f"rfp_id={rfp_id}: {artifact_path} ({Path(artifact_path).stat().st_size if exists else 0} bytes)"
    )

    return {
        **base,
        "artifact_path": artifact_path,
        "artifact_format": artifact_format,
        "artifact_produced": exists,
        "total_cents": total,
        "total_formatted": _cents(total),
        "status": "assembled",
        "summary": (
            f"Assembled proposal {rfp_id} for "
            f"{package.get('client_org', '') or 'client'} — "
            f"{base['section_count']} sections, total {_cents(total)} — "
            f"rendered to {artifact_path}"
        ),
    }

# bd-proposals — BD Proposals

A complete RFP-response department: one agency that takes a request for
proposal from arrival to a signed-off, compliance-checked, priced draft —
and learns from every win and loss. The narrative roles run from YAML; the
four judgment-heavy roles (intake, precedent, pricing, bid/no-bid) carry a
Python floor — a deterministic `@chain` the LLM can't waive plus a
`@pre_compose` that pulls real context — so pricing approval tiers,
bid/no-bid criteria, compliance must-haves, and precedent citation are
enforced by construction, not hoped for in a prompt. A seeded dev store
lets the whole chain run on day 0 with no connectors wired.

## Story

Priya runs business development at a mid-size services firm. Her firm's
GovWin and SAM.gov saved searches surface a new federal RFP, and the
**opportunity feed** (an n8n workflow against those capture tools) pulls
it in pre-deduplicated and fit-scored. Because the fit is high, the find
goes straight to Priya as **partner** for triage; she nudges it into the
pipeline.

**RFP intake** normalises the notice — client, practice area, due date,
budget — and in the same pass extracts structured requirements from the
attached SOW PDF, classifying each line as *must / should / may* and
scoring extraction completeness. The package is clean and has no
deal-breakers, so it flows to **precedent research**, which queries the
firm's proposal archive (its DMS, indexed into the `proposals_library`
knowledge group) for the three most reusable prior wins. The **section
drafter** writes the executive summary, approach, team bios, timeline and
case studies, citing those past proposals. The **pricing configurator**
builds line-item pricing against the firm's rate cards; the total lands
in-band and the discount is modest, so it flows straight to **contracts
review**. That role runs a regulatory-fit check, finds no blocking
clause, and routes the finished package to the **proposal writer** for
final polish and send. Every hop is appended to a hash-chained WORM audit.

Three weeks later the decision arrives. The **competitive-intelligence
analyst** runs a structured win/loss post-mortem, and the competitor
moves it surfaces are auto-forwarded to the firm's CRM through the
**competitor-signal ledger** — so the next RFP in that space starts
smarter.

## Why it works in an organization

RFP response is expensive, deadline-driven, and judgment-heavy — and most
of the cost is *coordination*, not writing. This agency collapses the
coordination: discovery, intake, precedent retrieval, drafting, pricing,
and compliance run as one forward-flowing chain, with humans gated in only
where judgment is irreversible (deal-breakers, out-of-band pricing,
unacceptable contract clauses, final send). The firm's existing systems
stay the source of truth — the capture tool owns the watchlist and dedup,
the DMS owns the proposal corpus, the CRM owns competitor intelligence —
so nothing has to be migrated into template storage. The payoff: more
bids answered per BD head, faster turnaround on deadline-bound RFPs, fewer
compliance misses (the unacceptable-clause legal gate is enforced by
construction, not hoped for), and a compounding win/loss memory that makes
every subsequent proposal cheaper to produce.

## Configuration

Three tiers. Copy `env` to `.env` and fill in by tier.

**Tier 1 — Boot (required).** The mesh will not run without these.
- `LEAFMESH_LICENSE_KEY` — required by the SDK to start.
- `OPENAI_API_KEY` — the `gpt-4o-mini` roles (intake, precedent, pricing,
  bid/no-bid).
- `ANTHROPIC_API_KEY` — the `claude-sonnet-4-6` roles (section drafter,
  contracts review, competitive intel).
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` — session + auto-storage
  backbone (defaults: `localhost` / `6379` / empty).

**Tier 2 — Host prereqs / adapters (optional, recommended).** Manager
escalation targets in `configs/config.yaml`.
- `PAGER_WEBHOOK` — PagerDuty (or any) incident webhook for hard
  escalations (defaults to the PagerDuty enqueue URL).
- `SLACK_BD_CHANNEL` + `SLACK_BOT_TOKEN` — set BOTH to enable the slack
  channel escalation target; the token authenticates the post.
- `SLACK_SIGNING_SECRET` — only needed if you add a slack *inbound*
  webhook (none ship here); leave unset otherwise.

**Tier 3 — Connectors (optional; wire to your systems).** Until set, the
two `programmatic` n8n agents return empty results gracefully and their
crons stay off.
- `OPPORTUNITY_FEED_WEBHOOK_URL` + `OPPORTUNITY_FEED_AUTH_TOKEN` — the
  n8n workflow that queries your GovWin / SAM.gov / FedConnect saved
  searches and returns only new notices. After wiring, uncomment the
  `wake_up: "0 6 * * *"` cron on `opportunity_feed_agent`.
- `CRM_SIGNAL_WEBHOOK_URL` + `CRM_SIGNAL_AUTH_TOKEN` — the n8n workflow
  against your CRM / intel store (Salesforce, HubSpot, Klue, Crayon,
  Notion) for the competitor-signal ledger (ingest / query).

```bash
cp env .env && pip install -r requirements.txt && python main.py
```

## Run it (day 0, no connectors)

The dev store (`agency/_shared/store.py`) ships seeded with a sample
opportunity (`RFP-2026-08813`), three proposal precedents, a rate card,
and win/loss history — so the full chain runs before any external system
is wired. With the mesh booted (`python main.py`), kick the captured RFP
into intake:

```python
import asyncio
from leafmesh import LeafMesh
from agency._shared import audit_logger

mesh = LeafMesh.from_yaml("configs/config.yaml")
audit_logger.register(mesh, "bd_audit_logger_agent")

async def go():
    await mesh.start()
    result = await mesh.mesh_call("rfp_email", input_data={
        "payload": {"rfp_id": "RFP-2026-08813"},   # seeded in the dev store
        "documents": [],
    })
    print(result)   # normalised RFP — compliance must-haves unioned from the store,
                    # completeness recomputed by the @chain floor
    await mesh.stop()

asyncio.run(go())
```

You can drive the pre-priced, end-to-end flow (intake → precedent →
draft → pricing → contracts) and the post-mortem scenarios with the
bundled payloads:

```bash
python examples/run_examples.py            # all scenarios
python examples/run_examples.py 01         # one scenario
```

The seeded numbers exercise the floors directly: `RFP-2026-08813` carries
an `FedRAMP` compliance must-have (unioned in by the intake floor) and a
$70M–$110M budget band (the pricing floor's in-band check).

## Agents

| Agent | Role | Responsibilities | Can perform |
|---|---|---|---|
| `opportunity_feed_agent` | Capture-tool scout | Pulls new, pre-deduplicated, fit-scored RFP notices from the firm's GovWin / SAM.gov / FedConnect saved searches | n8n connector pull; routes high-fit finds to the partner, otherwise to the audit log |
| `rfp_intake_agent` | Opportunity-intake specialist | Normalises an inbound RFP (client, practice area, due date, budget) AND extracts structured requirements from attachments with must/should/may classification + completeness scoring | `gpt-4o-mini` over `rfp_templates` knowledge; routes deal-breakers / incomplete extraction to the partner, clean packages to precedent research |
| `precedent_research_agent` | Precedent researcher | Retrieves similar prior wins and the top proposal-library matches as RAG context for drafting; never invents proposals retrieval didn't return | `gpt-4o-mini` over `proposals_library` (the firm's DMS); hands the corpus to the section drafter |
| `section_drafter_agent` | Proposal drafter | Writes each required section (exec summary, approach, team bios, timeline, case studies) citing past proposals | `claude-sonnet-4-6` over `section_templates` knowledge; hands the draft to pricing |
| `pricing_configurator_agent` | Pricing configurator | Builds line-item pricing against the rate card; a `@chain` floor recomputes the total from the line items and computes the approval tiers (the LLM can't dodge a sign-off) | `gpt-4o-mini` over `rate_cards` + `@pre_compose`/`@chain` floor; routes on the computed flags: >$1M → partner, >20% discount → practice lead, else → contracts review |
| `contracts_review_agent` | Contracts reviewer | Regulatory/legal fit review of the package (regulatory mode) AND clause-by-clause playbook review of a draft contract (playbook mode) | `claude-sonnet-4-6` over `contract_playbook`; hard legal gate on any unacceptable clause / blocked clearance, deal-desk gate to practice lead, clean packages to the proposal writer |
| `bid_no_bid_decisioner_agent` | Bid/no-bid strategist | Scores RFP fit on five axes → bid / qualify further / no-bid; never silently no-bids on a weak signal | `gpt-4o-mini` over `rfp_decision_playbook`; routes low-confidence to the partner, a "bid" verdict to the section drafter |
| `competitive_intel_agent` | Competitive-intelligence analyst | Runs win/loss post-mortems and quarterly reviews; surfaces competitor signals and learnings | `claude-sonnet-4-6` over `win_loss_archive`; briefs the practice lead, auto-forwards surfaced signals to the CRM ledger |
| `competitor_signal_ledger_agent` | Competitor-signal registrar | Ingests one competitor signal into / queries signals from the firm's CRM intel store (ingest / query modes) | n8n connector against the CRM; writes the result to the audit log on success |
| `proposal_writer_human` | Proposal writer | Final polish and send of the approved proposal | Human gate (2h timeout, default-deny → escalate to practice lead); routes onward to practice lead or audit |
| `practice_lead_human` | Practice lead | Pricing and practice-area sign-off | Human gate (4h timeout, default-deny → escalate to partner); routes to partner or audit |
| `legal_human` | Legal counsel | Compliance / IP / regulator review on any hard-gated package | Human gate (6h timeout, default-deny → hold for review); lands in the audit log |
| `partner_human` | Partner | Sign-off on high-value deals and deal-breakers | Human gate (8h timeout, default-deny → hold for review); lands in the audit log |
| `bd_audit_logger_agent` | Audit registrar | Appends every terminal hop to a hash-chained, append-only (WORM) audit trail | Custom external sink → `./logs/bd_audit.jsonl` (swap for S3 Object Lock / Splunk / Datadog in prod); terminal |

See **PRD.md** for the flow diagram, per-agent specs, data artifacts, and
design decisions.

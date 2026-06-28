# PRD — bd-proposals (BD Proposals)

## Overview & story

A complete RFP-response department modelled as a LeafMesh agency. A
request for proposal enters through one of several channels, is normalised
and requirement-extracted, researched against the firm's prior wins,
drafted, priced, compliance-reviewed, and sent — with human gates at every
irreversible decision and a hash-chained WORM audit on every terminal
branch. The firm's existing systems remain the source of truth: the
capture tool owns the opportunity watchlist and dedup, the DMS owns the
proposal corpus, and the CRM owns competitor intelligence; the agency
reaches them through n8n connectors.

**Story.** Priya (BD partner at a services firm) gets a high-fit federal
RFP surfaced by the capture-tool scout. RFP intake normalises it and
extracts must/should/may requirements from the SOW. Precedent research
pulls the three best reusable prior wins from the DMS; the section drafter
writes the package citing them; the pricing configurator prices it
in-band; contracts review clears it; the proposal writer sends it. Weeks
later, the win/loss decision triggers a structured post-mortem whose
competitor signals are forwarded to the CRM — so the next bid starts
smarter. Every hop is appended to a tamper-evident audit trail.

## Flow diagram

```
                 ┌─────────────────────────────────────────────────────┐
  capture tool   │  opportunity_feed (n8n)                              │
  (GovWin/SAM) ─▶│    high-fit ─▶ partner_human                         │
                 │    else      ─▶ bd_audit_logger                      │
                 └─────────────────────────────────────────────────────┘

  email / portal / referral / manual
        │
        ▼
  rfp_intake ──(deal-breaker OR extraction incomplete)──▶ partner_human
        │
        └──(clean & complete)──▶ precedent_research ──▶ section_drafter ──▶ pricing
                                                                              │
        bid_no_bid (entry: bid_no_bid_review)                                 │
          ├─(requires_partner_review)──▶ partner_human                       │
          └─(bid)────────────────────▶ section_drafter                       │
                                                                              ▼
                                            pricing_configurator
                                              ├─(total >$1M)──────────▶ partner_human
                                              ├─(discount >20%)───────▶ practice_lead_human
                                              └─(in-band)──────────────▶ contracts_review
                                                                              │
                       ┌──────────────────────────────────────────────────────┤
                       │                                                        │
        (unacceptable clause / blocked) ──▶ legal_human ──▶ audit               │
        (needs_review / deal-desk) ───────▶ practice_lead_human                 │
        (regulatory ok) ──────────────────▶ proposal_writer_human              │
        (playbook clean) ─────────────────▶ bd_audit_logger                    │

  proposal_writer ─(escalate)─▶ practice_lead ─(escalate)─▶ partner ─▶ audit
  practice_lead / legal / partner ──▶ bd_audit_logger (WORM terminus)

  decision_received / competitor_takeaway / quarterly_win_rate_review
        │
        ▼
  competitive_intel ──▶ practice_lead_human (briefing)
        └─(competitor signals)──▶ competitor_signal_ledger (n8n→CRM) ──▶ audit

  competitor_signal_ingest / competitor_intel_query
        ▼
  competitor_signal_ledger (n8n→CRM) ──(ok)──▶ bd_audit_logger
```

## Actor inventory

| Agent | Role (job title) | Type |
|---|---|---|
| `opportunity_feed_agent` | Capture-tool scout | programmatic / n8n |
| `rfp_intake_agent` | Opportunity-intake specialist | llm (gpt-4o-mini) |
| `precedent_research_agent` | Precedent researcher | llm (gpt-4o-mini) |
| `section_drafter_agent` | Proposal drafter | llm (claude-sonnet-4-6) |
| `pricing_configurator_agent` | Pricing configurator | llm (gpt-4o-mini) |
| `contracts_review_agent` | Contracts reviewer | llm (claude-sonnet-4-6) |
| `bid_no_bid_decisioner_agent` | Bid/no-bid strategist | llm (gpt-4o-mini) |
| `competitive_intel_agent` | Competitive-intelligence analyst | llm (claude-sonnet-4-6) |
| `competitor_signal_ledger_agent` | Competitor-signal registrar | programmatic / n8n |
| `proposal_writer_human` | Proposal writer | human |
| `practice_lead_human` | Practice lead | human |
| `legal_human` | Legal counsel | human |
| `partner_human` | Partner | human |
| `bd_audit_logger_agent` | Audit registrar | external / custom |

## Data artifacts

- **RFP record** (`data_structures.RFP`): rfp_id, client_org,
  practice_area, due_date, budget_range_cents, compliance_required,
  received_at_utc.
- **Intake extraction**: requirements (must/should/may), deliverables,
  evaluation_criteria, pricing_constraints, key_dates,
  compliance_frameworks, completeness_score, extraction_complete.
- **Precedent set**: similar_proposals (each with engagement_id), matches
  (top-3 from the corpus), best_match_*, high_confidence_match.
- **Draft**: sections, cited_past_proposals.
- **Pricing**: pricing_breakdown, total_cents, within_band, discount_pct.
- **Contract review**: clearance, reasons, review (per-clause severity),
  severity_counts, counter_proposals, risk_score, requires_legal_review,
  requires_deal_desk_review.
- **Bid/no-bid**: five fit axes, overall_score, recommendation,
  win_themes, requires_partner_review.
- **Post-mortem**: decision, what_we_did_well/poorly,
  competitor_intelligence, learnings_for_library.
- **Audit entry**: audit_event_id, written_at_utc, payload,
  hash_chain_prev, hash_chain_current (`./logs/bd_audit.jsonl`).

## Per-agent spec (grounded in config)

- **opportunity_feed_agent** — n8n connector; `OPPORTUNITY_FEED_*` env.
  Yields discovered/high-fit counts + lists; routes on
  `requires_partner_review`. `wake_up` cron ships commented out until the
  connector is wired (a cron against an empty URL just errors).
- **rfp_intake_agent** — `rfp_templates` knowledge; enforce_yields(3).
  One role, two responsibilities (normalise + extract). Routes
  deal-breakers / incomplete extraction to the partner; clean packages to
  precedent research.
- **precedent_research_agent** — `proposals_library` knowledge (the DMS);
  citation-required (drops candidates without engagement_id). Hands to
  the section drafter.
- **section_drafter_agent** — `section_templates` knowledge; sonnet. Hands
  to pricing.
- **pricing_configurator_agent** — `rate_cards` knowledge + the
  `agency/pricing_configurator_agent.py` floor. `@pre_compose` pulls the
  rate card + budget bounds; `@chain` recomputes the total from line
  items and computes the approval-tier flags. Three mutually-exclusive
  routes fire on the **computed** flags: `requires_partner_signoff` (>$1M)
  → partner, `requires_practice_lead_signoff` (>20% discount) → practice
  lead, else → contracts review.
- **contracts_review_agent** — `contract_playbook` knowledge; sonnet.
  Mode-dispatched (regulatory / playbook). Hard legal gate on any
  unacceptable clause or blocked clearance; deal-desk gate to practice
  lead; clean regulatory packages to the proposal writer; clean playbook
  reviews to audit.
- **bid_no_bid_decisioner_agent** — `rfp_decision_playbook` knowledge.
  Five-axis weighted score; never silently no-bids. Routes low-confidence
  to the partner, a "bid" verdict to the section drafter.
- **competitive_intel_agent** — `win_loss_archive` knowledge; sonnet.
  Briefs the practice lead; auto-forwards surfaced competitor signals to
  the ledger.
- **competitor_signal_ledger_agent** — n8n connector; `CRM_SIGNAL_*` env.
  Ingest / query modes against the CRM; writes to audit on success.
- **Human gates** — default-deny, fail-up chain: writer (2h) → practice
  lead (4h) → partner (8h); legal (6h) holds for review. No
  `operator_ids` set → tasks route to the shared inbox.
- **bd_audit_logger_agent** — custom external; hash-chained WORM sink
  registered via `mesh.intelligence()` in main.py; terminal.

## Entry points

`rfp_email`, `rfp_portal_upload`, `partner_referral`, `manual_action` →
intake. `competitor_signal_ingest` / `competitor_intel_query` → ledger.
`bid_no_bid_review` → decisioner. `decision_received` /
`competitor_takeaway` / `quarterly_win_rate_review` → competitive intel.
`rfp_scout_daily` / `rfp_scout_manual` → opportunity feed. Plus
direct-call entries for ad-hoc invocation of the drafting-chain agents and
`contract_playbook_review` / `direct_call_rfp_extraction`.

## Controls & trust

- **Human gates default-deny on timeout**, escalating up the chain (writer
  → practice lead → partner; legal → hold).
- **Hard legal gate by construction**: an unacceptable clause or blocked
  clearance forces `legal_human` via a `can_call` edge — not a prompt
  suggestion.
- **Out-of-band pricing never advances unreviewed**: >$1M and >20%
  discount route to human sign-off via mutually-exclusive edges.
- **No silent no-bid**: the decisioner forces partner review on weak/low
  signals.
- **WORM audit on every terminus**: hash-chained so any insertion or
  deletion is detectable post-hoc.
- **Manager escalation** (learning router, fallback all) to human +
  webhook (PagerDuty) + slack channel.

## Configuration pointer

See **README.md → Configuration** for the three-tier env breakdown
(boot / host-adapters / connectors). Most wiring lives in
`configs/config.yaml`; the Python is the four floor modules under
`agency/` (auto-discovered) plus `agency/_shared/` (audit sink, dev
store, session stash).

## Deterministic floors (the depth)

Four judgment-heavy roles carry a Python module (`agency/<name>_agent.py`,
auto-discovered by name) that pulls real context with `@pre_compose` and
enforces a control the LLM can't waive with a `@chain`. The prompt still
asks for good judgment; the chain guarantees the floor.

| Module | `@pre_compose` pulls | `@chain` floor (LLM can't waive) | `@compose` |
|---|---|---|---|
| `pricing_configurator_agent` | practice-area rate card + RFP budget bounds (store) | **recomputes `total_cents` from line items**, recomputes `within_band`, computes the **approval tiers** (`requires_partner_signoff` >$1M, `requires_practice_lead_signoff` >20% discount) — the `can_call` edges route on these computed flags | approver gate gets a focused brief; contracts review gets the full package |
| `bid_no_bid_decisioner_agent` | practice-area win/loss history + RFP (store) | **recomputes weighted `overall_score`**, recomputes `recommendation` from firm thresholds, **forces `requires_partner_review`** on no_bid / low confidence / weak score (no silent no-bid) | — |
| `rfp_intake_agent` | captured opportunity record — its compliance must-haves + budget (store) | **recomputes `completeness_score`** from the exact rubric, derives `extraction_complete`, **unions the captured compliance must-haves** into `compliance_required` (a compliance obligation is never silently dropped) | — |
| `precedent_research_agent` | practice-area precedents from the proposal corpus (store) | **drops any candidate without an `engagement_id`** (citation floor — no hallucinated proposals reach the drafter), recomputes `best_match_*` / corpus size / `high_confidence_match` from the surviving matches | — |

Plus the WORM audit sink (`agency/_shared/audit_logger.py`), the dev
store (`agency/_shared/store.py`, seeded so the chain runs day 0), and a
bounded-loop scratch (`agency/_shared/session_stash.py`).

## Reflection & decisions

- **Floors in code, judgment in prompts.** The controls a partner would
  never let an LLM waive — pricing approval tiers, bid/no-bid criteria,
  compliance must-haves, precedent citation — are recomputed/enforced in
  `@chain` steps, not merely requested in a prompt. Everything else
  (clause stances, must/should/may classification, narrative drafting)
  stays prompt-driven judgment.
- **Self-reliant agents.** The four floor roles pull their own context
  with `@pre_compose` (the rate card, the win/loss record, the captured
  opportunity, the proposal corpus) instead of being spoon-fed.
- **State stays in the customer's systems.** The watchlist + dedup live in
  the capture tool; the proposal corpus in the DMS (`proposals_library`
  knowledge group); competitor intel in the CRM. The template's
  `agency/_shared/store.py` is a **dev stub** — seeded so the demo runs
  with no connectors, with every function documented as the contract a
  connector/RAG call replaces in production. No template SQLite ledger.
- **Connectors degrade gracefully.** The two n8n agents lenient-fill empty
  results and their crons stay commented until the customer wires a real
  URL, so the mesh boots and runs before any external system exists.
- **Pricing routing enforced by a code floor.** The approval routes are
  mutually-exclusive `can_call` edges that fire on the **deterministically
  computed** `requires_partner_signoff` / `requires_practice_lead_signoff`
  flags — the `@chain` recomputes the total from the line items first, so
  an LLM cannot under-report a total to dodge a sign-off tier.
- **Audit path owned in code.** The SDK 2.4+ intelligence path receives no
  `connector_config`, so the sink file location is fixed in the module
  (`./logs/bd_audit.jsonl`) to match the config's declared path.
- **HITL via the shared inbox.** No placeholder `operator_ids` — dummy
  emails would make tasks invisible.

### Open items for a live smoke test

- Whether the slack channel escalation target actually posts with
  `SLACK_BOT_TOKEN` + `SLACK_BD_CHANNEL` (SDK-provider behaviour, not
  introspectable from config).
- End-to-end behaviour of the n8n connectors once real webhook URLs are
  wired (shape of returned notices / signals).

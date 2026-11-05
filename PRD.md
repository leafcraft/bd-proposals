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
  capture tool   │  opportunity_feed  (copies.count: 2, each claims a   │
  (GovWin/SAM) ─▶│    disjoint batch; live daily cron, America/NY)      │
                 │    high-fit ─▶ partner_human                         │
                 │    else      ─▶ bd_audit_logger                      │
                 └─────────────────────────────────────────────────────┘

  email / portal / referral / manual / pursuit_status
        │
        ▼
  bd_coordinator ──(open_pursuit)──▶ rfp_intake
        ├─(escalate)──▶ partner_human
        └─(status)────▶ bd_audit_logger
        │
        ▼
  rfp_intake ──(deal-breaker OR extraction incomplete)──▶ partner_human
        │
        └──(clean & complete)──▶ precedent_research ──▶ section_drafter ──▶ pricing
                                       (super-agent: plan→draft→verify;         │
                                        playbook + tools)                       │
        bid_no_bid (entry: bid_no_bid_review)                                   │
          ├─(requires_partner_review)──▶ partner_human                         │
          └─(bid)────────────────────▶ section_drafter                         │
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

  practice_lead ─(reprice, BOUNDED)─▶ pricing_configurator   # laps counted →
                                       # exhaustion forces a terminal partner sign-off
  proposal_writer ─(approved, not held)─▶ proposal_assembler (FINISHER)
        proposal_assembler ─▶ renders ./out/<rfp>.{pdf,md} ─▶ bd_audit_logger
                            └─(unapproved / flagged)─▶ delete partial, status=assembly_blocked

  nothing advances on silence: an unanswered gate closes its Inbox card and
        the ticket records that no reply came (nobody is chased)
  practice_lead / partner ─(approve, on a priced quote)─▶ contracts_review
  practice_lead / legal / partner, anything else ──▶ bd_audit_logger (WORM)
  the Manager escalates unfixable / repeated agent errors ──▶ partner_human

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
| `bd_coordinator_agent` | Pursuit Coordinator | llm (gpt-4o-mini, pure YAML) |
| `opportunity_feed_agent` | Capture-tool scout | programmatic (fan-out `scaling.copies.count: 2`) |
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
| `proposal_assembler_agent` | Proposal assembler (finisher) | programmatic |
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

- **bd_coordinator_agent** — Pursuit Coordinator (pure YAML). The pod's
  single point of contact: the four inbound-RFP entry points + a
  `pursuit_status` entry land here. Opens the pursuit (`open_pursuit` →
  `rfp_intake`), answers status asks, and routes explicit escalations to
  the partner. Never scores/drafts/prices/reviews itself.
- **opportunity_feed_agent** — backed by
  `agency/opportunity_feed_agent.py`. **Fan-out**: `scaling.copies.count: 2` +
  `scaling.copies.handoff: last` — one sweep runs as 2 parallel copies, each
  claiming a DISJOINT batch via `store.claim_opportunities` (an atomic
  claim; swap for Redis `LPOP count` in prod). A **live** daily cron
  (`wake_up: "0 6 * * *"`, `timezone: "America/New_York"`) sweeps day-0
  against the seeded discovery queue; the n8n connector is wired with the
  vault connection `opportunity_feed_n8n` (commented `integration` /
  `connector_config` lines); it announces `available:false`
  when the queue is empty and no connector is wired — never a synthetic "0 new".
  Routes on `requires_partner_review`.
- **rfp_intake_agent** — `rfp_templates` knowledge; enforce_yields(3).
  One role, two responsibilities (normalise + extract). Routes
  deal-breakers / incomplete extraction to the partner; clean packages to
  precedent research.
- **precedent_research_agent** — `proposals_library` knowledge (the DMS);
  citation-required (drops candidates without engagement_id). Hands to
  the section drafter.
- **section_drafter_agent** — `section_templates` knowledge; sonnet
  **super-agent** (`super_agent: {cost_ceiling: 120000, wall_clock: 900}` —
  plan → draft → verify, bounded by its own cost/wall-clock). Carries a
  **`draft_sections` playbook** (only `description` in the prompt;
  `responsibility` loaded on demand) and day-0 **tools**
  (`read_reusable_sections`, `read_boilerplate` from `agency/tools.py`,
  self-announcing) with a commented DMS `mcp` block for prod.
  `max_tool_calls_per_message: 15`. Hands to pricing.
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
- **bid_no_bid_decisioner_agent** — `rfp_decision_playbook` knowledge + a
  **`win_themes` playbook** (on-demand craft for building the 3-5 win
  narratives from the firm's track record). Five-axis weighted score;
  never silently no-bids. Routes low-confidence to the partner, a "bid"
  verdict to the section drafter.
- **competitive_intel_agent** — `win_loss_archive` knowledge; sonnet.
  Briefs the practice lead; auto-forwards surfaced competitor signals to
  the ledger.
- **competitor_signal_ledger_agent** — n8n connector; vault connection `crm_signal_n8n` (named on the agent; day 0 the record does not exist, so the agent is switched off with a notice until it does).
  Ingest / query modes against the CRM; writes to audit on success.
- **Human gates** — nothing advances on silence. Timeouts: writer 2h,
  practice lead 4h, legal 6h, partner 8h; when one runs out the Inbox card
  closes and the ticket records that no reply came — nobody is chased
  automatically. The declared `fallback_response` (`held_for_review` →
  audit) is kept; on SDK 2.4.486 a dual seat does not route it. A partner
  or practice-lead `approve` on a priced quote continues to contracts review
  (the rfp_id is recovered for the session from the dev store); every other
  reply is recorded. There are no human→human `can_call` wires (a `dual→dual` footgun the SDK
  warns on). The practice lead can send a quote back to pricing (`reprice`)
  — a **bounded** back-edge (see below). No `operator_ids` set → tasks
  route to the shared inbox.
- **proposal_assembler_agent** — the artifact-producing **finisher**
  (`agency/proposal_assembler_agent.py`), wired AFTER the writer's
  approval. Re-checks the approval token (an allow-token allowlist + a
  block-token denylist; an unknown verdict FAILS CLOSED), enforces the
  compliance/pricing invariants a human can't waive, and renders the real
  document to `./out/<rfp>.pdf` (ReportLab) or `.md` (deterministic
  fallback). On a tripped floor it DELETES the partial artifact and returns
  `status: assembly_blocked`. Recovers the approved package across the HITL
  boundary (upstream → session stash → Redis → dev store). Terminus →
  audit.
- **bd_audit_logger_agent** — custom external; hash-chained WORM sink
  registered via `mesh.intelligence()` in main.py; terminal.

## Entry points

`rfp_email`, `rfp_portal_upload`, `partner_referral`, `manual_action`,
`pursuit_status` → the coordinator (`bd_coordinator_agent`).
`competitor_signal_ingest` / `competitor_intel_query` → ledger.
`bid_no_bid_review` → decisioner. `decision_received` /
`competitor_takeaway` / `quarterly_win_rate_review` → competitive intel.
`rfp_scout_daily` / `rfp_scout_manual` → opportunity feed. Plus
direct-call entries for ad-hoc invocation of the drafting-chain agents and
`contract_playbook_review` / `direct_call_rfp_extraction`.

## Controls & trust

- **Silence never advances a pursuit**: an unanswered gate closes its Inbox
  card and the ticket records that no reply came; nobody is chased
  automatically. The Manager escalates only agent errors (unfixable, or 3
  failed agents in one session) to the partner; no human→human wires (no
  `dual→dual` ping-pong).
- **The finisher fails closed**: the proposal assembler re-checks the
  approval token (allow/deny lists, unknown ⇒ blocked), enforces
  compliance/pricing invariants, and DELETES a partial artifact on a
  tripped floor — a binding document is never left on disk for an
  unapproved/flagged proposal.
- **Bounded back-edge (Rule 3)**: the `practice_lead → pricing` reprice
  loop counts its laps in the session; on exhaustion the pricing floor
  forces a terminal partner sign-off — never an unbounded price↔review
  ping-pong.
- **Hard legal gate by construction**: an unacceptable clause or blocked
  clearance forces `legal_human` via a `can_call` edge — not a prompt
  suggestion.
- **Out-of-band pricing never advances unreviewed**: >$1M and >20%
  discount route to human sign-off via mutually-exclusive edges.
- **No silent no-bid**: the decisioner forces partner review on weak/low
  signals.
- **Stubs announce themselves**: `opportunity_feed` + the drafter's tools
  return `available:false` when there is no real source — never a synthetic
  success.
- **WORM audit on every terminus**: hash-chained so any insertion or
  deletion is detectable post-hoc.
- **Manager escalation** (learning router, fallback all) to the partner's
  Inbox; the Slack channel target (needs a Slack adapter on a human seat)
  and a webhook (PagerDuty) target ship commented — create vault
  connection `escalation_webhook`, then uncomment it (in `configs/config.yaml`
  before the first start, in Studio's YAML editor after it — no restart).

## Configuration pointer

See **README.md → Configuration** for the three-tier env breakdown
(boot / host-adapters / connectors). Most wiring lives in
`configs/config.yaml`; the Python is the deterministic-floor modules +
`proposal_assembler_agent.py` (finisher) + `opportunity_feed_agent.py`
(fan-out claim) + `tools.py` (the drafter's day-0 tool surface), all
auto-discovered, plus `agency/_shared/` (audit sink, dev store, session
stash). `main.py` imports `agency.tools` before `from_yaml` so the
`@global_tool`s register.

## Modern SDK capabilities (2.4.131), fitted to the domain

| Capability | Where | Why here |
|---|---|---|
| **super_agent** (dict form) | `section_drafter_agent` | Drafting a full proposal is autonomous plan → draft → verify across many sections; bounded by `cost_ceiling` + `wall_clock` (its own bounded loop) |
| **playbook** (on-demand) | `section_drafter` (`draft_sections`), `bid_no_bid` (`win_themes`) | The craft lives behind a `load_skill_reference` call — only the `description` rides in the prompt, so the prompt stays identity+contract and the how-to doesn't compete with it |
| **scaling.copies + atomic claim** | `opportunity_feed_agent` | A morning's discovery queue is a backlog; 2 parallel copies each claim a disjoint slice (`store.claim_opportunities`) so nothing is double-processed |
| **timezone** | `opportunity_feed_agent` | The live daily sweep cron fires at 06:00 `America/New_York`, not UTC (a bare cron would fire at 01:00 local) |
| **tools + commented mcp** | `section_drafter_agent` | Day-0 dev-store tools (`agency/tools.py`, self-announcing) pull reusable prose/boilerplate; the DMS `mcp` block ships commented — it picks the vault connection `dms_mcp` (Infrastructure → Integrations → MCP; a URL/token inline is refused at load) |
| **finisher** | `proposal_assembler_agent` | Approve-token re-check (fail closed) → invariants → render `./out` → delete-on-block → dev-store recovery |

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

The `pricing_configurator_agent` floor also enforces the **bounded
back-edge**: it counts `practice_lead → pricing` reprice laps in
`session_stash` and, once `_MAX_REPRICE_LAPS` is hit, forces a terminal
partner sign-off.

Plus the artifact-producing **finisher** (`proposal_assembler_agent.py`),
the **fan-out** claim (`opportunity_feed_agent.py`), the drafter's day-0
**tools** (`tools.py`), the WORM audit sink
(`agency/_shared/audit_logger.py`), the dev store
(`agency/_shared/store.py`, seeded — precedents, rate cards, win/loss,
reusable content, and a discovery queue — so the whole pod runs day 0), and
the bounded-loop scratch (`agency/_shared/session_stash.py`).

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
- **Connectors degrade gracefully — and announce it.** The opportunity
  feed runs its live cron day-0 against the seeded discovery queue and
  returns `available:false` (never a fake "0 new") once it is drained with
  no URL wired; the competitor ledger stays inert until its URL is set. A
  stub never fakes a synthetic success.
- **A pod, not a pipeline.** The pursuit coordinator owns each case; the
  specialists research/draft/price/review; the finisher renders the real
  document; the human members decide on every irreversible gate; the
  Manager supervises. One human, one agent, one system per stage — agents
  produce, humans decide, systems record.
- **Modern capabilities fitted to the work, not bolted on.** The drafter is
  a super-agent because drafting is genuinely plan→execute→verify; the feed
  fans out because a discovery queue is a backlog; the playbooks hold craft
  the prompt shouldn't carry; the cron carries a timezone because a BD team
  works in local hours. See the *Modern SDK capabilities* table above.
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

- The Slack channel escalation target (shipped commented) once Slack is
  connected on `partner_human`'s `channels:` block and `SLACK_BD_CHANNEL`
  is set.
- End-to-end behaviour of the n8n connectors once their vault connections
  are created (shape of returned notices / signals).

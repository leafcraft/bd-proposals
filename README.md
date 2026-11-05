# bd-proposals — BD Proposals

A complete RFP-response **pod** (SDK 2.4.131): a **coordinator** who owns
each pursuit, **specialists** who research/draft/price/review, a
**finisher** that renders the real proposal document, **human members** on
every irreversible gate, and the **LeafMesh Manager** supervising. It takes
a request for proposal from arrival to a signed-off, compliance-checked,
priced, *rendered* deliverable — and learns from every win and loss.

The judgment-heavy roles carry a Python floor — a deterministic `@chain`
the LLM can't waive plus a `@pre_compose` that pulls real context — so
pricing approval tiers, bid/no-bid criteria, compliance must-haves, and
precedent citation are enforced by construction, not hoped for in a prompt.
The pod also fits the modern SDK capabilities to the work: the section
drafter is a **super-agent** (plan → draft → verify) with a **playbook**
(loaded on demand) and day-0 **tools**; the opportunity feed **fans out**
across parallel copies (`scaling.copies`) with an atomic claim; the daily sweep cron
carries a **timezone**. A seeded dev store + self-announcing tools let the
whole pod run on day 0 with no connectors wired.

**The discipline, in one line: agents produce, humans decide, systems
record — and silence never advances anything** (if nobody answers a gate
in time, its Inbox card closes and the ticket records that no reply came;
nothing is approved or sent, and nobody is chased automatically).

## Story

Priya runs business development at a mid-size services firm. Her firm's
GovWin and SAM.gov saved searches surface new federal RFPs, and the
**opportunity feed** pulls them in pre-deduplicated and fit-scored — running
as two parallel copies that each claim a disjoint slice of the morning's
notices. Because one find's fit is high, it goes straight to Priya as
**partner** for triage; she opens a pursuit for it (the `manual_action`
entry point), and the **pursuit coordinator** opens the case and hands it to
intake.

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
final polish and approval. On approval the **proposal assembler** (the
finisher) re-checks the approval token, enforces the compliance/pricing
invariants, and renders the real proposal document to `./out` — deleting
any partial file if a check trips. Every hop is appended to a hash-chained
WORM audit.

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
- Webhook escalation (PagerDuty or any incident webhook) for hard
  escalations — no env var: create vault connection `escalation_webhook`
  (an "Add custom" record on the Infrastructure page, service type
  'Outbound webhook'), then uncomment the webhook target (in
  `configs/config.yaml` before the first start, in Studio's YAML editor after
  it).
- Slack escalation — ships **commented** (day 0 the partner gets every
  escalation in the Inbox). Connect Slack on Infrastructure → Messaging →
  Slack (bot token and signing secret live only in that vault record), give
  `partner_human` `channels: {slack: {connection: <name>}}`, set
  `SLACK_BD_CHANNEL` in `.env`, then uncomment the channel target (in
  `configs/config.yaml` before the first start, in Studio's YAML editor
  after it). Without a Slack adapter the target cannot deliver anything.

**Tier 3 — Connectors (optional; wire to your systems).** The pod runs
day-0 without these: `opportunity_feed_agent` claims from the seeded
discovery queue (and announces `available:false` when it is drained and no
connector is wired — never a fake "0 new"); `section_drafter_agent`'s tools
read the seeded reusable-content store; the competitor ledger is inert until
wired. Addresses and tokens live **only in the vault**: create each
connection (Infrastructure → Integrations → n8n / MCP), then uncomment its block —
in `configs/config.yaml` before the first start, in Studio's YAML editor after
it (see *Changing the configuration after the first start*). A URL or token
written in the config is refused at load.
- Vault connection `opportunity_feed_n8n` (Infrastructure → Integrations → n8n, or an "Add custom"
  record with service type Tools: base URL = the workflow's webhook URL,
  secret = its auth token) — the n8n workflow that queries your GovWin /
  SAM.gov / FedConnect saved searches. Uncomment the
  `integration`/`connector_config` lines on `opportunity_feed_agent`. The
  `wake_up: "0 6 * * *"` cron (timezone `America/New_York`) is **live** — it
  sweeps the seed day-0. The feed counts as wired as soon as the vault
  record `opportunity_feed_n8n` exists — nothing in `.env`.
- Vault connection `dms_mcp` (the DMS MCP server's URL + token) — your DMS /
  proposal corpus. Then **uncomment** the `mcp` block on
  `section_drafter_agent`.
- Vault connection `crm_signal_n8n` (same shape as above) — the n8n
  workflow against your CRM / intel store (Salesforce, HubSpot, Klue,
  Crayon, Notion) for the competitor-signal ledger (ingest / query). Then
  uncomment the `connector_config` lines on `competitor_signal_ledger_agent`.

```bash
cp env .env && pip install -r requirements.txt && python main.py
```

## Run it (day 0, no connectors)

The dev store (`agency/_shared/store.py`) ships seeded with sample
opportunities (`RFP-2026-08813`, `RFP-2026-09140`), three proposal precedents, a rate card,
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
a `FedRAMP` compliance must-have (unioned in by the intake floor), a
$700k–$1.1M budget band (the pricing floor's in-band check), and a draft
contract with uncapped liability, so contracts review sends it to legal.
`RFP-2026-09140` (Riverbend County Public Works, $400k–$600k, standard
contract) is the clean pursuit: it reaches the proposal writer. The seeded
approved package for `RFP-2026-08813` prices 250 days at the rate card
($920,000, 6% discount — inside the band and under both sign-off tiers).

## Agents

| Agent | Role (human job title) | Responsibilities | Can perform |
|---|---|---|---|
| `bd_coordinator_agent` | Pursuit Coordinator | Owns each RFP pursuit end to end; opens the case, orchestrates the pod, keeps live status, is BD's single point of contact | LLM (pure YAML); opens the pursuit → intake, routes escalations to the partner; **never scores, drafts, prices, or reviews itself** |
| `opportunity_feed_agent` | Capture-tool scout | Pulls new, pre-deduplicated, fit-scored RFP notices from the firm's GovWin / SAM.gov / FedConnect saved searches | Programmatic; **fans out across 2 parallel copies** (`scaling.copies.count: 2`), each claiming a disjoint batch (atomic claim); **live daily cron** (`America/New_York`); dev-store fallback that announces `available:false`; routes high-fit finds to the partner, else the audit log |
| `rfp_intake_agent` | Opportunity-intake specialist | Normalises an inbound RFP (client, practice area, due date, budget) AND extracts structured requirements from attachments with must/should/may classification + completeness scoring | `gpt-4o-mini` over `rfp_templates` knowledge; routes deal-breakers / incomplete extraction to the partner, clean packages to precedent research |
| `precedent_research_agent` | Precedent researcher | Retrieves similar prior wins and the top proposal-library matches as RAG context for drafting; never invents proposals retrieval didn't return | `gpt-4o-mini` over `proposals_library` (the firm's DMS); hands the corpus to the section drafter |
| `section_drafter_agent` | Proposal drafter | Plans and writes each required section (exec summary, approach, team bios, timeline, case studies) citing past proposals | `claude-sonnet-4-6` **super-agent** (plan → draft → verify, bounded by cost/wall-clock) + **`draft_sections` playbook** (on-demand craft) + day-0 **tools** (reusable prose / boilerplate) + commented DMS `mcp`; hands the draft to pricing |
| `pricing_configurator_agent` | Pricing configurator | Builds line-item pricing against the rate card; a `@chain` floor recomputes the total from the line items and computes the approval tiers (the LLM can't dodge a sign-off) | `gpt-4o-mini` over `rate_cards` + `@pre_compose`/`@chain` floor; routes on the computed flags: >$1M → partner, >20% discount → practice lead, else → contracts review |
| `contracts_review_agent` | Contracts reviewer | Regulatory/legal fit review of the package (regulatory mode) AND clause-by-clause playbook review of a draft contract (playbook mode) | `claude-sonnet-4-6` over `contract_playbook`; hard legal gate on any unacceptable clause / blocked clearance, deal-desk gate to practice lead, clean packages to the proposal writer |
| `bid_no_bid_decisioner_agent` | Bid/no-bid strategist | Scores RFP fit on five axes → bid / qualify further / no-bid; never silently no-bids on a weak signal | `gpt-4o-mini` over `rfp_decision_playbook` + a **`win_themes` playbook** (on-demand craft) + `@chain` decision floor; routes low-confidence to the partner, a "bid" verdict to the section drafter |
| `competitive_intel_agent` | Competitive-intelligence analyst | Runs win/loss post-mortems and quarterly reviews; surfaces competitor signals and learnings | `claude-sonnet-4-6` over `win_loss_archive`; briefs the practice lead, auto-forwards surfaced signals to the CRM ledger |
| `competitor_signal_ledger_agent` | Competitor-signal registrar | Ingests one competitor signal into / queries signals from the firm's CRM intel store (ingest / query modes) | n8n connector against the CRM; writes the result to the audit log on success |
| `proposal_writer_human` | Proposal writer | Final polish and approve/send of the proposal | Human gate (2 h; nothing is sent on silence); an approval routes to the assembler (finisher), which re-checks it |
| `practice_lead_human` | Practice lead | Discount sign-off (> 20%) and contracts needing review | Human gate (4 h); `approve` on a quote → contracts review; `reprice` → pricing (a **bounded** back-edge, 2 laps then the partner); anything else → audit |
| `legal_human` | Legal counsel | Compliance / IP / regulator review on any hard-gated package | Human gate (6 h); the decision is recorded → audit (a fixed package is re-run from contracts review) |
| `partner_human` | Partner | Sign-off on quotes over $1,000,000, deal-breakers, high-fit finds, bid/no-bid calls | Human gate (8 h); `approve` on a quote → contracts review; anything else → audit; also the Manager's escalation target |
| `proposal_assembler_agent` | Proposal assembler (the finisher) | Renders the APPROVED package into a real document at `./out` | Programmatic **finisher**: approve-token re-check (allow/deny lists, fail closed) → compliance/pricing invariants → render PDF/Markdown → **delete-on-block** → dev-store recovery across the HITL boundary; terminus → audit |
| `bd_audit_logger_agent` | Audit registrar | Appends every terminal hop to a hash-chained, append-only (WORM) audit trail | Custom external sink → `./logs/bd_audit.jsonl` (swap for S3 Object Lock / Splunk / Datadog in prod); terminal |

The **LeafMesh Manager** supervises. It escalates to the partner
(`manager.escalation`) when an agent hits an error a retry cannot fix (auth,
bad request, credit, bad config), when 3 different agents fail in one
session, or when restarts run out. A hand-off that misses its contract
raises an alert, not an escalation. It does **not** chase an unanswered
gate: if nobody answers in time (writer 2 h, practice lead 4 h, legal 6 h,
partner 8 h), the Inbox card closes and the ticket records that no reply
came — nothing advances.

See **PRD.md** for the flow diagram, per-agent specs, data artifacts, and
design decisions.

## Changing the configuration after the first start

`configs/config.yaml` is only the first-start seed. On the first start (an empty store) the agency imports it as version 1 and from then on keeps its configuration in the store. After that the file is not read again: an edit to it is **not** applied, even after a restart (the boot log says "that edit was NOT applied").

To change a running agency:

- **Studio** — its settings pages, or the raw YAML editor.
- **API** — `PUT /api/yaml/raw` with an `X-API-Key` header and the body `{"yaml_content": "<the whole YAML>", "save_to_disk": true}`, or `PATCH /api/yaml/config` with `{"updates": {...}, "save_to_disk": true}`.

Each save is a new version and applies live on every pod — no restart. (A few settings, such as brokers, make the agency reload itself in place within seconds.) So wherever this README or a comment says "uncomment X in `configs/config.yaml`", do it in the file before the first start, or in Studio's YAML editor after it.

## Changing a running project (Docker)

What reaches a project that is already running (leafmesh 2.4.497). The
image holds the Python code and the first-start `configs/config.yaml`;
`.env` is passed in when the container is created; the store (Redis) keeps
its data on its own volume.

| You change | When it applies |
|---|---|
| An agent in Studio (prompt, model, tools, routes, human seats, schedules, …) | At once, no restart |
| A human seat's `channels` (Slack, email, …) | The agency reloads itself in place within seconds |
| Add or delete an agent in Studio | At once, including routes and schedules |
| A connection in the vault (model keys, MCP, webhooks, connectors, Slack, email) | At once. An agent switched off for a missing connection or address switches back on by itself |
| Anything in `.env` (licence, agency name, store, ports) | After `docker compose up -d` (the container is recreated) |
| Python code (`agency/*.py`: programmatic agents, tools, `@pre_compose`) | After a rebuild: `docker compose up -d --build` |
| `configs/config.yaml` | Never after the first start. It is read only when the store is empty |
| Several app containers on one store | A Studio save reaches every one within about 15 seconds |

- Keep model keys in the vault. A key there wins over the same key in
  `.env` (the log warns), and a change applies at once. From 2.4.497 that
  holds for every value the vault holds (endpoints, organisation / project
  ids, cloud identities); the `.env` value returns when the record goes.
- Code the image does not have: an agent marked pure Python
  (`integration: python`) is switched off until its function is in the image;
  any other programmatic agent stays on, and each call to code it does not
  have fails. Rebuild the image with the code first.
- A new Redis volume is an empty store, so `configs/config.yaml` is imported
  again as version 1.
- **If the agency refuses to start after an upgrade** (a new leafmesh pin,
  then a rebuild: "Configuration has N error(s) in the stored
  configuration"), repair the stored configuration with the agency stopped:

  ```bash
  docker compose run --rm bd-proposals leafmesh config check      # each problem, with its line
  docker compose run --rm bd-proposals leafmesh config versions   # kept versions: which pass, which is in use
  docker compose run --rm bd-proposals leafmesh config rollback   # back to the newest version that passes (saved as a new version)
  ```

  Or `leafmesh config export > config.yaml`, fix it by hand, then
  `leafmesh config import config.yaml` (it is checked before it is saved).

## Where the data store is set

From leafmesh 2.4.482 the store (Redis or Postgres) is set **only in `.env`** — never in `configs/config.yaml`. A `persistence:` block in the YAML is ignored with a warning on leafmesh 2.4.482–2.4.485; from 2.4.486 the agency refuses to start if that block differs from `.env`, and names each `.env` line to add. The project's `.env` sets the store explicitly (`LEAFMESH_STORE`, `LEAFMESH_AGENCY_NAME`, `REDIS_*`).

- Redis (default): `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`; optional `REDIS_DEFAULT_TTL`, `REDIS_SESSION_TTL`, `REDIS_SSL*`, `REDIS_CLUSTER_NODES`.
- Postgres instead: `LEAFMESH_STORE=postgres` plus `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (optional `POSTGRES_SSLMODE`).
- Or the whole server in one value: `REDIS_URL=redis://user:pw@host:6379/0` (`rediss://` turns TLS on) or `DATABASE_URL=postgresql://user:pw@host:5432/db`. The single names fill in what the URL leaves out.
- With Docker Compose the app reaches Redis as `redis` (the service name); compose sets that for you.
- Check it in Studio → **Infrastructure → Datastores**: it shows whether the store is reachable (never the address or password).

## This mesh's sign-in (leafmesh 2.4.497)

From leafmesh 2.4.497 each mesh signs in to LeafCraft with its own key, not
a key shared by every install.

- **First start.** The mesh makes a key pair and registers it with
  `LEAFMESH_LICENSE_KEY` and `LEAFMESH_ENV_TOKEN` from `.env` (copy the
  environment token from Studio — a placeholder such as `development` is
  refused). With both valid it works at once. If your organisation turned on
  "require approval", the first start stops and says so: approve it in
  Studio → **Keys → SDK access**, then start again. Organisation admins get an
  email for every new registration.
- **Where the key lives.** In the vault, in the store, encrypted with
  `LEAFMESH_VAULT_KEY`: it survives rebuilds and every copy of the app shares
  it. A new Redis volume, or a new vault key, makes a new key pair that
  registers again — revoke the old one in Studio.
- **Check or change it** (in Docker: `docker compose run --rm bd-proposals leafmesh auth status`):
  - `leafmesh auth status` — credential id, key fingerprint, registration and
    mode, never a key; `--check` signs in now and reports the tokens.
  - `leafmesh auth register` — register now.
  - `leafmesh auth rotate` — a new key pair: once it is active the mesh
    switches to it and revokes the old one. A revoked or expired key is never
    revived; rotate instead.
- **Lost the environment token?** From 5 Dec 2026 Studio shows the licence
  key and environment token only once, when they are made (then only a hint).
  Rotate the environment token in Studio and put the new one in `.env`.
  Rotating it changes where the agency's data is kept in the store, so do it
  before the agency holds data.
- **An existing project whose `.env` says `LEAFMESH_ENV_TOKEN=development`.**
  2.4.497 needs the real token. The token also names where the agency's data
  sits in the store, so with the real token the agency starts on an empty
  store (vault, sessions, board) — the old data stays under the old name. Set
  the real token before you put data in the agency, or contact us to move it.

## Your vault key — back it up

`create-leafmesh` put a `LEAFMESH_VAULT_KEY` in your `.env` when it made this project. It is the master key that encrypts every connection and credential you store in the vault (in Redis / Postgres).

- **Back it up like a master password.** Lose it and every stored connection has to be entered again.
- **Never change or regenerate it** for an existing project — a new key locks the existing vault. To change it, use `leafmesh vault rotate-key`.
- Every copy of the app (every replica) must get the **same** value. Docker Compose passes it in from `.env` as an environment variable.
- Never commit `.env` (it is already in `.gitignore`).

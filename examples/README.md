# bd-proposals — example scenarios

Four realistic scenarios that exercise the major paths through this mesh.

## How to run

```bash
python examples/run_examples.py                 # all scenarios
python examples/run_examples.py 01_             # one scenario (substring match)
```

## Scenario map

- **01_new_rfp_received** — `manual_action` — RFP arrives from a regional government — rfp_intake extracts key requirements, precedent_research finds 2 similar prior wins.
- **02_win_post_mortem** — `decision_received` — Won the deal — competitive_intel produces a structured retro: what worked, what almost lost it, who internally championed.
- **03_loss_with_competitor** — `competitor_takeaway` — Lost to a known competitor — focused analysis on price, scope, and timing trade-offs.
- **04_quarterly_win_rate** — `quarterly_win_rate_review` — Cadence — aggregate win/loss across the quarter for sales-leadership review.

## Audit trail

Every scenario appends one hash-chained entry to the template's
`logs/<audit>.jsonl` file. Tail it during a run to see the
ledger build up across scenarios.

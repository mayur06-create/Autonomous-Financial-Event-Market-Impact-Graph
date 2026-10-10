# PS5 Market Impact Graph - Project Plan

## Status
- [x] Phase 0: schema locked, 3 demo events + test oracle, KB 38 nodes / 56 edges
- [ ] Phase 1: real-LLM extraction tested (needs ANTHROPIC_API_KEY)
- [ ] Phase 2: engine verified on real LLM output
- [ ] Phase 3: yfinance correlations verified (check Yahoo tickers)
- [ ] Phase 4: UI polish
- [ ] Phase 5: hardening + backup demo video
- [ ] Phase 6: slides + rehearsal

## Locked schema
Node: id, type (Company|Sector|Commodity|Indicator|Index|Currency), ticker?
Edge: source, target, sign (+1/-1), confidence (0-1), evidence_type (observed|knowledge|inferred),
      reason, evidence_text, correlation?, counter_evidence

## Confidence formula
knowledge = rule strength x 1.0 | observed = 0.9 x 0.95 | inferred = llm_conf x 0.5
time-series: correlation agrees -> +0.1*|corr| (cap 1.0); disagrees (|corr|>0.15) -> x(1-0.3*|corr|) + counter_evidence flag
path confidence = product of edge confidences; impact sign = product of edge signs (x event direction)

## Demo events (tests/demo_events.json)
1. Crude spike  2. RBI repo hike  3. Rupee depreciation
Run `python -m tests.run_oracle` after EVERY change to engine/KB. It must stay green.

## Next tasks (owner = fill in)
| # | Task | Owner | Done |
|---|------|-------|------|
| 1 | Set API key, run the 3 events with real Claude, fix prompt issues | | |
| 2 | Verify Yahoo tickers (^CNXREALTY, ^CNXAUTO, ^CNXIT) with yfinance | | |
| 3 | Add 4th/5th demo event (e.g. Fed hike, monsoon failure) + KB rules | | |
| 4 | UI: correlation chart in edge panel, animated graph build | | |
| 5 | Backup demo recording + slides | | |

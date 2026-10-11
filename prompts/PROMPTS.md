# NewsGraph — Hackwave 3.0 PS5 Prompts & Engineering Specification

This document details the phase-wise prompts, taxonomy definitions, and prompt templates used to build and extend **NewsGraph: Autonomous Financial Event ➔ Market Impact Graph**.

---

## 🏛️ Master System Prompt (for AI Agents & LLM Extensions)

```text
You are a senior ML + Quantitative Finance + Full-Stack engineer building NewsGraph for Hackwave 3.0 PS5.
Objective: Ingest unstructured financial news, extract canonical entities and event triggers, maintain a dynamic
knowledge graph with structural priors, propagate transmission shocks across multi-order dependency paths, estimate
impacted financial assets, provide grounded step-by-step causal explanations, and empirically validate market
reactions using event-study abnormal return methodology.

Rules:
1. Ground every transmission link with explicit textual or fundamental macroeconomic evidence.
2. Maintain strict decoupling between event direction (e.g. oil price up vs down) and sentiment (e.g. pain for airlines).
3. Do not invent duplicate nodes; canonicalize entities through the alias table and dense vector linking.
4. Support counts and EMA strength must update incrementally without clobbering foundational structural priors.
5. Provide empirical validation via yfinance event studies (CAR & z-score) whenever market tickers are available.
```

---

## 📋 Phase-Wise Prompts

### Phase 1 — Curated Knowledge Graph Seed & Schema V2
```text
Task: Upgrade SQLite schema to V2 and establish canonical knowledge graph priors.
Requirements:
1. Create `data/seed_kb.json` containing 39 canonical nodes (macro indicators, commodities, sectors, central banks,
   benchmark indices, and corporate equities) and 57 curated macroeconomic dependency edges.
2. Include the canonical relationship: `in-rbi` (Reserve Bank of India) ➔ `controls` ➔ `in-repo-rate` (RBI Repo Rate).
3. Implement `app/kb.py` with Schema V2 migration:
   - `nodes`: id, label, category, aliases (JSON), ticker, created_at
   - `edges`: id, source_id, target_id, relation, direction, strength, confidence, edge_type ('knowledge',
     'observed', 'inferred'), support_count, last_observed_at, conflict_flag, status
   - `articles`, `sector_impacts`, `revisions`
4. Implement automatic seeding on first boot if DB is empty or lacks seed knowledge edges.
```

### Phase 2 — Production NLP Stack (Workstream A)
```text
Task: Replace basic regex and dictionary lookups with a modular production financial NLP engine in `app/nlp/`.
Components:
1. `linking.py`: Canonical entity linker with exact alias matching (descending length) and dense embedding cosine
   similarity fallback (threshold ≥ 0.55).
2. `ner.py`: spaCy NER (`en_core_web_sm`) extracting ORG, MONEY, PERCENT, GPE, combined with entity linking.
3. `sentiment.py`: FinBERT sentiment analysis (`ProsusAI/finbert`) yielding positive, negative, and neutral scores
   at both sentence and entity levels, decoupled from market direction.
4. `retrieval.py`: Dense sentence embedding (`sentence-transformers/all-MiniLM-L6-v2`) on `title + first 2 sentences`
   for semantic similarity search (threshold ≥ 0.45) against historical news.
5. `classifier.py`: Zero-shot directional classifier (`DeBERTa-v3` / `BART`) mapping articles to `{event_type,
   family, trigger_node, sign}`.
6. Provide fast deterministic fallbacks when `NEWSGRAPH_OFFLINE=1` is set to ensure instant offline test passes.
```

### Phase 3 — Graph Propagation & Explainability Engine (Workstream B)
```text
Task: Build `app/propagate.py` to trace multi-hop financial shocks and validate market impacts.
Requirements:
1. Cycle-safe Depth-4 DFS: Traverses knowledge graph from trigger node along directed and bidirectional edges.
   Applies damping factor γ = 0.75^depth. Accumulates compound signed impacts:
   impact = source_shock * edge_sign * edge_strength * damping.
2. Personalized PageRank & Centrality: Calculates global graph centrality to identify systemic vulnerability.
3. Natural Language Explanation Synthesis: Constructs human-readable causal chains explaining each hop
   (e.g., "Crude surge increases input costs for Paint manufacturers, squeezing gross margins").
4. Empirical Validation (`yfinance`): Implements event-study methodology computing Cumulative Abnormal Returns
   (CAR) and z-scores over [-1, +5] day trading windows against Nifty 50 or S&P 500 benchmarks.
```

### Phase 4 — Target Web Dashboard & Full-Stack UI (Workstream C)
```text
Task: Build an enterprise-grade financial intelligence dashboard in `static/index.html` with full live intelligence flow.
Views & Features:
1. Live Intelligence & News Inbox (Home View): Live streaming from Marketaux with 5 one-click preset chips
   (India Markets, Crude & Energy, RBI & Rates, Banking, Tech), multi-article selection, and batch analysis into the KG.
2. Impact Overview: Layered left-to-right causal transmission graph, live KPI summary cards with active SVG confidence ring,
   step-by-step Why explainer, and top impact chains.
3. Autonomous Sector Impact Suite: Multi-horizon sector intelligence featuring diverging horizontal bar charts,
   horizon matrix heatmap, mechanism drivers breakdown, EMA sector trend line chart, and side drawer with news citations.
4. Redesigned KG Explorer: Full interactive knowledge graph powered by `vis-network` with forceAtlas2Based physics layout,
   spherical nodes sized by centrality, diamond event nodes, focused 2-hop neighborhood isolation, and inspector drawer.
5. KB Revisions & Time-Series: Historical news delta tracking (pros/cons) and multi-horizon sector exposures
   rendered via Chart.js.
```

---

## 🏷️ Directional Event Taxonomy & Classification Schema

The zero-shot classification system operates on the following directional label set:

| Family | Event Type | Trigger Node | Default Sign | Canonical Relations |
| :--- | :--- | :--- | :---: | :--- |
| `crude_oil` | `crude_price_surge` | `crude-oil` | `+1.0` | `input_cost_for`, `margin_squeeze`, `inflationary_pressure` |
| `crude_oil` | `crude_price_drop` | `crude-oil` | `-1.0` | `cost_relief_for`, `margin_expansion` |
| `monetary_policy` | `rate_hike` | `in-repo-rate`| `+1.0` | `borrowing_cost_for`, `valuation_headwind`, `nim_expansion` |
| `monetary_policy` | `rate_pause_or_cut`| `in-repo-rate`| `-1.0` | `liquidity_boost_for`, `demand_stimulus` |
| `inflation` | `cpi_inflation_rise`| `in-cpi-inflation`| `+1.0`| `pressures_central_bank`, `consumer_discretionary_drag` |
| `inflation` | `cpi_inflation_fall`| `in-cpi-inflation`| `-1.0`| `real_income_support`, `eases_monetary_tightening` |
| `corporate` | `earnings_beat` | `infosys` | `+1.0` | `sector_sentiment_boost`, `capex_expansion` |
| `corporate` | `earnings_miss` | `infosys` | `-1.0` | `sector_sentiment_drag` |

---

## 🤖 Gemini LLM Extraction Prompt Template

When Gemini is active, `app/llm.py` prompts the model with structured output constraints:

```text
You are an expert quantitative macroeconomic analyst. Analyze this financial news item and map its causal transmission.

Article Title: {title}
Article Body: {body}
Extracted Entities: {entities}
Prior Related Events in KB: {prior_events}

Respond strictly in valid JSON matching this schema:
{
  "summary": "1-2 sentence executive briefing",
  "trigger_node": "canonical-id-of-trigger",
  "direction": 1.0 or -1.0,
  "relations": [
    {
      "source": "node-id",
      "source_type": "entity|sector|commodity|indicator",
      "target": "node-id",
      "target_type": "entity|sector|commodity|indicator",
      "relation": "input_cost_for|margin_squeeze|controls|pressures",
      "effect": "positive|negative|neutral",
      "strength": 0.0 to 1.0,
      "reason": "Detailed transmission rationale",
      "impact": "Projected asset/sector financial impact"
    }
  ],
  "sector_impacts": [
    {
      "sector": "Known Sector Name",
      "score": -1.0 to 1.0,
      "horizon": "short|medium|long",
      "confidence": 0.0 to 1.0,
      "explanation": "Causal transmission reasoning"
    }
  ]
}
```

# NewsGraph — Autonomous Financial Event ➔ Market Impact Graph

[![Tests](https://img.shields.io/badge/acceptance_tests-18_passed-success.svg)](tests/run_tests.py)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![Hackwave](https://img.shields.io/badge/Hackwave_3.0-PS5_Financial_KG-purple.svg)](https://hackwave.dev)

**NewsGraph** is an enterprise-grade AI system built for **Hackwave 3.0 PS5: "Autonomous Financial Event ➔ Market Impact Graph"**. It ingests unstructured financial news, extracts canonical entities and event triggers, builds and updates a dynamic dependency knowledge graph, propagates transmission shocks through multi-order paths, estimates affected assets, explains every step with grounded evidence, and empirically validates abnormal returns using event studies.

---

## 🚀 Key Highlights & Architecture

```
Unstructured News (Marketaux Live Feed / Market Sectors / Sample)
           │
           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ WORKSTREAM A: Production Financial NLP Stack                          │
│  • spaCy NER (en_core_web_sm) + Alias Canonical Entity Linking (≥0.55)│
│  • FinBERT Sentiment (ProsusAI/finbert) decoupled from event sign     │
│  • Sentence-Transformers (all-MiniLM-L6-v2) Dense Retrieval (≥0.45)   │
│  • Direction-Aware Zero-Shot Classification (DeBERTa-v3 / BART)       │
│  • Real engine provenance probe & graceful offline fallback labelling  │
└────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ WORKSTREAM B: Dynamic Knowledge Graph & Sector Engine                  │
│  • SQLite Schema V2 with seed priors & news_inbox buffer table        │
│  • Incremental Edge Upsert: Support count, EMA strength, time decay    │
│  • Multi-Path Propagation: Depth-4 DFS, Noisy-OR confidence            │
│  • Sector Analysis: Blended KG + LLM scoring with tanh net effect      │
│  • Empirical Validation: yfinance Abnormal Return & CAR event studies  │
└────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────────────────────┐
│ WORKSTREAM C: Modern Full-Stack Dashboard (static/index.html)          │
│  • Live Feed & News Inbox: Marketaux stream, search, presets & bulk kg │
│  • Layered Left-to-Right Impact Graph & Dynamic Path Highlighting      │
│  • Full Sector Impact Suite: Diverging bars, Heatmap, Drivers, Trend   │
│  • vis-network KG Explorer: forceAtlas2 physics, 2-hop focused view    │
│  • KB Revisions & Multi-horizon Time Series (Chart.js)                 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Quickstart & Installation

### 1. Requirements
- Python 3.10+
- Internet access for downloading models / dependencies (supports full offline mode via internal fallback)

### 2. Install Dependencies & Pre-download NLP Models
```bash
# Clone or navigate to the directory
cd newsgraph

# Install Python requirements
pip install -r requirements.txt

# Download all required NLP models in one step
python -m app.nlp.download
```
*`python -m app.nlp.download` pre-loads and verifies spaCy `en_core_web_sm`, FinBERT `ProsusAI/finbert`, MiniLM `all-MiniLM-L6-v2`, and DeBERTa/BART classifiers.*

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your API keys (optional if running offline on sample data or tests):
```env
MARKETAUX_API_KEY=your_marketaux_token_here
GEMINI_API_KEY=your_gemini_key_here
```

### 4. Run Acceptance & Unit Tests
Verify the entire pipeline with all 14 tests:
```bash
python tests/run_tests.py
```
> **Output:** `PASS test_acceptance_1_brent_crude_propagation`, `PASS test_acceptance_2_rbi_reversal_retrieval`, `PASS test_acceptance_3_entity_merge`, `PASS test_acceptance_4_upsert_and_conflict`... `14 passed, 0 failed.`

---

## 🖥️ Running the Application

### Start the Interactive Server
```bash
python -m app serve --host 127.0.0.1 --port 8000
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

### Ingestion CLI
You can ingest news via CLI anytime:
```bash
# Ingest curated sample articles (oldest-first, idempotent)
python -m app ingest --mode sample

# Force re-ingestion and update graph edges
python -m app ingest --mode sample --force

# Ingest live financial news from Marketaux
python -m app ingest --mode live --search "RBI" --limit 10

# Reset knowledge base to pristine seed priors
python -m app reset
```

---

## ⚙️ Environment Configuration

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `MARKETAUX_API_KEY` | *(None)* | Marketaux REST API key for live financial news |
| `GEMINI_API_KEY` | *(None)* | Google Gemini API key for advanced narrative extraction |
| `NEWSGRAPH_OFFLINE` | `0` | If `1`, enables instant deterministic NLP fallback for fast testing & CI |
| `NEWSGRAPH_SPACY_MODEL`| `en_core_web_sm` | spaCy model used for entity tokenization and NER |
| `NEWSGRAPH_SIM_MIN` | `0.45` | Cosine similarity threshold for related news retrieval |
| `NEWSGRAPH_LINK_MIN`| `0.55` | Embedding similarity threshold for canonical entity linking |
| `NEWSGRAPH_DECAY_TAU`| `180.0` | Exponential half-life in days for edge confidence decay (`exp(-t/τ)`) |
| `NEWSGRAPH_DEVICE` | `auto` | Device to run HuggingFace models on (`cpu`, `cuda`, `mps`) |
| `PORT` | `8000` | Port for the HTTP server |

---

## 🔬 NLP & Graph Architecture Details

### Workstream A: NLP & Feature Extraction
- **Canonical Entity Linking (`app/nlp/linking.py`):** Canonicalizes disparate surface forms (e.g. *"Reserve Bank of India"*, *"RBI"*, *"Governor Das"*, *"Central Bank"*) to canonical ID `in-rbi` using longest-substring gazetteer matching and dense vector embeddings.
- **FinBERT Sentiment (`app/nlp/sentiment.py`):** Uses `ProsusAI/finbert` to compute sentence and entity-level sentiment strictly decoupled from event direction (e.g., *"Oil surges"* produces positive price shock for oil, but negative sentiment for airlines).
- **Dense Embedding Retrieval (`app/nlp/retrieval.py`):** Encodes `title + first two sentences` using `sentence-transformers/all-MiniLM-L6-v2` for cosine similarity matching against the knowledge base (threshold $\ge 0.45$).
- **Zero-Shot Directional Classification (`app/nlp/classifier.py`):** Disambiguates complex macroeconomic events (e.g., distinguishing an *oil price surge* from an *oil supply cut*, or a *rate pause* from a *rate hike*).

### Workstream B: Dynamic Knowledge Graph & Propagation
- **Knowledge Base Schema V2 (`app/kb.py`):** Stores nodes (`id`, `label`, `category`, `aliases`, `ticker`) and edges (`source_id`, `target_id`, `relation`, `direction`, `strength`, `confidence`, `edge_type`, `support_count`, `last_observed_at`, `status`).
- **Curated Prior Graph (`data/seed_kb.json`):** 39 canonical nodes and 57 curated structural links extracted from financial macro fundamentals (e.g., `crude-oil` ➔ `input_cost_for` ➔ `paint-mfg`, `crude-oil` ➔ `margin_squeeze` ➔ `omc-refining`).
- **Incremental Edge Upsert & Conflict Handling:**
  - Observed and inferred edges are upserted with running support counts.
  - Strength is updated using an Exponential Moving Average: $\text{EMA}_{\text{new}} = \alpha \cdot \text{new} + (1-\alpha) \cdot \text{prior}$ ($\alpha = 0.3$).
  - Inferred edges decay in confidence over time via $C(t) = C_0 \cdot e^{-\Delta t / \tau}$.
  - Contradictory signals trigger conflict flags (`conflict_flag = 1`) and review alerts.
- **Propagation Engine (`app/propagate.py`):**
  - **Cycle-safe Depth-4 DFS:** Computes multi-step shock propagation up to 4 hops with damping factor $\gamma = 0.75^d$.
  - **Personalized PageRank & Degree Centrality:** Ranks downstream node vulnerability across the whole graph.
  - **Explainability Synthesis:** Generates grounded textual explanations step-by-step for every link.
  - **Empirical Event-Study Validation (`yfinance`):** Calculates Cumulative Abnormal Return (CAR) and z-scores over $[-1, +5]$ day trading windows against Nifty 50 / S&P 500 benchmarks.

### Workstream C: Target Web Dashboard
- **Visual Design Parity:** Premium design tokens, responsive light/dark mode, and live KPI summary cards with active SVG confidence ring.
- **Live Feed & News Inbox (Home View):** Live streaming from Marketaux with 5 one-click preset chips (India Markets, Crude & Energy, RBI & Rates, Banking, Tech). Supports multi-article selection and batch analysis into the knowledge graph. Gracefully degrades to cached inbox with clear labelling on quota limits.
- **Layered Impact Graph:** Clean left-to-right causal layout (Trigger ➔ Indicators/Commodities ➔ Sectors ➔ Companies/Indices). Nodes are fully illuminated on load with dimming only applied during active chain focus.
- **Autonomous Sector Impact Suite:**
  1. *Diverging Bar Chart:* Shows net positive/negative sector exposure with opacity mapped to confidence.
  2. *Horizon Matrix Heatmap:* Immediate, Short-term, and Medium-term impact intensity.
  3. *Mechanism Drivers Breakdown:* Stacked bar attribution of contributing paths vs LLM reasoning.
  4. *Sector Trajectory (EMA Trend):* Historical multi-sector index movement over time.
  5. *Sector Intelligence Table & Slide-out Drawer:* Interactive inspection with causal mechanisms and news evidence citations.
- **Redesigned KG Explorer:** `vis-network` with `forceAtlas2Based` physics layout, spherical nodes sized by centrality, diamond event nodes, focused 2-hop neighborhood isolation, and interactive node/edge inspection drawer.
- **KB Revisions & Time-Series:** Tracks historical news revisions, pros & cons delta analysis, and interactive multi-horizon sector exposure graphs powered by Chart.js.

---

## 🧮 Autonomous Sector Score Computation

Sector impact is computed by blending graph propagation causal paths with zero-shot/LLM sentiment reasoning:

$$\text{Confidence}_{\text{KG}} = 1 - \prod_{i=1}^{n} (1 - c_i) \quad (\text{Noisy-OR})$$

$$\text{Net Score}_{\text{KG}} = \tanh\left(\sum_{i=1}^{n} \text{sign}_i \times c_i\right)$$

$$\text{Score}_{\text{Blended}} = 0.6 \cdot \text{Score}_{\text{KG}} + 0.4 \cdot \text{Score}_{\text{LLM}}$$

$$\text{Confidence}_{\text{Blended}} = 1 - (1 - 0.6 \cdot \text{Conf}_{\text{KG}})(1 - 0.4 \cdot \text{Conf}_{\text{LLM}})$$

*Disclaimer: Plausible impact estimates based on curated economic knowledge and NLP extraction, not financial predictions or investment advice.*

---

## 📡 REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/status` | `GET` | Returns honest engine states (`ready`, `fallback`, `error`), Gemini ListModels status, and presets |
| `/api/news/live` | `GET` | Fetches live Marketaux news with near-duplicate deduplication; filters by presets (`?preset=...`) |
| `/api/news/inbox` | `GET` | Returns news inbox items, optionally filtered by status (`?status=pending\|analyzed`) |
| `/api/news/analyze` | `POST` | Batch analyzes inbox articles (`{uuids: [...]}`), runs propagation, and commits to KG |
| `/api/sector-analysis` | `GET` | Per-article or aggregate multi-horizon sector intelligence (`?article=<id>` or `?scope=all`) |
| `/api/analyze` | `POST` | Analyzes pasted headline or article ID with full NLP extraction and propagation |
| `/api/validate` | `POST` | Runs `yfinance` event-study validation for given tickers, event dates, and signs |
| `/api/kg` | `GET` | Returns knowledge graph nodes and edges with confidence thresholds (`?min_conf=...`) |
| `/api/kg/node/<id>` | `GET` | Returns node metadata, connected edges, and supporting news articles |
| `/api/timeseries` | `GET` | Returns cumulative sector impact time-series with Exponential Moving Average (EMA) |
| `/api/revisions` | `GET` | Returns historical revisions and comparative pros/cons |
| `/api/articles` | `GET` | Returns all ingested articles in the archive |
| `/api/ingest` | `POST` | Triggers sample or live news ingestion |
| `/api/reset` | `POST` | Clears local knowledge base and reloads seed priors |

---

## 🧪 Acceptance Test Suite

The test suite in `tests/run_tests.py` validates all core requirements (18 tests passing):

1. **Acceptance 1: Brent Crude Spike ($95/bbl)** — Traces multi-hop transmission reaching Aviation (-), Paint (-), ONGC (+), and Real Estate (-).
2. **Acceptance 2: RBI Rate Hike vs Pause Reversal** — Dense retrieval matches prior monetary policy event ($\ge 0.45$) and records positive relief revision.
3. **Acceptance 3: Entity Disambiguation & Alias Merging** — Resolves aliases ("Brent", "crude oil") to canonical `Crude Oil`.
4. **Acceptance 4: Incremental Edge Upsert & Conflict Handling** — Repeated observations increment `support_count`, opposite signs flag conflict.
5. **Phase 6 Verification Tests** — Live inbox workflow, noisy-OR and tanh sector math, engine provenance honesty, and Gemini ListModels error handling.


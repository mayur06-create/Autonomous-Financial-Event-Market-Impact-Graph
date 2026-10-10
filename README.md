# Market Impact Graph (Hackwave PS5)

## Run
```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...     # optional; without it a keyword fallback is used
uvicorn backend.main:app --reload
```
Open http://localhost:8000

## Structure
- backend/knowledge_base.json : curated causal rules (add more! 40+ is ideal)
- backend/llm.py              : extraction / inference / explanation prompts (Claude)
- backend/graph_engine.py     : graph build, scoring, propagation (DFS, top-k)
- backend/market_data.py      : yfinance correlation (counter-evidence)
- frontend/index.html         : force-graph UI

## Edge types
observed (solid) = stated in news | knowledge (dashed) = curated rule | inferred (dotted) = LLM guess

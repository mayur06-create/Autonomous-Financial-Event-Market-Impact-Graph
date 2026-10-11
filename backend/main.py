import json
import os
import pathlib
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from . import graph_engine, schemas

app = FastAPI(title="Market Impact Graph")

BASE_DIR = pathlib.Path(__file__).parent.parent
DEMO_EVENTS_PATH = BASE_DIR / "tests" / "demo_events.json"
FRONTEND_DIR = BASE_DIR / "frontend"

@app.get("/health", response_model=schemas.HealthResponse)
def health():
    return {
        "status": "ok",
        "mode": "llm" if os.getenv("ANTHROPIC_API_KEY") else "fallback",
        "nodes": graph_engine.G.number_of_nodes(),
        "edges": graph_engine.G.number_of_edges(),
    }

@app.get("/demo-events")
def demo_events():
    if not DEMO_EVENTS_PATH.exists():
        raise HTTPException(status_code=404, detail="demo_events.json not found")
    return json.loads(DEMO_EVENTS_PATH.read_text(encoding="utf-8"))

@app.get("/graph")
def get_graph():
    return graph_engine.get_graph()

@app.post("/reset", response_model=schemas.ResetResponse)
def reset():
    return graph_engine.reset()

@app.post("/analyze", response_model=schemas.AnalyzeResponse)
def analyze(n: schemas.AnalyzeRequest):
    res = graph_engine.analyze(n.text)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.get("/")
def serve_dashboard():
    return FileResponse(FRONTEND_DIR / "dashboard.html")

@app.get("/legacy")
def serve_legacy():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=False), name="ui")

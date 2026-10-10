import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import graph_engine

app = FastAPI(title="Market Impact Graph")

class News(BaseModel):
    text: str

@app.post("/analyze")
def analyze(n: News):
    return graph_engine.analyze(n.text)

app.mount("/", StaticFiles(directory="frontend", html=True), name="ui")

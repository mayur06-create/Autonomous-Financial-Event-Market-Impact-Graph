from typing import List, Optional, Literal, Any
from pydantic import BaseModel, Field, ConfigDict

class AnalyzeRequest(BaseModel):
    text: str

class EventInfo(BaseModel):
    type: str
    headline: str
    direction: str
    magnitude: Optional[str] = None
    primary_entity: Optional[str] = None

class Node(BaseModel):
    id: str
    type: str = "Unknown"
    ticker: Optional[str] = None

class Edge(BaseModel):
    source: str
    target: str
    evidence_type: Literal["observed", "knowledge", "inferred"]
    confidence: float
    sign: int
    reason: str = ""
    evidence_text: str = ""
    correlation: Optional[float] = None
    counter_evidence: bool = False

class PathStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_node: str = Field(alias="from")
    to: str
    sign: int
    confidence: float
    evidence_type: Literal["observed", "knowledge", "inferred"] = "knowledge"
    reason: str = ""
    evidence_text: str = ""
    correlation: Optional[float] = None
    counter_evidence: bool = False

class Path(BaseModel):
    target: str
    steps: List[PathStep]
    confidence: float
    impact: int
    depth: int
    explanation: Optional[str] = None

class AffectedAsset(BaseModel):
    name: str
    type: str
    impact: int
    confidence: float
    score: Optional[float] = None
    path: Optional[Path] = None

class KPIs(BaseModel):
    assets_affected: int
    chains_traced: int
    avg_confidence: float
    positive: int
    negative: int

class GraphSize(BaseModel):
    nodes: int
    edges: int
    events: int

class AnalyzeResponse(BaseModel):
    event: EventInfo
    start_node: Optional[str] = None
    start_sign: Optional[int] = None
    nodes: List[Node]
    edges: List[Edge]
    top_paths: List[Path]
    affected_assets: List[AffectedAsset]
    kpis: KPIs
    graph_size: GraphSize
    disclaimer: str = "Plausible impact chains, not predictions. Correlation is not causation."
    mode: Literal["llm", "fallback"] = "fallback"

class ResetResponse(BaseModel):
    status: str
    nodes: int
    edges: int

class HealthResponse(BaseModel):
    status: str
    mode: Literal["llm", "fallback"]
    nodes: int
    edges: int

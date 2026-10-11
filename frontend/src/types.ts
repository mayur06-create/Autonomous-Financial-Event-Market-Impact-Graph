/**
 * types.ts — TypeScript interfaces matching backend Pydantic models.
 */

export type NodeType = 'commodity' | 'policy' | 'indicator' | 'instrument' | 'sector'

export type Sign = '+' | '-' | '?'

export type Lag = 'immediate' | 'short' | 'long'

export type EdgeStatus = 'observed' | 'seed' | 'inferred'

export interface Node {
  id: string
  label: string
  type: NodeType
  description?: string | null
  ticker?: string | null
  x?: number
  y?: number
  vx?: number
  vy?: number
  index?: number
}

export interface Edge {
  id: string
  source: string | Node
  target: string | Node
  sign: Sign
  strength_min: number
  strength_max: number
  lag: Lag
  reasoning: string
  evidence?: string | null
  status: EdgeStatus
  confidence: number
  source_ref?: string | null
}

export interface SeedEdge {
  id: string
  source: string
  target: string
  sign: Sign
  strength_range: [number, number]
  lag: Lag
  reasoning: string
  source_ref: string
}

export interface ExtractedEvent {
  event_type: string
  entities: string[]
  direction: Sign
  magnitude?: string | null
  region?: string | null
  evidence_sentence: string
  primary_node: string
  unlinked_entities: string[]
}

export interface PathResult {
  nodes: string[]
  edge_ids: string[]
  path_score: number
  sign: Sign
  hop_count: number
  summary: string
}

export interface AffectedAsset {
  node_id: string
  label: string
  node_type: NodeType
  direction: Sign
  confidence: number
  paths: number
  reasoning: string
}

export interface ValidationResult {
  ticker: string
  node_id: string
  car?: number | null
  event_date?: string | null
  window_days: number
  direction_match?: boolean | null
  label: string
  note: string
}

export interface UncertaintyNote {
  headline: string
  details: string[]
}

export interface ImpactGraph {
  nodes: Node[]
  edges: Edge[]
  event: ExtractedEvent
  top_paths: PathResult[]
  affected_assets: AffectedAsset[]
  validation: ValidationResult[]
  uncertainty_note: UncertaintyNote
  agreement_ratio: number
  cached: boolean
}

export interface SeedGraphResponse {
  node_count: number
  edge_count: number
  nodes: Node[]
  edges: SeedEdge[]
  themes: string[]
}

export interface SampleArticle {
  id: string
  title: string
  source: string
  date: string
  tag: string
  icon: string
  text: string
  expectedPrimary: string
  expectedDirection: Sign
  description: string
}

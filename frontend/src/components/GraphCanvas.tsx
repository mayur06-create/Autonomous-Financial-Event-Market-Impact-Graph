import React, { useRef, useState, useEffect, useMemo, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import type { ForceGraphMethods } from 'react-force-graph-2d'
import type { Node, Edge, NodeType } from '../types'
import { ZoomIn, ZoomOut, Maximize2, Layers } from 'lucide-react'

interface GraphCanvasProps {
  nodes: Node[]
  edges: Edge[]
  primaryNodeId?: string
  selectedNodeId: string | null
  setSelectedNodeId: (id: string | null) => void
}

const TYPE_COLORS: Record<NodeType, string> = {
  commodity:  '#f59e0b', // Amber
  policy:     '#a855f7', // Purple
  indicator:  '#3b82f6', // Blue
  instrument: '#06b6d4', // Cyan
  sector:     '#10b981', // Emerald
}

const SIGN_COLORS: Record<string, string> = {
  '+': '#10b981', // Positive / green
  '-': '#f43f5e', // Negative / red
  '?': '#f59e0b', // Ambiguous / amber
}

export const GraphCanvas: React.FC<GraphCanvasProps> = ({
  nodes,
  edges,
  primaryNodeId,
  selectedNodeId,
  setSelectedNodeId,
}) => {
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined)
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const [activeTypeFilter, setActiveTypeFilter] = useState<NodeType | 'all'>('all')

  // Resize observer
  useEffect(() => {
    if (!containerRef.current) return
    const updateSize = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth || 800,
          height: Math.max(480, containerRef.current.clientHeight || 500),
        })
      }
    }
    updateSize()
    window.addEventListener('resize', updateSize)
    return () => window.removeEventListener('resize', updateSize)
  }, [])

  // Graph data transformation
  const graphData = useMemo(() => {
    const filteredNodes = activeTypeFilter === 'all'
      ? nodes
      : nodes.filter(n => n.type === activeTypeFilter || n.id === primaryNodeId)

    const validNodeIds = new Set(filteredNodes.map(n => n.id))

    const filteredEdges = edges.filter(e => {
      const src = typeof e.source === 'object' ? (e.source as Node).id : e.source
      const tgt = typeof e.target === 'object' ? (e.target as Node).id : e.target
      return validNodeIds.has(src) && validNodeIds.has(tgt)
    })

    return {
      nodes: filteredNodes.map(n => ({ ...n })),
      links: filteredEdges.map(e => ({
        ...e,
        source: typeof e.source === 'object' ? (e.source as Node).id : e.source,
        target: typeof e.target === 'object' ? (e.target as Node).id : e.target,
      })),
    }
  }, [nodes, edges, activeTypeFilter, primaryNodeId])

  // Zoom to fit on initial load or nodes change
  useEffect(() => {
    const timer = setTimeout(() => {
      if (fgRef.current) {
        fgRef.current.zoomToFit(400, 40)
      }
    }, 600)
    return () => clearTimeout(timer)
  }, [graphData.nodes.length])

  // Custom node drawing
  const drawNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const isSelected = selectedNodeId === node.id
    const isPrimary = primaryNodeId === node.id
    const baseColor = TYPE_COLORS[node.type as NodeType] || '#6c8ef5'
    const radius = isPrimary ? 8 : isSelected ? 7 : 5.5

    // Outer Glow / Ring
    if (isPrimary || isSelected) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, radius + 4, 0, 2 * Math.PI, false)
      ctx.fillStyle = isPrimary ? 'rgba(99, 102, 241, 0.35)' : 'rgba(34, 211, 238, 0.35)'
      ctx.fill()
    }

    // Node Body
    ctx.beginPath()
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false)
    ctx.fillStyle = baseColor
    ctx.fill()
    ctx.lineWidth = isSelected ? 2 : 1
    ctx.strokeStyle = '#ffffff'
    ctx.stroke()

    // Label on zoom
    if (globalScale > 0.8 || isPrimary || isSelected) {
      const label = node.label || node.id
      const fontSize = Math.max(10 / globalScale, 9)
      ctx.font = `${isSelected ? 'bold ' : ''}${fontSize}px Inter, sans-serif`
      const textWidth = ctx.measureText(label).width
      const padX = 4
      const padY = 2
      const bgX = node.x - textWidth / 2 - padX
      const bgY = node.y + radius + 3

      // Text background pill
      ctx.fillStyle = 'rgba(11, 13, 20, 0.85)'
      ctx.beginPath()
      ctx.roundRect?.(bgX, bgY, textWidth + padX * 2, fontSize + padY * 2, 3)
      ctx.fill()
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)'
      ctx.lineWidth = 0.5
      ctx.stroke()

      // Text string
      ctx.fillStyle = isSelected ? '#38bdf8' : '#e8eaf0'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillText(label, node.x, bgY + padY)
    }
  }, [selectedNodeId, primaryNodeId])

  const selectedNode = useMemo(() => {
    return nodes.find(n => n.id === selectedNodeId)
  }, [nodes, selectedNodeId])

  return (
    <div className="bg-[#121520] border border-[#23283b] rounded-2xl overflow-hidden shadow-xl shadow-black/40 flex flex-col relative">
      {/* Graph Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-[#23283b] bg-[#181c2b]/50">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-bold text-white uppercase tracking-wider">
            Interactive Causal Network
          </span>
          <span className="text-[11px] font-mono text-[#8b90a6]">
            ({graphData.nodes.length} nodes · {graphData.links.length} edges)
          </span>
        </div>

        {/* Filters & Zoom controls */}
        <div className="flex items-center gap-2">
          {/* Node Type Filter */}
          <div className="flex items-center gap-1 bg-[#0b0d14] border border-[#23283b] rounded-lg p-0.5 text-[11px]">
            <button
              onClick={() => setActiveTypeFilter('all')}
              className={`px-2 py-0.5 rounded transition-colors ${
                activeTypeFilter === 'all' ? 'bg-indigo-500 text-white font-semibold' : 'text-[#8b90a6] hover:text-white'
              }`}
            >
              All
            </button>
            {(['commodity', 'policy', 'indicator', 'sector', 'instrument'] as NodeType[]).map(t => (
              <button
                key={t}
                onClick={() => setActiveTypeFilter(t)}
                className={`px-2 py-0.5 rounded capitalize transition-colors ${
                  activeTypeFilter === t ? 'bg-indigo-500 text-white font-semibold' : 'text-[#8b90a6] hover:text-white'
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Zoom Buttons */}
          <div className="flex items-center gap-1 border-l border-[#23283b] pl-2">
            <button
              onClick={() => fgRef.current?.zoom(fgRef.current.zoom() * 1.3, 300)}
              className="p-1.5 rounded-lg bg-[#0b0d14] hover:bg-[#21263a] border border-[#23283b] text-[#8b90a6] hover:text-white transition-colors"
              title="Zoom In"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => fgRef.current?.zoom(fgRef.current.zoom() / 1.3, 300)}
              className="p-1.5 rounded-lg bg-[#0b0d14] hover:bg-[#21263a] border border-[#23283b] text-[#8b90a6] hover:text-white transition-colors"
              title="Zoom Out"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => fgRef.current?.zoomToFit(400, 30)}
              className="p-1.5 rounded-lg bg-[#0b0d14] hover:bg-[#21263a] border border-[#23283b] text-[#8b90a6] hover:text-white transition-colors"
              title="Zoom to Fit"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Main Canvas Area */}
      <div ref={containerRef} className="w-full h-[520px] bg-[#0b0d14] relative">
        <ForceGraph2D
          ref={fgRef as any}
          width={dimensions.width}
          height={dimensions.height}
          graphData={graphData}
          nodeCanvasObject={drawNode}
          nodePointerAreaPaint={(node: any, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI, false)
            ctx.fill()
          }}
          linkColor={(link: any) => SIGN_COLORS[link.sign] || '#6c8ef5'}
          linkWidth={(link: any) => (link.strength_min + link.strength_max) * 1.5}
          linkCurvature={0.12}
          linkDirectionalArrowLength={4.5}
          linkDirectionalArrowRelPos={0.95}
          linkDirectionalParticles={2}
          linkDirectionalParticleWidth={2}
          linkDirectionalParticleSpeed={0.005}
          linkDirectionalParticleColor={(link: any) => SIGN_COLORS[link.sign] || '#6c8ef5'}
          linkLabel={(link: any) => `
            <div style="background: #181c2b; border: 1px solid #23283b; padding: 6px 10px; border-radius: 8px; font-size: 11px; color: #e8eaf0; font-family: Inter, sans-serif; max-width: 240px;">
              <div style="font-weight: 600; color: ${SIGN_COLORS[link.sign]}">
                Effect: ${link.sign === '+' ? 'Positive (+)' : link.sign === '-' ? 'Negative (−)' : 'Ambiguous (?)'}
              </div>
              <div style="color: #8b90a6; margin-top: 2px;">Strength: [${link.strength_min}, ${link.strength_max}] · Lag: ${link.lag}</div>
              <div style="margin-top: 4px; font-size: 10px; line-height: 1.3;">${link.reasoning}</div>
              ${link.source_ref ? `<div style="margin-top: 4px; font-size: 9px; color: #6366f1;">Ref: ${link.source_ref}</div>` : ''}
            </div>
          `}
          onNodeClick={(node: any) => {
            setSelectedNodeId(node.id === selectedNodeId ? null : node.id)
          }}
          backgroundColor="#0b0d14"
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.3}
        />

        {/* Legend Overlay */}
        <div className="absolute bottom-3 left-3 bg-[#121520]/90 backdrop-blur-md border border-[#23283b] rounded-xl p-2.5 text-[11px] shadow-lg flex flex-col gap-1.5">
          <div className="text-[10px] uppercase font-semibold text-[#8b90a6] mb-0.5">Node Categories</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            {Object.entries(TYPE_COLORS).map(([type, color]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                <span className="capitalize text-[#e8eaf0] text-[10px]">{type}</span>
              </div>
            ))}
          </div>
          <div className="border-t border-[#23283b] pt-1.5 mt-0.5 flex items-center gap-3">
            <div className="flex items-center gap-1">
              <span className="w-2 h-0.5 bg-[#10b981]" />
              <span className="text-[#10b981] text-[10px] font-mono">+ (Positive)</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2 h-0.5 bg-[#f43f5e]" />
              <span className="text-[#f43f5e] text-[10px] font-mono">− (Negative)</span>
            </div>
          </div>
        </div>

        {/* Inspector Popover if node is selected */}
        {selectedNode && (
          <div className="absolute top-3 right-3 max-w-xs bg-[#121520]/95 backdrop-blur-md border border-cyan-500/40 rounded-xl p-3.5 text-xs shadow-2xl space-y-2 animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between border-b border-[#23283b] pb-2">
              <div>
                <span className="text-white font-bold block">{selectedNode.label}</span>
                <span className="text-[10px] font-mono text-cyan-400 capitalize">
                  {selectedNode.type} {selectedNode.ticker && `· ${selectedNode.ticker}`}
                </span>
              </div>
              <button
                onClick={() => setSelectedNodeId(null)}
                className="text-[#8b90a6] hover:text-white text-xs px-1.5 py-0.5 rounded bg-[#181c2b]"
              >
                ✕
              </button>
            </div>
            <p className="text-[11px] text-[#8b90a6] leading-relaxed">
              {selectedNode.description || 'Curated node from Indian macroeconomic seed model.'}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

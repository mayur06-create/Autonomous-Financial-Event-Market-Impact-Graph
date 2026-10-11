import React, { useState, useEffect } from 'react'
import type { SeedGraphResponse } from '../types'
import { X, Search, Database, BookOpen } from 'lucide-react'

interface SeedGraphModalProps {
  isOpen: boolean
  onClose: () => void
}

export const SeedGraphModal: React.FC<SeedGraphModalProps> = ({ isOpen, onClose }) => {
  const [data, setData] = useState<SeedGraphResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'edges' | 'nodes' | 'themes'>('edges')
  const [search, setSearch] = useState('')

  useEffect(() => {
    if (!isOpen) return
    setLoading(true)
    fetch('/seed-graph')
      .then(res => res.json())
      .then(res => {
        setData(res)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [isOpen])

  if (!isOpen) return null

  const filteredEdges = data?.edges.filter(e =>
    e.source.toLowerCase().includes(search.toLowerCase()) ||
    e.target.toLowerCase().includes(search.toLowerCase()) ||
    e.reasoning.toLowerCase().includes(search.toLowerCase()) ||
    e.source_ref.toLowerCase().includes(search.toLowerCase())
  ) || []

  const filteredNodes = data?.nodes.filter(n =>
    n.label.toLowerCase().includes(search.toLowerCase()) ||
    n.id.toLowerCase().includes(search.toLowerCase()) ||
    (n.ticker && n.ticker.toLowerCase().includes(search.toLowerCase()))
  ) || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
      <div className="bg-[#121520] border border-[#23283b] rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#23283b] bg-[#181c2b]/50">
          <div className="flex items-center gap-2.5">
            <Database className="w-5 h-5 text-blue-400" />
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                Curated Indian Macro Causal Graph
                <span className="text-xs font-mono font-normal text-blue-400 px-2 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/20">
                  {data?.node_count || 33} Nodes · {data?.edge_count || 47} Edges
                </span>
              </h3>
              <p className="text-xs text-[#8b90a6]">
                Ground-truth causal seed model with literature-backed source citations
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-[#0b0d14] hover:bg-[#21263a] text-[#8b90a6] hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Toolbar: Search & Tabs */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3 border-b border-[#23283b] bg-[#0b0d14]">
          <div className="flex items-center gap-2 bg-[#181c2b] border border-[#23283b] rounded-lg px-3 py-1.5 w-64 text-xs">
            <Search className="w-3.5 h-3.5 text-[#8b90a6]" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search nodes, citations, reasoning..."
              className="bg-transparent text-white outline-none w-full placeholder-[#545870]"
            />
          </div>

          <div className="flex items-center gap-1 bg-[#181c2b] border border-[#23283b] rounded-lg p-0.5 text-xs">
            <button
              onClick={() => setActiveTab('edges')}
              className={`px-3 py-1 rounded transition-colors ${
                activeTab === 'edges' ? 'bg-indigo-500 text-white font-semibold' : 'text-[#8b90a6] hover:text-white'
              }`}
            >
              Causal Edges ({data?.edge_count || 47})
            </button>
            <button
              onClick={() => setActiveTab('nodes')}
              className={`px-3 py-1 rounded transition-colors ${
                activeTab === 'nodes' ? 'bg-indigo-500 text-white font-semibold' : 'text-[#8b90a6] hover:text-white'
              }`}
            >
              Macro Nodes ({data?.node_count || 33})
            </button>
            <button
              onClick={() => setActiveTab('themes')}
              className={`px-3 py-1 rounded transition-colors ${
                activeTab === 'themes' ? 'bg-indigo-500 text-white font-semibold' : 'text-[#8b90a6] hover:text-white'
              }`}
            >
              Core Themes
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-3">
          {loading ? (
            <div className="text-center py-12 text-[#8b90a6]">Loading seed graph...</div>
          ) : activeTab === 'edges' ? (
            <div className="space-y-3">
              {filteredEdges.map(e => (
                <div
                  key={e.id}
                  className="bg-[#181c2b] border border-[#23283b] rounded-xl p-3.5 space-y-2 text-xs"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-white bg-[#0b0d14] px-2 py-0.5 rounded border border-[#23283b]">
                        {e.source}
                      </span>
                      <span className={`font-mono font-bold px-1.5 py-0.5 rounded ${
                        e.sign === '+' ? 'text-emerald-400 bg-emerald-500/10' : e.sign === '-' ? 'text-rose-400 bg-rose-500/10' : 'text-amber-400 bg-amber-500/10'
                      }`}>
                        ──({e.sign})──►
                      </span>
                      <span className="font-mono font-bold text-white bg-[#0b0d14] px-2 py-0.5 rounded border border-[#23283b]">
                        {e.target}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 text-[11px] font-mono text-[#8b90a6]">
                      <span>Weight: [{e.strength_range[0]}, {e.strength_range[1]}]</span>
                      <span>·</span>
                      <span className="capitalize">{e.lag} lag</span>
                    </div>
                  </div>

                  <p className="text-[#8b90a6] leading-relaxed text-[11px]">
                    {e.reasoning}
                  </p>

                  <div className="flex items-center gap-1.5 text-[10px] text-blue-400 font-mono">
                    <BookOpen className="w-3 h-3" />
                    <span>Citation: {e.source_ref}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : activeTab === 'nodes' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filteredNodes.map(n => (
                <div
                  key={n.id}
                  className="bg-[#181c2b] border border-[#23283b] rounded-xl p-3.5 space-y-1.5 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white">{n.label}</span>
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      {n.type}
                    </span>
                  </div>
                  <div className="text-[11px] font-mono text-cyan-400">
                    ID: {n.id} {n.ticker && `· Ticker: ${n.ticker}`}
                  </div>
                  <p className="text-[11px] text-[#8b90a6] leading-relaxed">
                    {n.description}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-3">
              {data?.themes.map((theme, idx) => (
                <div
                  key={idx}
                  className="bg-[#181c2b] border border-[#23283b] rounded-xl p-4 text-xs space-y-1"
                >
                  <h4 className="font-bold text-white text-sm">{theme}</h4>
                  <p className="text-[#8b90a6] text-[11px]">
                    Causal propagation sub-network anchored on structural Indian transmission mechanisms.
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

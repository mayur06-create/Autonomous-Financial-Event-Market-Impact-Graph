import React, { useState } from 'react'
import type { AffectedAsset, Sign } from '../types'
import { ArrowUpRight, ArrowDownRight, HelpCircle, Target } from 'lucide-react'

interface AffectedAssetsGridProps {
  assets: AffectedAsset[]
  onSelectNode: (nodeId: string) => void
  selectedNodeId: string | null
}

export const AffectedAssetsGrid: React.FC<AffectedAssetsGridProps> = ({
  assets,
  onSelectNode,
  selectedNodeId,
}) => {
  const [directionFilter, setDirectionFilter] = useState<Sign | 'all'>('all')

  const filteredAssets = directionFilter === 'all'
    ? assets
    : assets.filter(a => a.direction === directionFilter)

  return (
    <div className="bg-[#121520] border border-[#23283b] rounded-2xl p-5 shadow-xl shadow-black/40 space-y-4">
      {/* Header & Filter */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#23283b] pb-3">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-bold text-white">
            Downstream Asset Impacts
          </h3>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            {assets.length} entities affected
          </span>
        </div>

        {/* Direction Filter Pills */}
        <div className="flex items-center gap-1 bg-[#0b0d14] border border-[#23283b] rounded-lg p-0.5 text-[11px]">
          <button
            onClick={() => setDirectionFilter('all')}
            className={`px-2.5 py-0.5 rounded transition-colors ${
              directionFilter === 'all'
                ? 'bg-indigo-500 text-white font-semibold'
                : 'text-[#8b90a6] hover:text-white'
            }`}
          >
            All ({assets.length})
          </button>
          <button
            onClick={() => setDirectionFilter('+')}
            className={`px-2.5 py-0.5 rounded transition-colors ${
              directionFilter === '+'
                ? 'bg-emerald-500 text-white font-semibold'
                : 'text-emerald-400 hover:text-white'
            }`}
          >
            + Bullish
          </button>
          <button
            onClick={() => setDirectionFilter('-')}
            className={`px-2.5 py-0.5 rounded transition-colors ${
              directionFilter === '-'
                ? 'bg-rose-500 text-white font-semibold'
                : 'text-rose-400 hover:text-white'
            }`}
          >
            − Bearish
          </button>
          <button
            onClick={() => setDirectionFilter('?')}
            className={`px-2.5 py-0.5 rounded transition-colors ${
              directionFilter === '?'
                ? 'bg-amber-500 text-white font-semibold'
                : 'text-amber-400 hover:text-white'
            }`}
          >
            ? Ambiguous
          </button>
        </div>
      </div>

      {/* Grid of Asset Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-h-[500px] overflow-y-auto pr-1">
        {filteredAssets.map((asset) => {
          const isSelected = selectedNodeId === asset.node_id
          const isPositive = asset.direction === '+'
          const isNegative = asset.direction === '-'
          const confidencePct = Math.round(asset.confidence * 100)

          return (
            <div
              key={asset.node_id}
              onClick={() => onSelectNode(asset.node_id)}
              className={`p-3.5 rounded-xl border transition-all cursor-pointer flex flex-col justify-between gap-3 ${
                isSelected
                  ? 'bg-[#181c2b] border-cyan-500 shadow-md shadow-cyan-500/10'
                  : 'bg-[#181c2b]/70 hover:bg-[#181c2b] border-[#23283b] hover:border-[#2f354f]'
              }`}
            >
              {/* Top Row: Label, Type & Direction Badge */}
              <div className="space-y-1">
                <div className="flex items-start justify-between gap-2">
                  <h4 className="text-xs font-bold text-white group-hover:text-cyan-300">
                    {asset.label}
                  </h4>
                  <span
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-mono font-bold shrink-0 ${
                      isPositive
                        ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                        : isNegative
                        ? 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                        : 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                    }`}
                  >
                    {isPositive ? (
                      <>
                        <ArrowUpRight className="w-3 h-3" /> Bullish (+)
                      </>
                    ) : isNegative ? (
                      <>
                        <ArrowDownRight className="w-3 h-3" /> Bearish (−)
                      </>
                    ) : (
                      <>
                        <HelpCircle className="w-3 h-3" /> Ambiguous (?)
                      </>
                    )}
                  </span>
                </div>
                <div className="text-[10px] text-[#8b90a6] font-mono capitalize">
                  {asset.node_type} · {asset.paths} {asset.paths === 1 ? 'causal path' : 'causal paths'}
                </div>
              </div>

              {/* Reasoning */}
              <p className="text-[11px] text-[#8b90a6] line-clamp-2 leading-relaxed">
                {asset.reasoning}
              </p>

              {/* Bottom Row: Confidence Bar & Metric */}
              <div className="space-y-1 pt-1 border-t border-[#23283b]/60">
                <div className="flex items-center justify-between text-[10px] font-mono">
                  <span className="text-[#8b90a6]">Graph Confidence</span>
                  <span className="font-bold text-[#e8eaf0]">{confidencePct}%</span>
                </div>
                <div className="w-full bg-[#0b0d14] rounded-full h-1.5 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      isPositive
                        ? 'bg-emerald-400'
                        : isNegative
                        ? 'bg-rose-400'
                        : 'bg-amber-400'
                    }`}
                    style={{ width: `${confidencePct}%` }}
                  />
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

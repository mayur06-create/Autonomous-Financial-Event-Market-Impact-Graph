import React, { useState } from 'react'
import type { PathResult, Node } from '../types'
import { GitFork, ArrowRight, ChevronRight } from 'lucide-react'

interface CausalPathsListProps {
  paths: PathResult[]
  nodes: Node[]
  onSelectNode: (nodeId: string) => void
}

export const CausalPathsList: React.FC<CausalPathsListProps> = ({
  paths,
  nodes,
  onSelectNode,
}) => {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(0)

  const nodeMap = new Map(nodes.map(n => [n.id, n]))

  if (!paths || paths.length === 0) {
    return (
      <div className="bg-[#121520] border border-[#23283b] rounded-2xl p-6 text-center text-[#8b90a6]">
        No causal propagation paths generated for this event.
      </div>
    )
  }

  return (
    <div className="bg-[#121520] border border-[#23283b] rounded-2xl p-5 shadow-xl shadow-black/40 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#23283b] pb-3">
        <div className="flex items-center gap-2">
          <GitFork className="w-4 h-4 text-indigo-400 rotate-90" />
          <h3 className="text-sm font-bold text-white">
            Propagated Causal Chains
          </h3>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            {paths.length} paths identified
          </span>
        </div>
        <span className="text-[11px] text-[#8b90a6]">
          Ranked by decayed path score
        </span>
      </div>

      {/* Path Cards List */}
      <div className="space-y-2.5 max-h-[460px] overflow-y-auto pr-1">
        {paths.map((path, idx) => {
          const isExpanded = expandedIndex === idx
          const isPositive = path.sign === '+'
          const isNegative = path.sign === '-'

          return (
            <div
              key={idx}
              className={`border rounded-xl transition-all overflow-hidden ${
                isExpanded
                  ? 'bg-[#181c2b] border-indigo-500/40 shadow-md shadow-indigo-500/5'
                  : 'bg-[#181c2b]/60 hover:bg-[#181c2b] border-[#23283b]'
              }`}
            >
              {/* Card Summary Header */}
              <button
                onClick={() => setExpandedIndex(isExpanded ? null : idx)}
                className="w-full text-left p-3 flex items-center justify-between gap-3"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  {/* Sign Pill */}
                  <span
                    className={`w-6 h-6 rounded-lg flex items-center justify-center shrink-0 text-xs font-mono font-bold ${
                      isPositive
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        : isNegative
                        ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                        : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                    }`}
                  >
                    {path.sign}
                  </span>

                  {/* Breadcrumbs */}
                  <div className="truncate">
                    <div className="text-xs font-medium text-white truncate flex items-center gap-1.5">
                      {path.nodes.map((nodeId, nIdx) => {
                        const nodeLabel = nodeMap.get(nodeId)?.label || nodeId
                        return (
                          <React.Fragment key={nodeId}>
                            <span
                              onClick={(e) => {
                                e.stopPropagation()
                                onSelectNode(nodeId)
                              }}
                              className="hover:text-cyan-400 hover:underline cursor-pointer"
                            >
                              {nodeLabel}
                            </span>
                            {nIdx < path.nodes.length - 1 && (
                              <ArrowRight className="w-3 h-3 text-[#545870] shrink-0" />
                            )}
                          </React.Fragment>
                        )
                      })}
                    </div>
                    <div className="text-[11px] text-[#8b90a6] mt-0.5 flex items-center gap-2 font-mono">
                      <span>{path.hop_count} hops</span>
                      <span>·</span>
                      <span>Score: {path.path_score.toFixed(3)}</span>
                    </div>
                  </div>
                </div>

                <ChevronRight
                  className={`w-4 h-4 text-[#8b90a6] shrink-0 transition-transform ${
                    isExpanded ? 'rotate-90' : ''
                  }`}
                />
              </button>

              {/* Expanded Mathematical & Reasoning Details */}
              {isExpanded && (
                <div className="px-3.5 pb-3.5 pt-1 border-t border-[#23283b]/60 space-y-2.5 text-xs text-[#8b90a6]">
                  {/* Explainable Formula Box */}
                  <div className="bg-[#0b0d14] border border-[#23283b] rounded-lg p-2.5 space-y-1.5 font-mono text-[11px]">
                    <div className="flex items-center justify-between text-[#e8eaf0]">
                      <span className="text-[#8b90a6]">Propagation Mechanics:</span>
                      <span className="text-cyan-400">
                        Sign = {isPositive ? '(+) Bullish' : isNegative ? '(−) Bearish' : '(?) Ambiguous'}
                      </span>
                    </div>
                    <p className="text-[#545870] text-[10px]">
                      Formula: ∏(edge midpoint) × (0.85)^({path.hop_count - 1} hops) = {path.path_score.toFixed(3)}
                    </p>
                  </div>

                  {/* Summary */}
                  <p className="text-[11px] text-[#e8eaf0] italic">
                    "{path.summary}"
                  </p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

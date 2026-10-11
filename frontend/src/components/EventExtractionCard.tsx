import React from 'react'
import type { ExtractedEvent } from '../types'
import { Sparkles, Quote, Globe, Layers, ArrowUpRight, ArrowDownRight, HelpCircle } from 'lucide-react'

interface EventExtractionCardProps {
  event: ExtractedEvent
  agreementRatio: number
  cached: boolean
}

export const EventExtractionCard: React.FC<EventExtractionCardProps> = ({
  event,
  agreementRatio,
  cached,
}) => {
  const isPositive = event.direction === '+'
  const isNegative = event.direction === '-'

  return (
    <div className="bg-[#121520] border border-[#23283b] rounded-2xl p-5 shadow-xl shadow-black/40 space-y-4">
      {/* Title & Metadata Badges */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#23283b] pb-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-indigo-400" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              Detected Financial Event
              {cached && (
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  disk-cached
                </span>
              )}
            </h3>
            <p className="text-xs text-[#8b90a6]">
              Extracted via 3-run LLM consensus · Ground truth facts mapped to seed nodes
            </p>
          </div>
        </div>

        {/* Agreement Ratio */}
        <div className="flex items-center gap-2 bg-[#181c2b] border border-[#23283b] px-3 py-1.5 rounded-xl">
          <div className="text-right">
            <div className="text-[10px] uppercase font-semibold text-[#8b90a6]">LLM Consistency</div>
            <div className="text-xs font-mono font-bold text-emerald-400">
              {(agreementRatio * 100).toFixed(0)}% Agreement
            </div>
          </div>
          <div className="w-8 h-8 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-xs text-emerald-400 font-bold">
            ✓
          </div>
        </div>
      </div>

      {/* Grid of Key Extracted Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* Event Type */}
        <div className="bg-[#181c2b] border border-[#23283b] rounded-xl p-3">
          <span className="text-[10px] uppercase font-semibold text-[#8b90a6] block mb-1">
            Event Classification
          </span>
          <span className="text-xs font-bold text-white block truncate" title={event.event_type}>
            {event.event_type}
          </span>
        </div>

        {/* Primary Anchor Node */}
        <div className="bg-[#181c2b] border border-[#23283b] rounded-xl p-3">
          <span className="text-[10px] uppercase font-semibold text-[#8b90a6] block mb-1">
            Primary Seed Node
          </span>
          <div className="flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
            <span className="text-xs font-mono font-bold text-cyan-300 truncate" title={event.primary_node}>
              {event.primary_node}
            </span>
          </div>
        </div>

        {/* Direction & Magnitude */}
        <div className="bg-[#181c2b] border border-[#23283b] rounded-xl p-3">
          <span className="text-[10px] uppercase font-semibold text-[#8b90a6] block mb-1">
            Direction & Magnitude
          </span>
          <div className="flex items-center gap-1.5">
            {isPositive ? (
              <span className="inline-flex items-center gap-1 text-emerald-400 text-xs font-bold font-mono">
                <ArrowUpRight className="w-3.5 h-3.5" /> Positive (+)
              </span>
            ) : isNegative ? (
              <span className="inline-flex items-center gap-1 text-rose-400 text-xs font-bold font-mono">
                <ArrowDownRight className="w-3.5 h-3.5" /> Negative (−)
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-amber-400 text-xs font-bold font-mono">
                <HelpCircle className="w-3.5 h-3.5" /> Ambiguous (?)
              </span>
            )}
            {event.magnitude && (
              <span className="text-[11px] text-[#8b90a6] font-mono truncate" title={event.magnitude}>
                · {event.magnitude}
              </span>
            )}
          </div>
        </div>

        {/* Region */}
        <div className="bg-[#181c2b] border border-[#23283b] rounded-xl p-3">
          <span className="text-[10px] uppercase font-semibold text-[#8b90a6] block mb-1">
            Geographic Scope
          </span>
          <div className="flex items-center gap-1.5">
            <Globe className="w-3.5 h-3.5 text-indigo-400" />
            <span className="text-xs font-semibold text-white">
              {event.region || 'India'}
            </span>
          </div>
        </div>
      </div>

      {/* Extracted Evidence Sentence Quote */}
      <div className="bg-[#0b0d14] border border-[#23283b] rounded-xl p-3.5 relative overflow-hidden">
        <div className="flex items-start gap-3">
          <Quote className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#8b90a6]">
              Ground-Truth Fact Quoted from Source Article
            </span>
            <p className="text-xs text-[#e8eaf0] italic leading-relaxed">
              "{event.evidence_sentence}"
            </p>
          </div>
        </div>
      </div>

      {/* Linked vs Unlinked Entities */}
      <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
        <span className="text-[#8b90a6] text-[11px]">Mapped Seed Entities:</span>
        {event.entities.map((ent) => (
          <span
            key={ent}
            className="px-2 py-0.5 rounded-md bg-[#181c2b] border border-[#23283b] text-[#e8eaf0] font-mono text-[11px]"
          >
            {ent}
          </span>
        ))}
        {event.unlinked_entities.length > 0 && (
          <>
            <span className="text-amber-400 text-[11px] ml-2">Unlinked (Excluded):</span>
            {event.unlinked_entities.map((unl) => (
              <span
                key={unl}
                className="px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/20 text-amber-300 font-mono text-[11px]"
              >
                {unl}
              </span>
            ))}
          </>
        )}
      </div>
    </div>
  )
}

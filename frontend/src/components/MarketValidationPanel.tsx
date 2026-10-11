import React from 'react'
import type { ValidationResult } from '../types'
import { CheckCircle2, XCircle, AlertTriangle, BarChart3, HelpCircle } from 'lucide-react'

interface MarketValidationPanelProps {
  validations: ValidationResult[]
}

export const MarketValidationPanel: React.FC<MarketValidationPanelProps> = ({
  validations,
}) => {
  if (!validations || validations.length === 0) {
    return null
  }

  return (
    <div className="bg-[#121520] border border-[#23283b] rounded-2xl p-5 shadow-xl shadow-black/40 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#23283b] pb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-cyan-400" />
          <h3 className="text-sm font-bold text-white">
            Empirical Market Model Validation (Event Study)
          </h3>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            {validations.length} tickers tested
          </span>
        </div>
        <span className="text-[11px] text-[#8b90a6]">
          OLS Estimation Window: 80 Days · Event Window: [-1, +3] Days
        </span>
      </div>

      {/* Caveat Alert */}
      <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-3 flex items-start gap-2.5 text-xs text-amber-300">
        <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400 mt-0.5" />
        <p className="leading-relaxed">
          <strong className="font-semibold text-amber-200">Indicative Signal Only:</strong> Macro shocks influence the benchmark index itself (Nifty 50), which dampens the observable abnormal return (CAR). Market data cross-checks directional alignment but does not prove exclusive causality.
        </p>
      </div>

      {/* Validation Results Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {validations.map((v) => {
          const hasCar = v.car !== null && v.car !== undefined
          const carPct = hasCar ? (v.car! * 100).toFixed(2) : 'N/A'
          const isCarPositive = hasCar && v.car! > 0

          return (
            <div
              key={v.ticker}
              className="bg-[#181c2b] border border-[#23283b] rounded-xl p-3.5 space-y-2"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs font-bold text-white block">{v.node_id}</span>
                  <span className="text-[10px] font-mono text-[#8b90a6]">{v.ticker}</span>
                </div>
                {v.direction_match === true ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    <CheckCircle2 className="w-3 h-3" /> Direction Agrees
                  </span>
                ) : v.direction_match === false ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">
                    <XCircle className="w-3 h-3" /> Divergence
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold bg-[#23283b] text-[#8b90a6]">
                    <HelpCircle className="w-3 h-3" /> Inconclusive
                  </span>
                )}
              </div>

              <div className="flex items-center justify-between text-xs font-mono pt-1 border-t border-[#23283b]/60">
                <span className="text-[#8b90a6]">Cumulative Abnormal Return:</span>
                <span className={`font-bold ${isCarPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {hasCar ? `${carPct}%` : 'No data'}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

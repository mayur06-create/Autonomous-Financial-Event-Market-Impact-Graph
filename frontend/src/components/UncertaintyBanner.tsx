import React from 'react'
import type { UncertaintyNote } from '../types'
import { ShieldAlert } from 'lucide-react'

interface UncertaintyBannerProps {
  note: UncertaintyNote
}

export const UncertaintyBanner: React.FC<UncertaintyBannerProps> = ({ note }) => {
  return (
    <div className="bg-[#121520] border border-[#23283b] rounded-2xl p-4 shadow-lg space-y-2">
      <div className="flex items-center gap-2">
        <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
        <h4 className="text-xs font-bold text-white uppercase tracking-wider">
          {note.headline || 'Epistemic & Uncertainty Boundaries'}
        </h4>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5 pt-1">
        {note.details.map((detail, idx) => (
          <div
            key={idx}
            className="bg-[#181c2b] border border-[#23283b] rounded-xl p-2.5 text-[11px] text-[#8b90a6] leading-relaxed flex items-start gap-2"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400/80 mt-1.5 shrink-0" />
            <span>{detail}</span>
          </div>
        ))}
      </div>

      <p className="text-[10px] text-[#545870] italic pt-1 text-center">
        Market Impact Graph produces plausible structural scenarios based on macro causal mechanics. It does not issue financial advice or guaranteed market forecasts.
      </p>
    </div>
  )
}

import React from 'react'
import { TrendingDown, TrendingUp, CircleDollarSign, Droplets, Layers, ArrowRight } from 'lucide-react'
import { INITIAL_TICKER_DATA, type MarketInstrument } from '../data/marketTickerData'

interface SparklineProps {
  data: number[]
  isPositive: boolean
  width?: number
  height?: number
  id: string
}

const SparklineChart: React.FC<SparklineProps> = ({
  data,
  isPositive,
  width = 68,
  height = 30,
  id,
}) => {
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const padding = 2

  const points = data.map((val, idx) => {
    const x = padding + (idx / (data.length - 1)) * (width - padding * 2)
    const y = height - padding - ((val - min) / range) * (height - padding * 2)
    return { x, y }
  })

  // Build SVG path
  const pathD = points.reduce((acc, pt, idx) => {
    return idx === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`
  }, '')

  // Area path for gradient fill
  const areaD = `${pathD} L ${width - padding} ${height} L ${padding} ${height} Z`

  const strokeColor = isPositive ? '#10B981' : '#F52D3D'
  const gradientId = `gradient-${id}`

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="overflow-visible shrink-0"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={strokeColor} stopOpacity={0.35} />
          <stop offset="100%" stopColor={strokeColor} stopOpacity={0.0} />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#${gradientId})`} />
      <path
        d={pathD}
        fill="none"
        stroke={strokeColor}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

interface MarketTickerPanelProps {
  onViewAll?: () => void
}

export const MarketTickerPanel: React.FC<MarketTickerPanelProps> = ({ onViewAll }) => {
  const getInstrumentIcon = (item: MarketInstrument) => {
    switch (item.iconType) {
      case 'chart-down':
        return (
          <div className="w-9 h-9 rounded-xl bg-[#2a1218] border border-red-500/25 flex items-center justify-center shrink-0 shadow-sm shadow-red-500/10">
            <TrendingDown className="w-4 h-4 text-[#F52D3D]" />
          </div>
        )
      case 'chart-up':
        return (
          <div className="w-9 h-9 rounded-xl bg-[#0f281e] border border-emerald-500/25 flex items-center justify-center shrink-0 shadow-sm shadow-emerald-500/10">
            <TrendingUp className="w-4 h-4 text-[#10B981]" />
          </div>
        )
      case 'gold':
        return (
          <div className="w-9 h-9 rounded-xl bg-[#2e2311] border border-amber-500/25 flex items-center justify-center shrink-0 shadow-sm shadow-amber-500/10">
            <Layers className="w-4 h-4 text-[#EAB308]" />
          </div>
        )
      case 'oil':
        return (
          <div className="w-9 h-9 rounded-xl bg-[#2a170f] border border-orange-500/25 flex items-center justify-center shrink-0 shadow-sm shadow-orange-500/10">
            <Droplets className="w-4 h-4 text-[#F97316]" />
          </div>
        )
      case 'forex':
        return (
          <div className="w-9 h-9 rounded-xl bg-[#0e271f] border border-emerald-500/25 flex items-center justify-center shrink-0 shadow-sm shadow-emerald-500/10">
            <CircleDollarSign className="w-4 h-4 text-[#10B981]" />
          </div>
        )
    }
  }

  return (
    <div className="w-full bg-[#0a0d18]/85 backdrop-blur-xl border border-white/10 rounded-2xl p-2.5 sm:p-3 shadow-2xl shadow-black/80">
      <div className="flex items-center gap-2 sm:gap-4 overflow-x-auto no-scrollbar scroll-smooth divide-x divide-white/5">
        {INITIAL_TICKER_DATA.map((item) => (
          <div
            key={item.id}
            className="flex items-center gap-3 px-3 py-1 shrink-0 transition-transform duration-200 hover:scale-[1.02]"
          >
            {getInstrumentIcon(item)}

            <div className="min-w-[95px]">
              <div className="flex items-center gap-1">
                <span className="text-xs font-semibold text-gray-200 tracking-wide">
                  {item.name}
                </span>
                <span
                  className={`text-[11px] font-bold ${
                    item.isPositive ? 'text-[#10B981]' : 'text-[#F52D3D]'
                  }`}
                >
                  {item.isPositive ? '↑' : '↓'}
                </span>
              </div>
              <div className="text-sm sm:text-[15px] font-bold text-white tracking-tight leading-tight">
                {item.price}
              </div>
              <div
                className={`text-[11px] font-medium leading-tight ${
                  item.isPositive ? 'text-[#10B981]' : 'text-[#F52D3D]'
                }`}
              >
                {item.change} ({item.changePercent})
              </div>
            </div>

            <div className="pl-1">
              <SparklineChart
                id={item.id}
                data={item.sparkline}
                isPositive={item.isPositive}
              />
            </div>
          </div>
        ))}

        {/* View All link */}
        <div className="pl-4 pr-3 shrink-0 flex items-center">
          <button
            onClick={onViewAll}
            className="flex items-center gap-1 text-xs font-semibold text-gray-400 hover:text-white transition-colors group cursor-pointer"
          >
            <span>View All</span>
            <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-1" />
          </button>
        </div>
      </div>
    </div>
  )
}

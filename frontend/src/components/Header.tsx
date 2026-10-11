import React from 'react'
import { Activity, Database, History, Sparkles } from 'lucide-react'

interface HeaderProps {
  backendStatus: 'checking' | 'ok' | 'error'
  backendVersion?: string
  demoMode: boolean
  setDemoMode: (val: boolean) => void
  onOpenSeedGraph: () => void
  onOpenBacktest: () => void
}

export const Header: React.FC<HeaderProps> = ({
  backendStatus,
  backendVersion,
  demoMode,
  setDemoMode,
  onOpenSeedGraph,
  onOpenBacktest,
}) => {
  return (
    <header className="border-b border-[#23283b] bg-[#121520]/80 backdrop-blur-md sticky top-0 z-40 px-4 lg:px-8 py-3">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
        {/* Brand & Subtitle */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 via-blue-600 to-cyan-400 p-[1px] shadow-lg shadow-indigo-500/20">
            <div className="w-full h-full bg-[#0d0f17] rounded-[11px] flex items-center justify-center">
              <Activity className="w-5 h-5 text-cyan-400 animate-pulse" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                Market Impact Graph
                <span className="text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                  HackWave 3.0 · PS5
                </span>
              </h1>
            </div>
            <p className="text-xs text-[#8b90a6]">
              Explainable Causal Propagation for Indian Macro & Financial Markets
            </p>
          </div>
        </div>

        {/* Action Controls & Health */}
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Demo Mode Toggle */}
          <button
            onClick={() => setDemoMode(!demoMode)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
              demoMode
                ? 'bg-amber-500/10 border-amber-500/30 text-amber-300 hover:bg-amber-500/20 shadow-sm shadow-amber-500/10'
                : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20'
            }`}
            title={demoMode ? "Demo Mode uses pre-cached human-authored extractions" : "Live mode calls Gemini LLM"}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{demoMode ? 'Demo Mode (Cached)' : 'Live LLM Mode'}</span>
          </button>

          {/* Seed Graph Explorer Modal Trigger */}
          <button
            onClick={onOpenSeedGraph}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#181c2b] hover:bg-[#21263a] border border-[#23283b] text-[#e8eaf0] transition-colors"
          >
            <Database className="w-3.5 h-3.5 text-blue-400" />
            <span className="hidden sm:inline">Seed Graph</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-blue-500/20 text-blue-300">47 edges</span>
          </button>

          {/* Historical Backtest Modal Trigger */}
          <button
            onClick={onOpenBacktest}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#181c2b] hover:bg-[#21263a] border border-[#23283b] text-[#e8eaf0] transition-colors"
          >
            <History className="w-3.5 h-3.5 text-purple-400" />
            <span className="hidden sm:inline">Backtest</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-purple-500/20 text-purple-300">10 Events</span>
          </button>

          {/* Backend Status Badge */}
          <div
            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs border ${
              backendStatus === 'ok'
                ? 'bg-[#181c2b] border-emerald-500/20 text-emerald-400'
                : backendStatus === 'checking'
                ? 'bg-[#181c2b] border-amber-500/20 text-amber-400'
                : 'bg-[#181c2b] border-rose-500/20 text-rose-400'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                backendStatus === 'ok'
                  ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]'
                  : backendStatus === 'checking'
                  ? 'bg-amber-400 animate-ping'
                  : 'bg-rose-400'
              }`}
            />
            <span className="font-mono text-[11px]">
              {backendStatus === 'ok'
                ? `FastAPI ${backendVersion || 'v0.8.0'}`
                : backendStatus === 'checking'
                ? 'Connecting…'
                : 'Offline'}
            </span>
          </div>
        </div>
      </div>
    </header>
  )
}

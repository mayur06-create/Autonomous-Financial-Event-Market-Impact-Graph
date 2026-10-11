import React, { useState } from 'react'
import { SAMPLE_ARTICLES } from '../sampleNews'
import type { SampleArticle } from '../types'
import { Play, RotateCcw, Calendar, FileText, ChevronDown, ChevronUp, Fuel, Landmark, TrendingDown, Flame } from 'lucide-react'

interface NewsInputPanelProps {
  newsText: string
  setNewsText: (text: string) => void
  eventDate: string
  setEventDate: (date: string) => void
  onAnalyze: () => void
  loading: boolean
  activePresetId: string | null
  setActivePresetId: (id: string | null) => void
}

export const NewsInputPanel: React.FC<NewsInputPanelProps> = ({
  newsText,
  setNewsText,
  eventDate,
  setEventDate,
  onAnalyze,
  loading,
  activePresetId,
  setActivePresetId,
}) => {
  const [showAdvanced, setShowAdvanced] = useState(false)

  const handleSelectSample = (sample: SampleArticle) => {
    setActivePresetId(sample.id)
    setNewsText(sample.text)
    setEventDate(sample.date)
  }

  const handleClear = () => {
    setActivePresetId(null)
    setNewsText('')
    setEventDate('')
  }

  const getIcon = (id: string) => {
    switch (id) {
      case '01_opec_cut': return <Fuel className="w-4 h-4 text-amber-400" />
      case '02_rbi_rate_hike': return <Landmark className="w-4 h-4 text-purple-400" />
      case '03_inr_depreciation': return <TrendingDown className="w-4 h-4 text-cyan-400" />
      case '04_inflation_spike': return <Flame className="w-4 h-4 text-rose-400" />
      default: return <FileText className="w-4 h-4 text-indigo-400" />
    }
  }

  const wordCount = newsText.trim() ? newsText.trim().split(/\s+/).length : 0
  const charCount = newsText.length

  return (
    <div className="bg-[#121520] border border-[#23283b] rounded-2xl p-5 shadow-xl shadow-black/40 space-y-4">
      {/* Preset Scenario Selector Bar */}
      <div>
        <div className="flex items-center justify-between mb-2.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-[#8b90a6] flex items-center gap-2">
            <span>Benchmark Hackathon Scenarios</span>
            <span className="text-[10px] lowercase px-2 py-0.5 rounded bg-[#181c2b] text-[#545870] font-normal border border-[#23283b]">
              click to load
            </span>
          </label>
          {newsText && (
            <button
              onClick={handleClear}
              className="text-xs text-[#8b90a6] hover:text-white flex items-center gap-1 transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Clear Text</span>
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
          {SAMPLE_ARTICLES.map((sample) => {
            const isSelected = activePresetId === sample.id
            return (
              <button
                key={sample.id}
                onClick={() => handleSelectSample(sample)}
                className={`flex flex-col text-left p-3 rounded-xl border transition-all relative overflow-hidden group ${
                  isSelected
                    ? 'bg-gradient-to-br from-indigo-500/15 to-blue-600/10 border-indigo-500/50 shadow-md shadow-indigo-500/10'
                    : 'bg-[#181c2b] hover:bg-[#21263a] border-[#23283b] hover:border-[#2f354f]'
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5">
                    {getIcon(sample.id)}
                    <span className="text-[11px] font-semibold text-[#e8eaf0] truncate">
                      {sample.tag}
                    </span>
                  </div>
                  <span className="text-[10px] text-[#545870] font-mono">
                    {sample.date.slice(0, 7)}
                  </span>
                </div>
                <p className="text-xs font-medium text-white line-clamp-1 group-hover:text-cyan-300 transition-colors">
                  {sample.title}
                </p>
                <p className="text-[11px] text-[#8b90a6] line-clamp-2 mt-1 leading-snug">
                  {sample.description}
                </p>
                {isSelected && (
                  <div className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-indigo-400 shadow-[0_0_6px_rgba(99,102,241,1)]" />
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* News Text Area */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-[#8b90a6]">
          <span className="font-medium text-white flex items-center gap-2">
            Financial News Text / Article
          </span>
          <div className="flex items-center gap-3 text-[11px] font-mono">
            <span>{wordCount} words</span>
            <span>·</span>
            <span className={charCount < 50 ? 'text-amber-400' : 'text-[#8b90a6]'}>
              {charCount} / 20,000 chars {charCount < 50 && '(min 50 required)'}
            </span>
          </div>
        </div>

        <textarea
          value={newsText}
          onChange={(e) => {
            setNewsText(e.target.value)
            if (activePresetId) setActivePresetId(null)
          }}
          placeholder="Paste financial news article here (e.g., RBI monetary policy announcement, crude oil spike, trade balance deficit, Fed rate decision)..."
          rows={5}
          className="w-full bg-[#0b0d14] border border-[#23283b] focus:border-indigo-500 rounded-xl p-3.5 text-sm text-[#e8eaf0] placeholder-[#545870] outline-none transition-all font-sans resize-y focus:ring-1 focus:ring-indigo-500/50"
        />
      </div>

      {/* Advanced Bar & Run Action */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs text-[#8b90a6] hover:text-[#e8eaf0] flex items-center gap-1 transition-colors"
          >
            <span>Market Validation Date (Optional)</span>
            {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

          {showAdvanced && (
            <div className="flex items-center gap-2 bg-[#0b0d14] border border-[#23283b] rounded-lg px-2.5 py-1 text-xs">
              <Calendar className="w-3.5 h-3.5 text-[#8b90a6]" />
              <input
                type="date"
                value={eventDate}
                onChange={(e) => setEventDate(e.target.value)}
                className="bg-transparent text-white outline-none font-mono text-xs"
              />
            </div>
          )}
        </div>

        {/* Action Button */}
        <button
          onClick={onAnalyze}
          disabled={loading || charCount < 50}
          className={`flex items-center gap-2 px-6 py-2.5 rounded-xl font-semibold text-sm transition-all shadow-lg ${
            loading || charCount < 50
              ? 'bg-[#181c2b] text-[#545870] border border-[#23283b] cursor-not-allowed shadow-none'
              : 'bg-gradient-to-r from-indigo-500 via-blue-600 to-cyan-500 text-white hover:brightness-110 shadow-indigo-500/25 hover:shadow-cyan-500/30 active:scale-[0.98]'
          }`}
        >
          {loading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/20 border-t-white rounded-full animate-spin" />
              <span>Propagating Causal Graph…</span>
            </>
          ) : (
            <>
              <Play className="w-4 h-4 fill-white" />
              <span>Propagate Market Impact</span>
            </>
          )}
        </button>
      </div>
    </div>
  )
}

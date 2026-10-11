import { useState, useEffect, useCallback } from 'react'
import { MarketPulseNav } from './components/MarketPulseNav'
import { HeroSection } from './components/HeroSection'
import { NewsInputPanel } from './components/NewsInputPanel'
import { EventExtractionCard } from './components/EventExtractionCard'
import { GraphCanvas } from './components/GraphCanvas'
import { CausalPathsList } from './components/CausalPathsList'
import { AffectedAssetsGrid } from './components/AffectedAssetsGrid'
import { MarketValidationPanel } from './components/MarketValidationPanel'
import { UncertaintyBanner } from './components/UncertaintyBanner'
import { SeedGraphModal } from './components/SeedGraphModal'
import { BacktestModal } from './components/BacktestModal'
import { SAMPLE_ARTICLES } from './sampleNews'
import type { ImpactGraph } from './types'
import { AlertCircle, Share2, Cpu } from 'lucide-react'

const API_BASE = '' // Use relative URLs → Vite proxy → 127.0.0.1:8000 (fixes Windows IPv6/IPv4 mismatch)

export default function App() {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'ok' | 'error'>('checking')
  const [backendVersion, setBackendVersion] = useState<string>('0.8.0')
  const [demoMode, setDemoMode] = useState<boolean>(true)

  // Default to first sample article
  const defaultSample = SAMPLE_ARTICLES[0]
  const [newsText, setNewsText] = useState<string>(defaultSample.text)
  const [eventDate, setEventDate] = useState<string>(defaultSample.date)
  const [activePresetId, setActivePresetId] = useState<string | null>(defaultSample.id)

  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [impactData, setImpactData] = useState<ImpactGraph | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  // Modals
  const [isSeedGraphOpen, setIsSeedGraphOpen] = useState<boolean>(false)
  const [isBacktestOpen, setIsBacktestOpen] = useState<boolean>(false)

  // Check backend health — polls every 10 seconds so it auto-reconnects
  useEffect(() => {
    const checkHealth = () => {
      fetch(`${API_BASE}/health`)
        .then(res => {
          if (res.ok) {
            setBackendStatus('ok')
            return res.json()
          }
          throw new Error('Health check failed')
        })
        .then(data => {
          if (data.version) setBackendVersion(data.version)
        })
        .catch(() => setBackendStatus('error'))
    }
    checkHealth()
    const interval = setInterval(checkHealth, 10000)
    return () => clearInterval(interval)
  }, [])

  // Analyze function
  const handleAnalyze = useCallback(async () => {
    if (!newsText.trim() || newsText.length < 50) return

    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          news_text: newsText,
          demo_mode: demoMode,
          event_date: eventDate.trim() || null,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `Server error: HTTP ${response.status}`)
      }

      const data: ImpactGraph = await response.json()
      setImpactData(data)
      if (data.event?.primary_node) {
        setSelectedNodeId(data.event.primary_node)
      }
    } catch (err: any) {
      setError(err.message || 'Failed to analyze news event.')
    } finally {
      setLoading(false)
    }
  }, [newsText, demoMode, eventDate])

  // Run initial analysis on load
  useEffect(() => {
    handleAnalyze()
  }, [])

  const [activeTab, setActiveTab] = useState<string>('Markets')

  const scrollToSection = (id: string) => {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' })
    }
  }

  // Copy summary to clipboard
  const handleCopySummary = () => {
    if (!impactData) return
    const summary = `Market Impact Graph Analysis:
Event: ${impactData.event.event_type} (${impactData.event.direction})
Primary Anchor: ${impactData.event.primary_node}
Top Paths: ${impactData.top_paths.length}
Affected Entities: ${impactData.affected_assets.map(a => `${a.label} (${a.direction})`).join(', ')}
Agreement Ratio: ${(impactData.agreement_ratio * 100).toFixed(0)}%`
    navigator.clipboard.writeText(summary)
    alert('Analysis summary copied to clipboard!')
  }

  return (
    <div className="min-h-screen bg-[#0b0d14] text-[#e8eaf0] flex flex-col font-sans selection:bg-[#F52D3D]/30 selection:text-white">
      {/* Premium Dark Navigation Bar */}
      <MarketPulseNav
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        backendStatus={backendStatus}
        backendVersion={backendVersion}
        demoMode={demoMode}
        setDemoMode={setDemoMode}
        onOpenSeedGraph={() => setIsSeedGraphOpen(true)}
        onOpenBacktest={() => setIsBacktestOpen(true)}
        onNavigateSection={scrollToSection}
      />

      {/* Opening Hero Section with Blurred Background & Live Market Ticker */}
      <HeroSection
        onExploreMarkets={() => scrollToSection('analysis-section')}
        onLatestNews={() => scrollToSection('news-section')}
        onViewAllInstruments={() => scrollToSection('portfolio-section')}
      />

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 lg:px-8 py-8 space-y-8">
        {/* Error Alert if any */}
        {error && (
          <div className="bg-rose-500/10 border border-rose-500/30 rounded-2xl p-4 text-xs text-rose-300 flex items-start gap-3 shadow-lg">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <strong className="font-bold text-rose-200">Analysis Error</strong>
              <p>{error}</p>
              {backendStatus === 'error' && (
                <p className="text-[#8b90a6] text-[11px] mt-1 font-mono">
                  Make sure the FastAPI backend is running on http://localhost:8000 (.venv\Scripts\uvicorn app.main:app)
                </p>
              )}
            </div>
          </div>
        )}

        {/* Input & Scenario Selector */}
        <section id="news-section" className="scroll-mt-20">
          <NewsInputPanel
            newsText={newsText}
            setNewsText={setNewsText}
            eventDate={eventDate}
            setEventDate={setEventDate}
            onAnalyze={handleAnalyze}
            loading={loading}
            activePresetId={activePresetId}
            setActivePresetId={setActivePresetId}
          />
        </section>

        {/* Results Section */}
        {impactData && (
          <section id="analysis-section" className="space-y-6 animate-in fade-in duration-300 scroll-mt-20">
            {/* 1. Extraction Explainability Card */}
            <EventExtractionCard
              event={impactData.event}
              agreementRatio={impactData.agreement_ratio}
              cached={impactData.cached}
            />

            {/* 2. Visualizations Layout (Graph & Causal Chains) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column: Interactive Graph Canvas (7 cols) */}
              <div className="lg:col-span-7 space-y-4">
                <GraphCanvas
                  nodes={impactData.nodes}
                  edges={impactData.edges}
                  primaryNodeId={impactData.event.primary_node}
                  selectedNodeId={selectedNodeId}
                  setSelectedNodeId={setSelectedNodeId}
                />
              </div>

              {/* Right Column: Causal Paths Step-by-Step (5 cols) */}
              <div className="lg:col-span-5 space-y-4">
                <CausalPathsList
                  paths={impactData.top_paths}
                  nodes={impactData.nodes}
                  onSelectNode={(nodeId) => setSelectedNodeId(nodeId)}
                />
              </div>
            </div>

            {/* 3. Affected Assets & Sectors Matrix */}
            <div id="portfolio-section" className="scroll-mt-20">
              <AffectedAssetsGrid
                assets={impactData.affected_assets}
                onSelectNode={(nodeId) => setSelectedNodeId(nodeId)}
                selectedNodeId={selectedNodeId}
              />
            </div>

            {/* 4. Empirical Market Model Event Study (if event_date provided) */}
            {impactData.validation && impactData.validation.length > 0 && (
              <MarketValidationPanel validations={impactData.validation} />
            )}

            {/* 5. Epistemic Uncertainty & Hackathon Disclaimer */}
            {impactData.uncertainty_note && (
              <UncertaintyBanner note={impactData.uncertainty_note} />
            )}

            {/* Action Bar */}
            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={handleCopySummary}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium bg-[#181c2b] hover:bg-[#21263a] border border-[#23283b] text-[#e8eaf0] transition-colors cursor-pointer"
              >
                <Share2 className="w-3.5 h-3.5 text-[#F52D3D]" />
                <span>Copy Scenario Summary</span>
              </button>
            </div>
          </section>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-[#23283b] bg-[#121520] py-6 px-4 lg:px-8 mt-12">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-[#8b90a6]">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-indigo-400" />
            <span>Market Impact Graph · HackWave 3.0 PS5 Submission</span>
          </div>
          <div className="flex items-center gap-4 text-[11px]">
            <span>FastAPI Backend</span>
            <span>·</span>
            <span>Gemini Self-Consistency Consensus</span>
            <span>·</span>
            <span>NetworkX Causal DiGraph</span>
            <span>·</span>
            <span>React + Tailwind v4 + Force Graph</span>
          </div>
        </div>
      </footer>

      {/* Modals */}
      <SeedGraphModal
        isOpen={isSeedGraphOpen}
        onClose={() => setIsSeedGraphOpen(false)}
      />

      <BacktestModal
        isOpen={isBacktestOpen}
        onClose={() => setIsBacktestOpen(false)}
      />
    </div>
  )
}

import React, { useState } from 'react'
import {
  TrendingUp,
  Search,
  Bell,
  User,
  Menu,
  X,
  Sparkles,
  Database,
  History,
  SlidersHorizontal,
} from 'lucide-react'

interface MarketPulseNavProps {
  activeTab?: string
  setActiveTab?: (tab: string) => void
  backendStatus: 'checking' | 'ok' | 'error'
  backendVersion?: string
  demoMode: boolean
  setDemoMode: (val: boolean) => void
  onOpenSeedGraph: () => void
  onOpenBacktest: () => void
  onNavigateSection?: (sectionId: string) => void
}

export const MarketPulseNav: React.FC<MarketPulseNavProps> = ({
  activeTab = 'Markets',
  setActiveTab,
  backendStatus,
  backendVersion = '0.8.0',
  demoMode,
  setDemoMode,
  onOpenSeedGraph,
  onOpenBacktest,
  onNavigateSection,
}) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  const navLinks = [
    { name: 'Markets', targetId: 'markets-section' },
    { name: 'News', targetId: 'news-section' },
    { name: 'Analysis', targetId: 'analysis-section' },
    { name: 'Portfolio', targetId: 'portfolio-section' },
    { name: 'Tools', targetId: 'tools' },
  ]

  const handleNavClick = (link: { name: string; targetId: string }) => {
    if (setActiveTab) setActiveTab(link.name)
    if (link.name === 'Tools') {
      setToolsOpen(!toolsOpen)
      return
    }
    if (link.targetId && onNavigateSection) {
      onNavigateSection(link.targetId)
    }
    setMobileMenuOpen(false)
  }

  return (
    <header className="sticky top-0 z-50 w-full bg-[#070a14]/90 backdrop-blur-md border-b border-white/10 transition-colors">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Brand Logo & Name */}
        <div
          onClick={() => onNavigateSection && onNavigateSection('hero-section')}
          className="flex items-center gap-2.5 cursor-pointer shrink-0 select-none group"
        >
          <div className="w-8 h-8 rounded-lg bg-[#271016] border border-[#F52D3D]/30 flex items-center justify-center shadow-md shadow-red-500/10 group-hover:border-[#F52D3D]/60 transition-colors">
            <TrendingUp className="w-4 h-4 text-[#F52D3D] transition-transform group-hover:scale-110" />
          </div>
          <span className="text-lg font-extrabold tracking-wider font-sans">
            <span className="text-white">MARKET</span>
            <span className="text-[#F52D3D]">PULSE</span>
          </span>
        </div>

        {/* Desktop Navigation Links */}
        <nav className="hidden md:flex items-center space-x-1 lg:space-x-3 text-sm font-medium">
          {navLinks.map((link) => {
            const isActive = activeTab === link.name
            return (
              <button
                key={link.name}
                onClick={() => handleNavClick(link)}
                className={`px-3 py-1.5 transition-colors relative cursor-pointer ${
                  isActive
                    ? 'text-white font-semibold'
                    : 'text-[#9ca3af] hover:text-white'
                }`}
              >
                {link.name}
                {isActive && (
                  <span className="absolute bottom-[-16px] left-0 right-0 h-[2.5px] bg-[#F52D3D] rounded-t-full shadow-[0_0_8px_rgba(245,45,61,0.7)]" />
                )}
              </button>
            )
          })}
        </nav>

        {/* Right Controls: Search bar, Notification, Profile, Status */}
        <div className="flex items-center gap-3">
          {/* Search bar */}
          <div className="relative hidden sm:block w-48 lg:w-64">
            <Search className="w-3.5 h-3.5 text-[#6b7280] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search stocks, indices, news..."
              className="w-full bg-[#111625] border border-white/10 rounded-full pl-8 pr-3 py-1.5 text-xs text-white placeholder-[#6b7280] focus:outline-none focus:border-[#F52D3D]/60 transition-colors"
            />
          </div>

          {/* Tools Menu Popover Trigger */}
          <div className="relative">
            <button
              onClick={() => setToolsOpen(!toolsOpen)}
              className="p-1.5 rounded-lg text-[#9ca3af] hover:text-white hover:bg-white/5 border border-transparent hover:border-white/10 transition-colors cursor-pointer"
              title="System Tools & Settings"
            >
              <SlidersHorizontal className="w-4 h-4" />
            </button>

            {toolsOpen && (
              <div className="absolute right-0 mt-2 w-64 bg-[#0d111e] border border-white/15 rounded-xl shadow-2xl p-3 space-y-2 z-50 text-xs animate-in fade-in zoom-in-95">
                <div className="font-semibold text-gray-300 pb-1 border-b border-white/10 flex items-center justify-between">
                  <span>Intelligence Controls</span>
                  <span className="text-[10px] text-gray-400 font-mono">v{backendVersion}</span>
                </div>

                {/* Demo Mode Toggle */}
                <button
                  onClick={() => setDemoMode(!demoMode)}
                  className={`w-full flex items-center justify-between p-2 rounded-lg border transition-all cursor-pointer ${
                    demoMode
                      ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                      : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                  }`}
                >
                  <span className="flex items-center gap-1.5 font-medium">
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>{demoMode ? 'Cached Demo Mode' : 'Live Gemini LLM'}</span>
                  </span>
                  <span className="text-[10px] underline">Toggle</span>
                </button>

                {/* Seed Graph trigger */}
                <button
                  onClick={() => {
                    onOpenSeedGraph()
                    setToolsOpen(false)
                  }}
                  className="w-full flex items-center justify-between p-2 rounded-lg bg-[#161b2b] hover:bg-[#1e253c] text-gray-200 border border-white/5 transition-colors cursor-pointer"
                >
                  <span className="flex items-center gap-1.5">
                    <Database className="w-3.5 h-3.5 text-blue-400" />
                    <span>Explore Seed Graph</span>
                  </span>
                  <span className="text-[10px] text-blue-400 font-mono">47 edges</span>
                </button>

                {/* Backtest modal trigger */}
                <button
                  onClick={() => {
                    onOpenBacktest()
                    setToolsOpen(false)
                  }}
                  className="w-full flex items-center justify-between p-2 rounded-lg bg-[#161b2b] hover:bg-[#1e253c] text-gray-200 border border-white/5 transition-colors cursor-pointer"
                >
                  <span className="flex items-center gap-1.5">
                    <History className="w-3.5 h-3.5 text-purple-400" />
                    <span>Event Backtest Suite</span>
                  </span>
                  <span className="text-[10px] text-purple-400 font-mono">10 Events</span>
                </button>
              </div>
            )}
          </div>

          {/* Notification Bell with Red Dot */}
          <button
            className="relative p-1.5 rounded-lg text-[#9ca3af] hover:text-white hover:bg-white/5 transition-colors cursor-pointer"
            title="Notifications"
          >
            <Bell className="w-4 h-4" />
            <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-[#F52D3D] shadow-[0_0_6px_#F52D3D]" />
          </button>

          {/* User Profile Icon */}
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-[#1b2234] to-[#2a344e] border border-white/20 flex items-center justify-center text-gray-300 hover:text-white cursor-pointer transition-colors shadow-inner">
            <User className="w-4 h-4" />
          </div>

          {/* Backend Status indicator badge */}
          <div
            className={`hidden xl:flex items-center gap-1.5 px-2 py-1 rounded-full text-[11px] font-mono border ${
              backendStatus === 'ok'
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                : backendStatus === 'checking'
                ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
            }`}
            title={`Backend: ${backendStatus}`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                backendStatus === 'ok'
                  ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]'
                  : backendStatus === 'checking'
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-rose-400'
              }`}
            />
            <span>{backendStatus === 'ok' ? 'API Online' : backendStatus === 'checking' ? 'Connecting' : 'Offline'}</span>
          </div>

          {/* Mobile Menu Button */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="md:hidden p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-white/10 bg-[#090d19] px-4 py-4 space-y-3">
          <div className="relative mb-3">
            <Search className="w-3.5 h-3.5 text-[#6b7280] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search stocks, indices, news..."
              className="w-full bg-[#111625] border border-white/10 rounded-lg pl-8 pr-3 py-2 text-xs text-white"
            />
          </div>

          <div className="grid grid-cols-2 gap-2 text-sm font-medium">
            {navLinks.map((link) => (
              <button
                key={link.name}
                onClick={() => handleNavClick(link)}
                className={`text-left px-3 py-2 rounded-lg transition-colors ${
                  activeTab === link.name
                    ? 'bg-[#F52D3D]/15 text-[#F52D3D] font-bold border border-[#F52D3D]/30'
                    : 'text-gray-300 hover:bg-white/5'
                }`}
              >
                {link.name}
              </button>
            ))}
          </div>

          <div className="pt-2 border-t border-white/10 flex items-center justify-between text-xs">
            <button
              onClick={() => {
                onOpenSeedGraph()
                setMobileMenuOpen(false)
              }}
              className="px-3 py-1.5 rounded-lg bg-[#161b2b] text-blue-400 border border-white/5"
            >
              Seed Graph
            </button>
            <button
              onClick={() => {
                onOpenBacktest()
                setMobileMenuOpen(false)
              }}
              className="px-3 py-1.5 rounded-lg bg-[#161b2b] text-purple-400 border border-white/5"
            >
              Backtest Suite
            </button>
            <button
              onClick={() => setDemoMode(!demoMode)}
              className={`px-3 py-1.5 rounded-lg border ${
                demoMode
                  ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                  : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
              }`}
            >
              {demoMode ? 'Demo' : 'Live LLM'}
            </button>
          </div>
        </div>
      )}
    </header>
  )
}

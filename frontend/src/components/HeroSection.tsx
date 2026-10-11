import React from 'react'
import { ArrowRight, Newspaper } from 'lucide-react'
import { MarketTickerPanel } from './MarketTickerPanel'
import heroBgImg from '../assets/hero-bg.png'

interface HeroSectionProps {
  onExploreMarkets: () => void
  onLatestNews: () => void
  onViewAllInstruments?: () => void
}

export const HeroSection: React.FC<HeroSectionProps> = ({
  onExploreMarkets,
  onLatestNews,
  onViewAllInstruments,
}) => {
  return (
    <section
      id="hero-section"
      className="relative w-full min-h-[85vh] lg:min-h-[88vh] flex flex-col justify-between overflow-hidden bg-[#070913] select-none"
    >
      {/* ── Background Layer with 6px Blur & Extended Margins to Prevent Edge Leaks ── */}
      <div
        className="absolute -inset-8 bg-cover bg-center pointer-events-none transform scale-105"
        style={{
          backgroundImage: `url(${heroBgImg})`,
          filter: 'blur(6px)',
          WebkitFilter: 'blur(6px)',
        }}
        aria-hidden="true"
      />

      {/* ── Cinematic Dark Navy / Black Overlay with Subtle Red Tint ── */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            'radial-gradient(circle at 75% 35%, rgba(245, 45, 61, 0.12) 0%, transparent 60%), linear-gradient(90deg, rgba(7, 10, 19, 0.94) 0%, rgba(8, 12, 24, 0.82) 48%, rgba(18, 7, 12, 0.72) 100%), linear-gradient(180deg, rgba(7, 10, 19, 0.5) 0%, rgba(7, 10, 19, 0.75) 75%, #0b0d14 100%)',
        }}
        aria-hidden="true"
      />

      {/* ── Main Left-Aligned Hero Content (Crisp Foreground) ── */}
      <div className="relative z-10 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 pt-10 sm:pt-14 lg:pt-18 pb-6 flex-1 flex flex-col justify-center">
        <div className="max-w-2xl lg:max-w-3xl space-y-5 sm:space-y-6">
          {/* Status Badge */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#161a29]/80 border border-white/10 backdrop-blur-md shadow-sm">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#F52D3D] opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[#F52D3D]" />
            </span>
            <span className="text-[11px] font-bold tracking-wider text-gray-200 uppercase font-sans">
              MARKET INTELLIGENCE • LIVE UPDATES
            </span>
          </div>

          {/* Headline */}
          <div className="space-y-1 sm:space-y-2">
            <h1 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-white font-sans leading-[1.12]">
              Understand the Markets.
            </h1>
            <h2 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight font-sans leading-[1.12]">
              <span className="text-[#F52D3D]">Stay Ahead</span>
              <span className="text-white"> of Every Move.</span>
            </h2>
          </div>

          {/* Subtitle */}
          <p className="text-sm sm:text-base lg:text-lg text-[#a2a8b9] font-normal leading-relaxed max-w-xl">
            Track market trends, global events and financial insights in one place. Make smarter decisions with real-time data, expert analysis and trusted news.
          </p>

          {/* Call-to-Action Buttons */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3.5 pt-2 sm:pt-4">
            {/* Primary Button */}
            <button
              id="cta-explore-markets"
              onClick={onExploreMarkets}
              className="inline-flex items-center justify-center gap-2.5 px-6 py-3 rounded-xl bg-[#F52D3D] hover:bg-[#de2030] text-white text-sm font-semibold shadow-lg shadow-red-500/25 transition-all duration-200 hover:shadow-red-500/40 hover:-translate-y-0.5 active:translate-y-0 cursor-pointer"
            >
              <span>Explore Markets</span>
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-1" />
            </button>

            {/* Secondary Button */}
            <button
              id="cta-latest-news"
              onClick={onLatestNews}
              className="inline-flex items-center justify-center gap-2.5 px-6 py-3 rounded-xl bg-[#121626]/80 hover:bg-[#1a2035] text-white text-sm font-semibold border border-[#2b334d] hover:border-gray-400/40 backdrop-blur-md transition-all duration-200 hover:-translate-y-0.5 active:translate-y-0 cursor-pointer shadow-sm"
            >
              <span>Latest News</span>
              <Newspaper className="w-4 h-4 text-gray-300" />
            </button>
          </div>
        </div>
      </div>

      {/* ── Bottom Market Ticker Panel ── */}
      <div className="relative z-10 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 pb-6 sm:pb-8">
        <MarketTickerPanel onViewAll={onViewAllInstruments || onExploreMarkets} />
      </div>
    </section>
  )
}

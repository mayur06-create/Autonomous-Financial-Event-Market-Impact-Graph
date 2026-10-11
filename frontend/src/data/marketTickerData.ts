/**
 * Market Ticker Data Service
 * 
 * Provides real-time snapshot data for hero market strip.
 * Matches the reference MARKETPULSE dashboard design.
 * 
 * To replace with a live API:
 * 1. Implement `fetchLiveTickerData()` calling your market provider (e.g., NSE/BSE API, Yahoo Finance, or FastAPI endpoint).
 * 2. Update the HeroTickerPanel hook to consume live data.
 */

export interface MarketInstrument {
  id: string
  name: string
  category: 'Index' | 'Commodity' | 'Forex' | 'Crypto'
  price: string
  change: string
  changePercent: string
  isPositive: boolean
  sparkline: number[]
  iconType: 'chart-down' | 'chart-up' | 'gold' | 'oil' | 'forex'
}

export const INITIAL_TICKER_DATA: MarketInstrument[] = [
  {
    id: 'sensex',
    name: 'Sensex',
    category: 'Index',
    price: '78,642.12',
    change: '-1,248.56',
    changePercent: '-1.56%',
    isPositive: false,
    sparkline: [79890, 79650, 79420, 79550, 79200, 79050, 78900, 78750, 78820, 78642],
    iconType: 'chart-down',
  },
  {
    id: 'nifty50',
    name: 'Nifty 50',
    category: 'Index',
    price: '23,984.70',
    change: '-383.90',
    changePercent: '-1.57%',
    isPositive: false,
    sparkline: [24368, 24290, 24200, 24250, 24150, 24100, 24040, 24010, 24080, 23984],
    iconType: 'chart-down',
  },
  {
    id: 'gold',
    name: 'Gold (MCX)',
    category: 'Commodity',
    price: '₹72,450.00',
    change: '+612.00',
    changePercent: '+0.85%',
    isPositive: true,
    sparkline: [71838, 71920, 71980, 72050, 72150, 72100, 72280, 72350, 72400, 72450],
    iconType: 'gold',
  },
  {
    id: 'brent',
    name: 'Brent Crude',
    category: 'Commodity',
    price: '$78.32',
    change: '-2.64',
    changePercent: '-3.26%',
    isPositive: false,
    sparkline: [80.96, 80.50, 80.20, 79.90, 79.70, 79.40, 79.10, 78.80, 78.50, 78.32],
    iconType: 'oil',
  },
  {
    id: 'usdinr',
    name: 'USD/INR',
    category: 'Forex',
    price: '₹83.42',
    change: '+0.18',
    changePercent: '+0.22%',
    isPositive: true,
    sparkline: [83.24, 83.26, 83.28, 83.31, 83.33, 83.35, 83.38, 83.39, 83.40, 83.42],
    iconType: 'forex',
  },
]

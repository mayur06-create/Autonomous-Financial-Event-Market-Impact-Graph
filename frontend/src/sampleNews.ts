import type { SampleArticle } from './types'

export const SAMPLE_ARTICLES: SampleArticle[] = [
  {
    id: '01_opec_cut',
    title: 'OPEC+ Surprise 1.16M bpd Production Cut',
    source: 'Reuters',
    date: '2023-04-03',
    tag: 'Crude Oil Shock',
    icon: 'Fuel',
    expectedPrimary: 'crude_oil',
    expectedDirection: '+',
    description: 'Crude spikes >6% → widened Current Account Deficit → INR pressure → OMC & Aviation margin hit.',
    text: `OPEC+ Announces Surprise 1 Million Barrel/Day Production Cut
Reuters, April 3, 2023

RIYADH — OPEC+ shocked global energy markets on Sunday by announcing a voluntary production cut of approximately 1.16 million barrels per day (bpd) starting May 2023, on top of the 2 million bpd reduction agreed in October 2022. Saudi Arabia alone will cut 500,000 bpd. Russia extended its 500,000 bpd reduction through year-end.

Brent crude futures jumped more than 6% at the Asian open, trading above $86 a barrel. Analysts at Goldman Sachs revised their year-end Brent forecast to $95/bbl.

Impact on India: India imports roughly 85% of its crude requirements. Every $10/bbl rise in crude prices widens the current account deficit by approximately $15 billion annually, according to RBI estimates. Oil marketing companies (BPCL, HPCL, IOC) may face margin pressure if retail fuel prices are not raised; however, the government has historically absorbed shocks close to elections to control inflation.

INR is expected to face depreciation pressure as the import bill rises. Aviation fuel (ATF) constitutes 30–35% of airline operating costs, putting IndiGo, Air India, and SpiceJet under pressure. Logistics companies such as Blue Dart and GATI will also see cost headwinds.

The RBI, already monitoring sticky core inflation, may delay any rate cuts in the near term. Bond yields are expected to tick up on rising inflation expectations.`
  },
  {
    id: '02_rbi_rate_hike',
    title: 'RBI Hikes Repo Rate 25 bps to 6.75%',
    source: 'Economic Times',
    date: '2023-02-08',
    tag: 'Monetary Policy',
    icon: 'Landmark',
    expectedPrimary: 'repo_rate',
    expectedDirection: '+',
    description: 'MPC raises repo rate by 25 bps → Nifty Bank compression → higher EMIs squeeze Real Estate & Auto demand.',
    text: `RBI Raises Repo Rate by 25 bps to 6.75%; Maintains Withdrawal of Accommodation
Economic Times, February 8, 2023

MUMBAI — The Reserve Bank of India's Monetary Policy Committee (MPC) raised the benchmark repo rate by 25 basis points to 6.75% on Wednesday, in a 4-2 majority decision, signalling continued resolve to bring CPI inflation sustainably to the 4% target.

Governor Shaktikanta Das said the MPC would maintain its stance of "withdrawal of accommodation" as long as necessary. The decision was broadly in line with market expectations, though a minority of analysts had forecast a pause.

Market reaction: Nifty Bank index fell 1.2% on the day as higher rates compress net interest margins in the short term. The 10-year G-sec yield rose 7 basis points to 7.42%. The Indian rupee strengthened marginally by 0.3% on improved real rate differential expectations.

Sector implications:
- Banking & NBFCs: Transmission lag of 2–3 quarters means NIM pressure is temporary; asset quality remains the key variable.
- Real estate: Higher home loan rates (EMIs rise ~Rs 750/month per Rs 50 lakh loan) dampen affordability; residential demand may moderate in the H1 2023.
- Auto (two-wheelers): Retail credit constitutes ~70% of two-wheeler sales; rate sensitivity is high for entry-level segment.
- Infrastructure & Capital goods: Discount rate rise lowers NPV of long-duration projects.

The next MPC meeting is scheduled for April 2023. The market is pricing in a pause at that meeting, but elevated global commodity prices remain a risk.`
  },
  {
    id: '03_inr_depreciation',
    title: 'Rupee Hits All-Time Low of 84.50 / USD',
    source: 'Mint',
    date: '2024-10-19',
    tag: 'Forex & FPI Flows',
    icon: 'TrendingDown',
    expectedPrimary: 'inr',
    expectedDirection: '+',
    description: 'DXY surge & FPI outflows drive USD/INR higher → raw import cost rises → IT & Pharma exporters gain.',
    text: `Rupee Hits Record Low of 84.50 Against Dollar Amid Global Risk-Off
Mint, October 19, 2024

MUMBAI — The Indian rupee touched an all-time intraday low of 84.50 against the US dollar on Friday, driven by broad dollar strength after stronger-than-expected US jobs data raised fears that the Federal Reserve would keep rates higher for longer.

The USD Index (DXY) climbed to 103.8, its highest since August. Foreign portfolio investors (FPIs) pulled out a net Rs 4,300 crore from domestic equities in the week, adding to the selling pressure on the rupee.

Key effects:
- Importers (crude oil, edible oil, electronics): Rising input costs in rupee terms. Every 1% INR depreciation raises the crude import bill by approximately Rs 12,000 crore annually (RBI working paper, 2022).
- IT exporters (TCS, Infosys, Wipro, HCL Tech): Positive revenue tailwind; a weaker rupee boosts realization from USD-denominated contracts. Industry body NASSCOM estimates ~40–50 bps improvement in EBIT margin per 1% INR depreciation.
- Pharma exporters: Similar tailwind to IT; US-generics business benefits.
- Metals (Hindalco, Tata Steel): Mixed. Import cost of coking coal rises; but export realizations also improve.
- Gold: Domestic prices in INR terms rise with rupee weakness, dampening demand but boosting returns for holders.

The RBI intervened in the forward market to prevent disorderly depreciation. Foreign exchange reserves stood at $688 billion, providing a comfortable buffer. Analysts expect the central bank to tolerate modest depreciation but resist a sharp move.`
  },
  {
    id: '04_inflation_spike',
    title: 'CPI Inflation Climbs to 6.83% Breaching Band',
    source: 'Business Standard',
    date: '2023-09-12',
    tag: 'Inflation Spike',
    icon: 'Flame',
    expectedPrimary: 'inflation_cpi',
    expectedDirection: '+',
    description: 'Food & vegetable prices drive headline CPI above 6% threshold → pushes rate cut expectations into FY25.',
    text: `India CPI Inflation Rises to 6.8% in August, Breaching RBI Upper Tolerance Band
Business Standard, September 12, 2023

NEW DELHI — India's retail inflation, measured by the Consumer Price Index (CPI), surged to 6.83% year-on-year in August 2023, breaching the Reserve Bank of India's upper tolerance band of 6% for the first time in five months, driven primarily by a spike in vegetable prices (tomato +300% YoY) and elevated cereals inflation.

Core CPI (excluding food and fuel) remained relatively contained at 4.9%, providing some comfort to policymakers. However, the headline print significantly exceeded the consensus estimate of 6.2% and the RBI's own projection of 5.4% for Q2 FY24.

Implications:
- RBI policy: The print makes a September rate cut virtually impossible. Market participants shifted expectations of the first cut to Q1 FY25. Overnight index swap (OIS) rates moved 8–10 bps higher.
- Bond market: The 10-year government securities yield rose 6 bps to 7.19% on inflation fears. A higher-for-longer stance implies sustained bond supply.
- Banking sector: Deposit rate competition is likely to remain high; margins under pressure for liability-heavy banks.
- FMCG companies (HUL, Nestle, Dabur): Input cost pressures from food inflation; rural demand likely to be hurt by food price inflation eating into disposable income.
- Agriculture-linked stocks: Agro-chemicals, fertilizers, and tractor companies (M&M) may see mixed impact — demand for agri-inputs rises but farmer income is volatile.
- Fixed income: Short-duration funds preferred; long-duration funds face mark-to-market losses as yields rise.`
  }
]

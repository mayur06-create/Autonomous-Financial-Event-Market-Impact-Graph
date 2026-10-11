"""
stock_intelligence.py — Constituent-Level Stock Intelligence & Sensitivity Engine (Phase P3).

Evaluates granular company-level exposure across key listed Indian equities based on:
  1. Raw Material / Energy cost share of COGS/Opex
  2. Foreign Exchange / Export billing currency share
  3. Pricing Power & Margin absorption capacity
  4. Balance sheet leverage (Net Debt / EBITDA) & interest rate sensitivity
  5. Empirical asset beta and hedging cushions

Pure scenario & transmission mechanisms — NEVER guaranteed price targets.
"""

from __future__ import annotations
import logging
from typing import Optional

from app.schemas import (
    ConstituentExposureItem,
    StockIntelligenceReport,
    DynamicSectorMatrix,
    ExtractedEvent,
    MacroDriver,
    Sign,
)

logger = logging.getLogger("market_impact.stock_intelligence")


# ─── Stock Universe & Fundamental Profiles ─────────────────────────────────────

STOCK_UNIVERSE: list[dict] = [
    {
        "symbol": "INDIGO",
        "company_name": "InterGlobe Aviation Ltd",
        "ticker": "INDIGO.NS",
        "sector": "Aviation & Transport",
        "rm_cost_share": 0.38,          # ATF is ~38% of total operating expenses
        "export_revenue_share": 0.08,   # International flights
        "fx_import_burden": 0.55,       # Aircraft lease rentals + fuel dollar-denominated
        "pricing_power": "Moderate",    # Dynamic yield management, but passenger price sensitive
        "interest_rate_sensitivity": 0.40,
        "commodity_sensitivity": -0.88,
        "historical_beta": 1.15,
        "cushion_or_hedge": "Dominant ~63% domestic market share enables partial fuel surcharge pass-through over 6-8 week lag.",
        "mechanisms": {
            "crude_spike": "Aviation Turbine Fuel (ATF) constitutes ~38% of IndiGo's operating expenses. A crude oil surge directly expands cash burn per Available Seat Kilometer (ASK).",
            "inr_weakness": "Over 50% of aircraft maintenance, overhaul, and dollar-denominated lease liabilities expand in rupee terms.",
            "rates_up": "Aircraft fleet refinancing and lease capitalizations face higher discount rates.",
        },
    },
    {
        "symbol": "ASIANPAINT",
        "company_name": "Asian Paints Ltd",
        "ticker": "ASIANPAINT.NS",
        "sector": "Paints & Specialty Chemicals",
        "rm_cost_share": 0.52,          # Monomers, solvents, titanium dioxide (crude derivatives) ~52% of COGS
        "export_revenue_share": 0.12,
        "fx_import_burden": 0.40,       # Imported TiO2 and solvent feedstock
        "pricing_power": "High",        # Strong brand moat and dealer network
        "interest_rate_sensitivity": 0.30,
        "commodity_sensitivity": -0.80,
        "historical_beta": 0.82,
        "cushion_or_hedge": "Industry-leading distribution moat allows phased 1.5–3.0% retail price hikes across decorative emulsions.",
        "mechanisms": {
            "crude_spike": "Petrochemical derivatives (phthalic anhydride, solvents, resins) make up ~50% of raw material costs, creating immediate gross margin compression.",
            "rates_up": "Slowdown in residential real estate completions mildly impacts fresh decorative repainting cycles.",
        },
    },
    {
        "symbol": "TCS",
        "company_name": "Tata Consultancy Services Ltd",
        "ticker": "TCS.NS",
        "sector": "IT Services",
        "rm_cost_share": 0.00,          # Zero physical raw materials
        "export_revenue_share": 0.94,   # ~94% USD, EUR, GBP billing
        "fx_import_burden": 0.05,
        "pricing_power": "High",        # Tier-1 enterprise vendor
        "interest_rate_sensitivity": -0.45, # Global enterprise IT budget constraint
        "commodity_sensitivity": 0.00,
        "historical_beta": 0.78,
        "cushion_or_hedge": "Zero net debt, massive cash reserves, and multi-year mission-critical transformation contracts.",
        "mechanisms": {
            "inr_weakness": "Every 1% depreciation in USD/INR delivers an estimated +25–30 bps expansion in reported operating EBITDA margins.",
            "rates_up": "Elevated US Fed interest rates cause US/European banking and retail clients to scrutinize non-essential discretionary cloud spending.",
        },
    },
    {
        "symbol": "INFY",
        "company_name": "Infosys Ltd",
        "ticker": "INFY.NS",
        "sector": "IT Services",
        "rm_cost_share": 0.00,
        "export_revenue_share": 0.93,
        "fx_import_burden": 0.05,
        "pricing_power": "High",
        "interest_rate_sensitivity": -0.45,
        "commodity_sensitivity": 0.00,
        "historical_beta": 0.85,
        "cushion_or_hedge": "Comprehensive rolling FX hedging program buffers short-term currency volatility.",
        "mechanisms": {
            "inr_weakness": "Dollar contract revenues translate to expanded rupee realizations, offsetting wage increments and onsite subcontractor costs.",
            "rates_up": "Global enterprise rate tightening causes client hesitation in discretionary technology capex releases.",
        },
    },
    {
        "symbol": "HDFCBANK",
        "company_name": "HDFC Bank Ltd",
        "ticker": "HDFCBANK.NS",
        "sector": "Banking",
        "rm_cost_share": 0.00,
        "export_revenue_share": 0.00,
        "fx_import_burden": 0.00,
        "pricing_power": "High",        # Low-cost CASA deposit franchise
        "interest_rate_sensitivity": -0.35, # Rate hikes squeeze deposit costs vs floating loan book
        "commodity_sensitivity": -0.10,
        "historical_beta": 0.95,
        "cushion_or_hedge": "Extensive retail branch footprint drives stable low-cost CASA deposit mobilization.",
        "mechanisms": {
            "rates_up": "Floating loan book reprices upward immediately, but treasury bond portfolios incur mark-to-market provision drag and deposit costs catch up.",
            "liquidity_tight": "Competition for retail term deposits compresses Net Interest Margins (NIMs) during aggressive rate cycles.",
        },
    },
    {
        "symbol": "ICICIBANK",
        "company_name": "ICICI Bank Ltd",
        "ticker": "ICICIBANK.NS",
        "sector": "Banking",
        "rm_cost_share": 0.00,
        "export_revenue_share": 0.00,
        "fx_import_burden": 0.00,
        "pricing_power": "High",
        "interest_rate_sensitivity": -0.30,
        "commodity_sensitivity": -0.10,
        "historical_beta": 1.05,
        "cushion_or_hedge": "High proportion of repo-linked External Benchmark Lending Rate (EBLR) assets provides swift yield adaptation.",
        "mechanisms": {
            "rates_up": "Fast transmission of repo rate hikes to retail and SME loan books temporarily widens lending spreads before deposit rates repricing.",
            "rates_down": "Rate cuts accelerate retail mortgage and SME credit uptake, supporting loan book compounding.",
        },
    },
    {
        "symbol": "ONGC",
        "company_name": "Oil & Natural Gas Corporation Ltd",
        "ticker": "ONGC.NS",
        "sector": "Upstream Oil & Gas",
        "rm_cost_share": 0.10,          # Extraction & rig lease expenses
        "export_revenue_share": 0.70,   # Crude sold at international parity pricing (USD-denominated)
        "fx_import_burden": 0.15,
        "pricing_power": "High",        # Price-taker linked to global Brent benchmarks
        "interest_rate_sensitivity": -0.10,
        "commodity_sensitivity": 0.92,
        "historical_beta": 0.90,
        "cushion_or_hedge": "Every $1/bbl increase in crude realization boosts standalone EBITDA by approximately ₹700–800 crore.",
        "mechanisms": {
            "crude_spike": "Elevated international crude benchmark prices directly elevate upstream crude and gas realizations, generating massive operating free cash flows.",
            "crude_drop": "Lower crude spot benchmarks decrease EBITDA per barrel and reduce dividend yields.",
        },
    },
    {
        "symbol": "BPCL",
        "company_name": "Bharat Petroleum Corporation Ltd",
        "ticker": "BPCL.NS",
        "sector": "Oil Marketing Companies (OMCs)",
        "rm_cost_share": 0.82,          # Crude is the single largest feedstock input
        "export_revenue_share": 0.15,
        "fx_import_burden": 0.75,       # Dollar crude imports
        "pricing_power": "Low",         # Regulated retail auto-fuel pricing
        "interest_rate_sensitivity": -0.45, # Massive short-term debt for crude inventory financing
        "commodity_sensitivity": -0.80,
        "historical_beta": 1.10,
        "cushion_or_hedge": "Integrated refining margins (GRMs) partially soften marketing loss during unhedged crude run-ups.",
        "mechanisms": {
            "crude_spike": "Elevated crude procurement without simultaneous retail petrol/diesel pump price revisions severely erodes marketing margins.",
            "crude_drop": "Plunging crude prices unlock supernormal retail marketing margins and lower working capital debt.",
        },
    },
    {
        "symbol": "MARUTI",
        "company_name": "Maruti Suzuki India Ltd",
        "ticker": "MARUTI.NS",
        "sector": "Auto & Ancillaries",
        "rm_cost_share": 0.68,          # Steel, aluminum, plastics, precious metals ~68% of sales
        "export_revenue_share": 0.14,
        "fx_import_burden": 0.22,       # Japanese Yen and USD-linked imported component royalty
        "pricing_power": "Moderate",    # High volume entry segment sensitive to price elasticities
        "interest_rate_sensitivity": -0.65, # ~80% of passenger vehicles bought via financing
        "commodity_sensitivity": -0.65,
        "historical_beta": 0.92,
        "cushion_or_hedge": "Unrivaled rural sales touchpoints and hybrid technology adoption mitigate localized demand slowdowns.",
        "mechanisms": {
            "rates_up": "Higher auto financing interest rates elevate customer monthly EMIs, leading to deferral of entry-level passenger vehicle purchases.",
            "commodity_up": "Surging steel and aluminum spot prices compress operating gross margins unless passed on via ex-showroom price increases.",
        },
    },
    {
        "symbol": "DLF",
        "company_name": "DLF Ltd",
        "ticker": "DLF.NS",
        "sector": "Real Estate / Construction",
        "rm_cost_share": 0.35,          # Steel, cement, contractor costs
        "export_revenue_share": 0.00,
        "fx_import_burden": 0.00,
        "pricing_power": "High",        # Strong brand in premium luxury residential segment
        "interest_rate_sensitivity": -0.78, # Mortgage rates determine buyer affordability
        "commodity_sensitivity": -0.45,
        "historical_beta": 1.25,
        "cushion_or_hedge": "Virtually zero net debt in residential business and robust pre-sales booking cash flows.",
        "mechanisms": {
            "rates_up": "Escalating home loan interest rates increase long-term mortgage service burdens, stretching residential sales cycles.",
            "rates_down": "Competitive mortgage rate environment spurs demand for premium residential launches and accelerates inventory liquidation.",
        },
    },
    {
        "symbol": "TATASTEEL",
        "company_name": "Tata Steel Ltd",
        "ticker": "TATASTEEL.NS",
        "sector": "Metals & Mining",
        "rm_cost_share": 0.55,          # Coking coal, electricity, fluxes (100% captive iron ore in India)
        "export_revenue_share": 0.25,
        "fx_import_burden": 0.35,       # Imported Australian coking coal
        "pricing_power": "Moderate",    # Cyclical global commodity parity
        "interest_rate_sensitivity": -0.40,
        "commodity_sensitivity": 0.85,
        "historical_beta": 1.35,
        "cushion_or_hedge": "100% captive iron ore mines in domestic operations insulate Indian business from seaborne ore volatility.",
        "mechanisms": {
            "commodity_up": "Higher international hot rolled coil (HRC) steel benchmark prices elevate domestic realizations and operating cash flows.",
            "coking_coal_up": "Surging seaborne coking coal import costs elevate blast furnace conversion costs per tonne.",
        },
    },
    {
        "symbol": "SUNPHARMA",
        "company_name": "Sun Pharmaceutical Industries Ltd",
        "ticker": "SUNPHARMA.NS",
        "sector": "Pharmaceuticals",
        "rm_cost_share": 0.28,          # Active pharmaceutical ingredients (API) & solvents
        "export_revenue_share": 0.68,   # US Generics, Specialty, Emerging Markets
        "fx_import_burden": 0.20,
        "pricing_power": "High",        # Global specialty portfolio (Ilumya, Cequa, Winlevi)
        "interest_rate_sensitivity": -0.15,
        "commodity_sensitivity": -0.15,
        "historical_beta": 0.65,
        "cushion_or_hedge": "Expanding global proprietary specialty business reduces dependence on commoditized generic pricing.",
        "mechanisms": {
            "inr_weakness": "Strong dollar receipts enhance rupee-converted revenue from US specialty drugs and emerging market export franchises.",
            "regulatory_burden": "Heightened USFDA regulatory compliance mandates and cGMP remediation capex.",
        },
    },
    {
        "symbol": "HINDUNILVR",
        "company_name": "Hindustan Unilever Ltd",
        "ticker": "HINDUNILVR.NS",
        "sector": "FMCG / Consumer Staples",
        "rm_cost_share": 0.48,          # Palm fatty acid, soda ash, linear alkyl benzene (crude linked), packaging
        "export_revenue_share": 0.03,
        "fx_import_burden": 0.25,       # Imported palm oil and chemicals
        "pricing_power": "High",        # Power brands across soaps, detergents, oral care, tea
        "interest_rate_sensitivity": -0.10,
        "commodity_sensitivity": -0.65,
        "historical_beta": 0.60,
        "cushion_or_hedge": "Unrivaled FMCG rural distribution and calibrated pack-size SKU adjustments maintain gross margin resilience.",
        "mechanisms": {
            "commodity_up": "Surging palm oil, crude derivative packaging, and freight costs compress gross margins, requiring selective price hikes.",
            "rural_demand_up": "Favorable monsoon and agrarian cash transfers accelerate rural volume uptake across mass home and personal care brands.",
        },
    },
    {
        "symbol": "RELIANCE",
        "company_name": "Reliance Industries Ltd",
        "ticker": "RELIANCE.NS",
        "sector": "Diversified Conglomerate",
        "rm_cost_share": 0.60,          # Crude oil for Jamnagar mega-refinery
        "export_revenue_share": 0.35,   # Petroleum product exports
        "fx_import_burden": 0.50,
        "pricing_power": "High",        # Complex refinery capable of processing heavy sour crudes
        "interest_rate_sensitivity": -0.35,
        "commodity_sensitivity": 0.25,  # Mixed: Oil-to-Chemicals benefits from refining spreads; retail/telecom are domestic consumer
        "historical_beta": 1.02,
        "cushion_or_hedge": "Diversified cash engine across Oil-to-Chemicals (O2C), Jio Digital, and Reliance Retail balances sector-specific shocks.",
        "mechanisms": {
            "crude_spike": "High complex refining margins (GRMs) expand export realization, while domestic petchem and retail margins face cost friction.",
            "rates_up": "Telecom and retail capex interest servicing costs rise moderately.",
        },
    },
    {
        "symbol": "LT",
        "company_name": "Larsen & Toubro Ltd",
        "ticker": "LT.NS",
        "sector": "Infrastructure & Capital Goods",
        "rm_cost_share": 0.42,          # Steel, cement, electrical components, construction labor
        "export_revenue_share": 0.38,   # Middle East hydrocarbon and infra projects
        "fx_import_burden": 0.20,
        "pricing_power": "Moderate",    # Most long-term contracts feature price escalation clauses
        "interest_rate_sensitivity": -0.35,
        "commodity_sensitivity": -0.30,
        "historical_beta": 1.12,
        "cushion_or_hedge": "Record order backlog with ~75% inflation-indexed escalation protection clauses.",
        "mechanisms": {
            "capex_up": "Aggressive central/state government infrastructure capex and Middle East energy investments drive robust order inflows.",
            "inr_weakness": "Significant Middle East project revenues yield currency translation upside.",
        },
    },
]


# ─── 2. Constituent Exposure Engine ───────────────────────────────────────────

def evaluate_constituent_exposures(
    news_text: str,
    event: ExtractedEvent,
    sector_matrix: Optional[DynamicSectorMatrix] = None,
) -> StockIntelligenceReport:
    """
    Computes individual sensitivity scores, impact classifications, and
    transmission mechanisms for key listed Indian equities.
    """
    # Build a lookup of active macro drivers
    active_drivers = sector_matrix.active_drivers if sector_matrix else []
    driver_map: dict[MacroDriver, float] = {}
    for d in active_drivers:
        sign = 1.0 if d.direction == Sign.positive else (-1.0 if d.direction == Sign.negative else 0.0)
        driver_map[d.driver] = sign * d.intensity

    # Identify primary event theme
    is_crude = any(w in news_text.lower() for w in ["crude", "oil", "brent", "petroleum", "fuel"])
    is_rates = any(w in news_text.lower() for w in ["rate", "repo", "rbi", "yield", "basis points", "bps"])
    is_fx = any(w in news_text.lower() for w in ["rupee", "usd/inr", "dollar", "currency", "inr"])
    direction_mult = 1.0 if event.direction == Sign.positive else (-1.0 if event.direction == Sign.negative else 0.0)

    analyzed_items: list[ConstituentExposureItem] = []

    for stock in STOCK_UNIVERSE:
        # Multi-factor score calculation
        score = 0.0
        applied_mechanisms: list[str] = []

        # Factor 1: Commodity / Raw Material impact
        if MacroDriver.commodity_pricing in driver_map:
            comm_effect = driver_map[MacroDriver.commodity_pricing] * stock["commodity_sensitivity"]
            score += comm_effect * 0.45
            if abs(comm_effect) > 0.15:
                applied_mechanisms.append(
                    f"Raw Material Sensitivity: RM represents {int(stock['rm_cost_share']*100)}% of cost base with {stock['commodity_sensitivity']:+.2f} correlation."
                )

        # Factor 2: Foreign Exchange & Export Exposure
        if MacroDriver.fx_exposure in driver_map:
            fx_intensity = driver_map[MacroDriver.fx_exposure]
            # Export positive, import burden negative
            fx_effect = fx_intensity * (stock["export_revenue_share"] * 0.85 - stock["fx_import_burden"] * 0.70)
            score += fx_effect * 0.35
            if abs(fx_effect) > 0.10:
                applied_mechanisms.append(
                    f"FX Exposure: {int(stock['export_revenue_share']*100)}% export revenues vs {int(stock['fx_import_burden']*100)}% FX import obligations."
                )

        # Factor 3: Interest Rates & Financing Burden
        if MacroDriver.interest_rates in driver_map:
            rate_intensity = driver_map[MacroDriver.interest_rates]
            rate_effect = rate_intensity * stock["interest_rate_sensitivity"]
            score += rate_effect * 0.30
            if abs(rate_effect) > 0.10:
                applied_mechanisms.append(
                    f"Interest Rate Sensitivity: Rate sensitivity rating of {stock['interest_rate_sensitivity']:+.2f} across customer financing and balance sheet."
                )

        # Factor 4: Generic Macro / Fallback
        if not driver_map:
            if is_crude:
                score = direction_mult * stock["commodity_sensitivity"] * 0.6
            elif is_rates:
                score = direction_mult * stock["interest_rate_sensitivity"] * 0.5
            elif is_fx:
                score = direction_mult * (stock["export_revenue_share"] - stock["fx_import_burden"]) * 0.6
            else:
                score = direction_mult * 0.15

        # Bound score to [-1.0, 1.0]
        net_score = max(-1.0, min(1.0, round(score, 2)))
        conf = round(min(0.92, max(0.40, abs(net_score) * 0.65 + 0.35)), 2)

        # Assign Impact Class
        if stock["symbol"] == "RELIANCE" and is_crude:
            impact_class = "Mixed Exposure"
            dir_sign = Sign.ambiguous
        elif net_score >= 0.15:
            impact_class = "Key Beneficiary"
            dir_sign = Sign.positive
        elif net_score <= -0.15:
            impact_class = "High Pressure"
            dir_sign = Sign.negative
        elif abs(net_score) < 0.15 and stock.get("pricing_power") == "High":
            impact_class = "Resilient"
            dir_sign = Sign.positive if net_score >= 0 else Sign.negative
        else:
            impact_class = "Mixed Exposure"
            dir_sign = Sign.ambiguous

        # Specific mechanism text
        mech_text = ""
        if is_crude and "crude_spike" in stock["mechanisms"]:
            mech_text = stock["mechanisms"]["crude_spike"] if event.direction == Sign.positive else stock["mechanisms"].get("crude_drop", "")
        elif is_rates and "rates_up" in stock["mechanisms"]:
            mech_text = stock["mechanisms"]["rates_up"] if event.direction == Sign.positive else stock["mechanisms"].get("rates_down", "")
        elif is_fx and "inr_weakness" in stock["mechanisms"]:
            mech_text = stock["mechanisms"]["inr_weakness"]

        if not mech_text and applied_mechanisms:
            mech_text = ". ".join(applied_mechanisms)
        if not mech_text:
            mech_text = f"Exposure driven by {stock['sector']} dynamics and corporate cost structure."

        analyzed_items.append(ConstituentExposureItem(
            symbol=stock["symbol"],
            company_name=stock["company_name"],
            ticker=stock["ticker"],
            sector=stock["sector"],
            direction=dir_sign,
            impact_class=impact_class,
            sensitivity_score=net_score,
            confidence=conf,
            transmission_mechanism=mech_text,
            key_factors={
                "RM Cost %": f"{int(stock['rm_cost_share']*100)}%",
                "Export %": f"{int(stock['export_revenue_share']*100)}%",
                "Pricing Power": stock["pricing_power"],
                "Beta": f"{stock['historical_beta']:.2f}",
            },
            cushion_or_hedge=stock.get("cushion_or_hedge"),
            historical_beta=stock["historical_beta"],
        ))

    # Bucket constituents
    beneficiaries = [item for item in analyzed_items if item.impact_class == "Key Beneficiary"]
    beneficiaries.sort(key=lambda x: x.sensitivity_score, reverse=True)

    pressured = [item for item in analyzed_items if item.impact_class == "High Pressure"]
    pressured.sort(key=lambda x: x.sensitivity_score)

    mixed_or_resilient = [item for item in analyzed_items if item.impact_class in ("Resilient", "Mixed Exposure")]
    mixed_or_resilient.sort(key=lambda x: abs(x.sensitivity_score), reverse=True)

    methodology = (
        "Constituent intelligence applies multi-factor fundamental sensitivity models incorporating raw material cost share (COGS/Opex), "
        "foreign exchange billing denomination, pricing power absorption, and empirical equity beta. "
        "Outputs represent directional scenario vulnerabilities, not price forecasts or investment recommendations."
    )

    return StockIntelligenceReport(
        total_stocks_analyzed=len(analyzed_items),
        top_beneficiaries=beneficiaries,
        top_pressured=pressured,
        mixed_or_resilient=mixed_or_resilient,
        methodology_summary=methodology,
    )

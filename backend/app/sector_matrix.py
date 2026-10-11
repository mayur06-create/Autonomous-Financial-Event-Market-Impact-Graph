"""
sector_matrix.py — Taxonomy Classifier, Macroeconomic Drivers & Dynamic Sector Matrix (Phase P2).

Maps any financial news event to:
  1. 13-category Event Taxonomy
  2. 9 Macroeconomic Transmission Drivers
  3. Dynamic Sector Exposure Matrix across NSE Sectors (Positive, Negative, Mixed, Neutral)
  4. Explainable transmission mechanisms with beneficiary & pressured constituents.

Constraint: Pure mechanism and scenario mapping — NEVER guaranteed price forecasts.
"""

from __future__ import annotations
import re
import logging
from typing import Optional

from app.schemas import (
    EventTaxonomyCategory,
    MacroDriver,
    DriverImpact,
    SectorExposureItem,
    DynamicSectorMatrix,
    ExtractedEvent,
    Sign,
)

logger = logging.getLogger("market_impact.sector_matrix")


# ─── 1. Taxonomy Definitions & Keywords ───────────────────────────────────────

TAXONOMY_META: dict[EventTaxonomyCategory, dict] = {
    EventTaxonomyCategory.monetary_policy: {
        "label": "Monetary Policy & Rates",
        "keywords": [
            "repo", "reverse repo", "rbi", "rate hike", "rate cut", "basis points",
            "bps", "monetary policy", "mpc", "crr", "slr", "policy stance",
            "tightening", "easing", "fed rate", "fomc", "interest rate decision"
        ],
        "default_driver": MacroDriver.interest_rates,
    },
    EventTaxonomyCategory.fiscal_policy: {
        "label": "Fiscal Policy & Government Capex",
        "keywords": [
            "union budget", "fiscal deficit", "capex", "capital expenditure", "gst",
            "taxation", "customs duty", "subsidy", "pli scheme", "government spending",
            "infrastructure spending", "tax cut", "disinvestment"
        ],
        "default_driver": MacroDriver.demand_volume,
    },
    EventTaxonomyCategory.commodity_shock: {
        "label": "Commodity Shock & Raw Materials",
        "keywords": [
            "crude", "brent", "oil", "wti", "opec", "natural gas", "petroleum",
            "gold", "silver", "copper", "steel", "coal", "iron ore", "coking coal",
            "aluminum", "wheat", "palm oil", "fertilizer", "commodity price"
        ],
        "default_driver": MacroDriver.commodity_pricing,
    },
    EventTaxonomyCategory.fx_currency: {
        "label": "FX & Currency Dynamics",
        "keywords": [
            "rupee", "inr", "usd/inr", "depreciation", "appreciation", "forex",
            "dollar index", "dxy", "currency devaluation", "fx reserves", "fpi flows",
            "external commercial borrowings", "dollar strength"
        ],
        "default_driver": MacroDriver.fx_exposure,
    },
    EventTaxonomyCategory.geopolitical_trade: {
        "label": "Geopolitical & Trade Restrictions",
        "keywords": [
            "tariff", "sanctions", "trade war", "embargo", "export ban", "import duty",
            "middle east conflict", "red sea", "shipping blockade", "strait of hormuz",
            "customs barrier", "antidumping", "fta"
        ],
        "default_driver": MacroDriver.regulatory_burden,
    },
    EventTaxonomyCategory.regulatory_policy: {
        "label": "Regulatory & Compliance Shift",
        "keywords": [
            "sebi", "rbi mandate", "cci", "licensing", "price capping", "npci",
            "fssai", "usfda", "483 observation", "import restriction", "green cess",
            "emission norms", "bs-vi", "windfall tax"
        ],
        "default_driver": MacroDriver.regulatory_burden,
    },
    EventTaxonomyCategory.banking_credit: {
        "label": "Banking, Credit & Yield Curve",
        "keywords": [
            "credit growth", "deposit growth", "npa", "gross npa", "provisioning",
            "bond yields", "10-year yield", "g-sec", "nbfc liquidity", "cost of funds",
            "nim", "net interest margin", "asset quality", "bank credit"
        ],
        "default_driver": MacroDriver.liquidity_availability,
    },
    EventTaxonomyCategory.corporate_earnings: {
        "label": "Corporate Earnings & Guidance",
        "keywords": [
            "q1", "q2", "q3", "q4", "quarterly results", "ebitda", "pat", "margin squeeze",
            "order book", "guidance cut", "earnings surprise", "revenue growth"
        ],
        "default_driver": MacroDriver.demand_volume,
    },
    EventTaxonomyCategory.inflation_macro: {
        "label": "Inflation & Macro Pressures",
        "keywords": [
            "inflation", "cpi", "wpi", "food inflation", "core inflation", "retail inflation",
            "consumer prices", "price index", "cost of living", "purchasing power"
        ],
        "default_driver": MacroDriver.input_cost,
    },
    EventTaxonomyCategory.supply_chain_disruption: {
        "label": "Supply Chain & Logistics",
        "keywords": [
            "freight rate", "container shortage", "port congestion", "semiconductor shortage",
            "chip shortage", "logistics cost", "suez canal", "vessel rerouting"
        ],
        "default_driver": MacroDriver.input_cost,
    },
    EventTaxonomyCategory.climate_monsoon: {
        "label": "Climate, Monsoon & Agriculture",
        "keywords": [
            "monsoon", "rainfall", "el nino", "la nina", "kharif", "rabi", "drought",
            "crop yield", "rural demand", "agri output", "unseasonal rains"
        ],
        "default_driver": MacroDriver.demand_volume,
    },
    EventTaxonomyCategory.domestic_demand_consumption: {
        "label": "Domestic Demand & Consumption",
        "keywords": [
            "auto sales", "festive sales", "rural demand", "urban consumption", "fmcg sales",
            "two-wheeler demand", "consumer spending", "passenger vehicle sales", "discretionary spend"
        ],
        "default_driver": MacroDriver.demand_volume,
    },
    EventTaxonomyCategory.global_spillover: {
        "label": "Global Market Spillover",
        "keywords": [
            "wall street", "nasdaq selloff", "s&p 500", "fed meeting", "us treasury yield",
            "china stimulus", "european central bank", "global tech selloff", "fii selloff"
        ],
        "default_driver": MacroDriver.market_sentiment,
    },
}


# ─── 2. Sector Definitions & Sensitivity Profiles ─────────────────────────────

SECTOR_PROFILES: list[dict] = [
    {
        "name": "Banking",
        "benchmark": "Nifty Bank",
        "ticker": "^NSEBANK",
        "sensitivities": {
            MacroDriver.interest_rates:         -0.40,  # Rate hikes compress bond MTM & slow credit demand
            MacroDriver.liquidity_availability: +0.80,
            MacroDriver.credit_quality:         +0.85,
            MacroDriver.market_sentiment:       +0.60,
            MacroDriver.demand_volume:          +0.75,
            MacroDriver.input_cost:             -0.10,
            MacroDriver.fx_exposure:            -0.20,
            MacroDriver.regulatory_burden:      -0.65,
            MacroDriver.commodity_pricing:      -0.10,
        },
        "beneficiaries": ["HDFC Bank", "ICICI Bank", "State Bank of India"],
        "pressured": ["Small Finance Banks", "High-beta PSU Banks"],
        "mechanism_templates": {
            "interest_rates_up": "Higher lending rates expand yields initially but elevate NPA risks, slow retail loan growth and trigger mark-to-market treasury portfolio losses.",
            "interest_rates_down": "Lower interest rates stimulate loan disbursements, improve borrowing affordability and yield treasury bond gains.",
            "liquidity_tight": "System liquidity squeeze raises deposit mobilization costs and exerts pressure on Net Interest Margins (NIMs).",
            "default": "Banking balance sheets are geared directly to credit demand, deposit rate cycles and asset quality.",
        },
    },
    {
        "name": "IT Services",
        "benchmark": "Nifty IT",
        "ticker": "^CNXIT",
        "sensitivities": {
            MacroDriver.fx_exposure:            +0.85,  # Weaker INR directly lifts operating margins on USD/EUR contracts
            MacroDriver.demand_volume:          +0.80,  # US/Europe enterprise tech budgets
            MacroDriver.interest_rates:         -0.45,  # Higher global rates cut client discretionary IT spending
            MacroDriver.market_sentiment:       +0.65,
            MacroDriver.input_cost:             -0.20,  # Wage inflation
            MacroDriver.regulatory_burden:      -0.30,  # Visa & offshore regulations
            MacroDriver.commodity_pricing:       0.00,
            MacroDriver.liquidity_availability: +0.20,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["TCS", "Infosys", "HCL Tech", "Wipro"],
        "pressured": ["Midcap IT with heavy BFSI European exposure"],
        "mechanism_templates": {
            "inr_weak": "Export billings in USD/EUR translate to higher rupee revenues and expanding EBITDA margin realization.",
            "rates_up": "Global enterprise rate tightening prompts corporate clients to defer discretionary digital transformation programs.",
            "default": "Indian IT exporters rely heavily on US/European enterprise demand and currency translation gains.",
        },
    },
    {
        "name": "Auto & Ancillaries",
        "benchmark": "Nifty Auto",
        "ticker": "^CNXAUTO",
        "sensitivities": {
            MacroDriver.interest_rates:         -0.65,  # Vehicle retail financing costs
            MacroDriver.input_cost:             -0.70,  # Steel, aluminum, plastics, freight
            MacroDriver.commodity_pricing:      -0.60,  # Raw material cost pressure
            MacroDriver.demand_volume:          +0.85,  # Festive / rural / replacement demand
            MacroDriver.fx_exposure:            -0.30,  # Imported child parts vs exports
            MacroDriver.market_sentiment:       +0.45,
            MacroDriver.regulatory_burden:      -0.50,  # Emission standards, safety norms
            MacroDriver.liquidity_availability: +0.50,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["Maruti Suzuki", "Tata Motors", "Mahindra & Mahindra", "Bajaj Auto"],
        "pressured": ["Ancillary suppliers with weak pricing power"],
        "mechanism_templates": {
            "rates_up": "Elevated vehicle financing interest rates elevate monthly EMIs, deferring consumer automotive purchases.",
            "input_cost_up": "Elevated steel, rubber and semiconductor input costs compress gross margins unless passed on through price hikes.",
            "default": "Auto volumes correlate strongly with affordable retail financing, monsoon-driven rural demand, and metal input costs.",
        },
    },
    {
        "name": "Pharmaceuticals",
        "benchmark": "Nifty Pharma",
        "ticker": "^CNXPHARMA",
        "sensitivities": {
            MacroDriver.fx_exposure:            +0.65,  # Major exporter to US/EU
            MacroDriver.regulatory_burden:      -0.70,  # USFDA 483s, warning letters, domestic price controls
            MacroDriver.demand_volume:          +0.40,  # Inelastic healthcare demand
            MacroDriver.input_cost:             -0.35,  # API and solvent import costs
            MacroDriver.commodity_pricing:      -0.10,
            MacroDriver.interest_rates:         -0.15,
            MacroDriver.market_sentiment:       +0.35,  # Defensive asset in volatile markets
            MacroDriver.liquidity_availability: +0.10,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["Sun Pharma", "Dr Reddy's", "Cipla", "Divi's Laboratories"],
        "pressured": ["Formulation players facing severe US price erosion"],
        "mechanism_templates": {
            "inr_weak": "Generics exports to regulated markets yield enhanced dollar realization and cushion API procurement expenses.",
            "regulatory_up": "Heightened regulatory inspection stringency and remediation capex threaten plant export clearances.",
            "default": "Pharma operates with defensive structural demand, driven by generic pipeline approvals, currency realization, and compliance standards.",
        },
    },
    {
        "name": "FMCG / Consumer Staples",
        "benchmark": "Nifty FMCG",
        "ticker": "^CNXFMCG",
        "sensitivities": {
            MacroDriver.input_cost:             -0.75,  # Palm oil, crude derivatives, agri commodities
            MacroDriver.commodity_pricing:      -0.65,
            MacroDriver.demand_volume:          +0.75,  # Rural disposable income, monsoon
            MacroDriver.interest_rates:         -0.15,  # Low debt exposure
            MacroDriver.market_sentiment:       +0.40,  # Defensive flight to safety
            MacroDriver.fx_exposure:            -0.20,  # Import of palm oil and packaging
            MacroDriver.regulatory_burden:      -0.25,
            MacroDriver.liquidity_availability: +0.15,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["Hindustan Unilever", "ITC", "Nestle India", "Dabur"],
        "pressured": ["Regional FMCG players unable to absorb raw material inflation"],
        "mechanism_templates": {
            "input_cost_up": "Surging agri-commodity, packaging, and crude derivative costs squeeze gross margins and require grammage adjustments.",
            "rural_demand_up": "Healthy monsoon and agricultural yields boost rural disposable income, driving volume growth for staple goods.",
            "default": "FMCG balances defensive pricing power and brand moat against raw material inflation and rural wage growth.",
        },
    },
    {
        "name": "Metals & Mining",
        "benchmark": "Nifty Metal",
        "ticker": "^CNXMETAL",
        "sensitivities": {
            MacroDriver.commodity_pricing:      +0.85,  # Direct price realization
            MacroDriver.demand_volume:          +0.80,  # Global and domestic infrastructure capex
            MacroDriver.input_cost:             -0.55,  # Coking coal, electricity, logistics
            MacroDriver.fx_exposure:            +0.35,  # Global dollar parity pricing
            MacroDriver.interest_rates:         -0.35,  # High capital intensity capex debt
            MacroDriver.regulatory_burden:      -0.45,  # Export duties, mining royalties
            MacroDriver.market_sentiment:       +0.60,  # High beta cyclicals
            MacroDriver.liquidity_availability: +0.25,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["Tata Steel", "JSW Steel", "Hindalco", "Vedanta"],
        "pressured": ["Pure re-rollers and secondary producers lacking captive iron/coal"],
        "mechanism_templates": {
            "commodity_up": "Rising global steel and non-ferrous metal benchmark prices boost blended realizations and operating cash flows.",
            "capex_up": "Government infrastructure spending and manufacturing capex accelerate domestic order flow.",
            "default": "Metals are high-beta cyclicals tied to global commodity cycles, Chinese industrial demand, and infrastructure outlays.",
        },
    },
    {
        "name": "Real Estate / Construction",
        "benchmark": "Nifty Realty",
        "ticker": "^CNXREALTY",
        "sensitivities": {
            MacroDriver.interest_rates:         -0.80,  # Mortgage interest rates & developer borrowing costs
            MacroDriver.input_cost:             -0.60,  # Cement, steel, labor, approval costs
            MacroDriver.demand_volume:          +0.85,  # Residential bookings & commercial leasing
            MacroDriver.liquidity_availability: +0.70,  # Construction finance & home loan availability
            MacroDriver.market_sentiment:       +0.55,
            MacroDriver.regulatory_burden:      -0.40,  # RERA compliance & local municipal approvals
            MacroDriver.fx_exposure:             0.00,
            MacroDriver.commodity_pricing:      -0.50,
            MacroDriver.credit_quality:         +0.40,
        },
        "beneficiaries": ["DLF", "Godrej Properties", "Macrotech Developers (Lodha)", "Oberoi Realty"],
        "pressured": ["Highly leveraged tier-2 regional developers"],
        "mechanism_templates": {
            "rates_up": "Escalating mortgage interest rates dampen homebuyer affordability and stretch inventory absorption timelines.",
            "rates_down": "Competitive home loan rates accelerate residential sales velocity and support developer cash conversion.",
            "default": "Realty performance is highly rate-sensitive, dependent on mortgage affordability, developer debt cost, and raw material inputs.",
        },
    },
    {
        "name": "Upstream Oil & Gas",
        "benchmark": "Nifty Energy",
        "ticker": "^CNXENERGY",
        "sensitivities": {
            MacroDriver.commodity_pricing:      +0.90,  # Direct net crude/gas realization per barrel
            MacroDriver.fx_exposure:            +0.45,  # Revenues dollar-denominated
            MacroDriver.regulatory_burden:      -0.60,  # Windfall profit taxes & special additional excise duties
            MacroDriver.input_cost:             -0.20,  # Rig rental and offshore exploration costs
            MacroDriver.demand_volume:          +0.30,
            MacroDriver.interest_rates:         -0.10,
            MacroDriver.market_sentiment:       +0.40,
            MacroDriver.liquidity_availability: +0.10,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["ONGC", "Oil India"],
        "pressured": ["Downstream entities during unhedged crude spikes"],
        "mechanism_templates": {
            "crude_up": "Higher crude benchmark prices translate directly to elevated wellhead realizations and upstream EBITDA expansion.",
            "windfall_tax": "Government imposition of windfall profit tax caps net realization upside above predetermined threshold prices.",
            "default": "Upstream exploration companies directly capture crude and natural gas realization gains, moderated by domestic cess and windfall taxes.",
        },
    },
    {
        "name": "Oil Marketing Companies (OMCs)",
        "benchmark": "Nifty Energy",
        "ticker": "^CNXENERGY",
        "sensitivities": {
            MacroDriver.commodity_pricing:      -0.75,  # High crude raises procurement cost; regulated retail pump price creates under-recoveries
            MacroDriver.fx_exposure:            -0.60,  # Crude bought in USD; weaker INR increases import bill
            MacroDriver.regulatory_burden:      -0.70,  # Retail fuel price caps, excise duty interventions
            MacroDriver.input_cost:             -0.80,
            MacroDriver.demand_volume:          +0.40,  # Fuel consumption volume
            MacroDriver.interest_rates:         -0.30,  # High working capital borrowing for crude inventory
            MacroDriver.market_sentiment:       +0.30,
            MacroDriver.liquidity_availability: +0.20,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["BPCL", "HPCL", "IOC"],
        "pressured": ["OMCs when crude surges without retail pump price revisions"],
        "mechanism_templates": {
            "crude_up": "Surging international crude benchmarks without retail pump price revisions compress marketing margins and require higher working capital.",
            "crude_down": "Softening crude prices restore robust retail marketing margins and lower working capital financing requirements.",
            "default": "OMCs operate on the spread between imported crude costs and regulated domestic retail fuel prices.",
        },
    },
    {
        "name": "Paints & Specialty Chemicals",
        "benchmark": "Nifty Commodities",
        "ticker": "^CNXCOMMODITIES",
        "sensitivities": {
            MacroDriver.input_cost:             -0.85,  # Crude derivatives (monomers, solvents, titanium dioxide) represent 50%+ of COGS
            MacroDriver.commodity_pricing:      -0.70,
            MacroDriver.fx_exposure:            -0.45,  # Imported feedstock cost in USD
            MacroDriver.demand_volume:          +0.75,  # Housing repainting, auto OEM coating, industrial demand
            MacroDriver.interest_rates:         -0.25,
            MacroDriver.regulatory_burden:      -0.30,
            MacroDriver.market_sentiment:       +0.40,
            MacroDriver.liquidity_availability: +0.15,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["Asian Paints", "Berger Paints", "Pidilite Industries", "SRF"],
        "pressured": ["Commodity chemical players lacking pricing power against new entrants"],
        "mechanism_templates": {
            "crude_up": "Crude derivative feedstock price inflation erodes gross margins unless offset by successive retail price hikes.",
            "crude_down": "Lower petrochemical raw material costs expand operating margins significantly and allow promotional discounting.",
            "default": "Paints and specialty chemical producers are heavily exposed to petrochemical derivatives and housing demand cycles.",
        },
    },
    {
        "name": "Aviation & Transport",
        "benchmark": "Nifty Services",
        "ticker": "^CNXSERVICE",
        "sensitivities": {
            MacroDriver.input_cost:             -0.90,  # Aviation Turbine Fuel (ATF) constitutes 35-40% of operating expenses
            MacroDriver.fx_exposure:            -0.65,  # Aircraft lease rentals, spare parts, and fuel are dollar-denominated
            MacroDriver.demand_volume:          +0.75,  # Passenger traffic load factor and yields
            MacroDriver.commodity_pricing:      -0.80,
            MacroDriver.interest_rates:         -0.35,  # Aircraft fleet debt/lease financing
            MacroDriver.regulatory_burden:      -0.45,  # Airport tariffs, aviation security fees, bilateral seat quotas
            MacroDriver.market_sentiment:       +0.40,
            MacroDriver.liquidity_availability: +0.20,
            MacroDriver.credit_quality:          0.00,
        },
        "beneficiaries": ["InterGlobe Aviation (IndiGo)", "SpiceJet"],
        "pressured": ["Airlines with unhedged FX lease liabilities during high oil regimes"],
        "mechanism_templates": {
            "crude_up": "Elevated Aviation Turbine Fuel (ATF) costs squeeze operating margins unless passed through airfares.",
            "inr_weak": "Currency depreciation inflates dollar-denominated aircraft lease rentals and maintenance overhaul expenses.",
            "default": "Aviation margins are intensely sensitive to crude-linked jet fuel expenses and dollar-denominated aircraft leasing.",
        },
    },
]


# ─── 3. Classification Engine ─────────────────────────────────────────────────

def classify_event_taxonomy(news_text: str, event: Optional[ExtractedEvent] = None) -> tuple[EventTaxonomyCategory, str]:
    """
    Classifies news text into one of 13 Event Taxonomy categories using
    structured pattern matching, entity context, and semantic keywords.
    """
    text_lower = news_text.lower()
    
    # Priority matching based on extracted event type if available
    if event and event.primary_node:
        p_node = event.primary_node.lower()
        if "repo" in p_node or "interest rate" in p_node:
            return EventTaxonomyCategory.monetary_policy, TAXONOMY_META[EventTaxonomyCategory.monetary_policy]["label"]
        if "crude" in p_node or "oil" in p_node or "gold" in p_node:
            return EventTaxonomyCategory.commodity_shock, TAXONOMY_META[EventTaxonomyCategory.commodity_shock]["label"]
        if "usd/inr" in p_node or "rupee" in p_node or "currency" in p_node:
            return EventTaxonomyCategory.fx_currency, TAXONOMY_META[EventTaxonomyCategory.fx_currency]["label"]
        if "inflation" in p_node or "cad" in p_node:
            return EventTaxonomyCategory.inflation_macro, TAXONOMY_META[EventTaxonomyCategory.inflation_macro]["label"]

    # Score categories by keyword frequency and weight
    best_cat = EventTaxonomyCategory.general_macro
    max_score = 0

    for cat, meta in TAXONOMY_META.items():
        score = 0
        for kw in meta["keywords"]:
            if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                # Higher weight for compound phrases
                score += 2 if " " in kw else 1
        if score > max_score:
            max_score = score
            best_cat = cat

    # Fallback checks if no explicit score
    if max_score == 0:
        if any(w in text_lower for w in ["oil", "fuel", "gas", "petrol", "diesel"]):
            best_cat = EventTaxonomyCategory.commodity_shock
        elif any(w in text_lower for w in ["bank", "rate", "rbi", "yield"]):
            best_cat = EventTaxonomyCategory.monetary_policy
        elif any(w in text_lower for w in ["dollar", "rupee", "currency", "inr"]):
            best_cat = EventTaxonomyCategory.fx_currency
        else:
            best_cat = EventTaxonomyCategory.general_macro

    label = TAXONOMY_META.get(best_cat, {}).get("label", "Macroeconomic & Market Transmission")
    return best_cat, label


# ─── 4. Macroeconomic Driver Activation Engine ────────────────────────────────

def evaluate_macro_drivers(
    category: EventTaxonomyCategory,
    news_text: str,
    direction: Sign,
) -> list[DriverImpact]:
    """
    Evaluates which of the 9 macroeconomic drivers are activated by the event,
    their directional sign, intensity (0.0 to 1.0), and transmission reasoning.
    """
    text_lower = news_text.lower()
    is_up = (direction == Sign.positive)
    drivers: list[DriverImpact] = []

    # Detect magnitude/intensity clues
    intensity_mult = 1.0
    if any(w in text_lower for w in ["surge", "spikes", "sharp", "plunge", "crisis", "soar", "huge"]):
        intensity_mult = 1.2
    elif any(w in text_lower for w in ["mild", "slight", "modest", "gradual", "moderate"]):
        intensity_mult = 0.7

    # Helper to bound intensity
    def clamp_intensity(val: float) -> float:
        return min(0.95, max(0.15, round(val * intensity_mult, 2)))

    if category == EventTaxonomyCategory.commodity_shock:
        # Crude or commodity spike
        if is_up:
            drivers.append(DriverImpact(
                driver=MacroDriver.commodity_pricing,
                name="Commodity Pricing Realization",
                direction=Sign.positive,
                intensity=clamp_intensity(0.85),
                reasoning="Elevated global commodity spot and futures benchmarks lift realization for raw material producers.",
            ))
            drivers.append(DriverImpact(
                driver=MacroDriver.input_cost,
                name="Input Cost Inflation",
                direction=Sign.positive,
                intensity=clamp_intensity(0.80),
                reasoning="Surging energy, transport, and raw material derivative costs directly inflate downstream manufacturing and operating expenses.",
            ))
            drivers.append(DriverImpact(
                driver=MacroDriver.fx_exposure,
                name="Import Bill & Currency Pressure",
                direction=Sign.positive,
                intensity=clamp_intensity(0.65),
                reasoning="Heavier dollar requirements for commodity imports widen the trade balance and exert depreciation pressure on the INR.",
            ))
        else:
            drivers.append(DriverImpact(
                driver=MacroDriver.input_cost,
                name="Input Cost Relief",
                direction=Sign.negative,
                intensity=clamp_intensity(0.80),
                reasoning="Cooling commodity and energy prices lower procurement expenses, widening gross margins across consuming sectors.",
            ))
            drivers.append(DriverImpact(
                driver=MacroDriver.commodity_pricing,
                name="Producer Realization Softening",
                direction=Sign.negative,
                intensity=clamp_intensity(0.75),
                reasoning="Lower commodity prices compress selling realizations and operating cash flows for extraction companies.",
            ))

    elif category == EventTaxonomyCategory.monetary_policy:
        if is_up:
            drivers.append(DriverImpact(
                driver=MacroDriver.interest_rates,
                name="Interest Rate & Yield Curve Hike",
                direction=Sign.positive,
                intensity=clamp_intensity(0.85),
                reasoning="Policy rate hikes increase benchmark borrowing costs across corporate loans, retail credit, and sovereign bond yields.",
            ))
            drivers.append(DriverImpact(
                driver=MacroDriver.liquidity_availability,
                name="System Liquidity Tightening",
                direction=Sign.negative,
                intensity=clamp_intensity(0.65),
                reasoning="Monetary tightening absorbs surplus banking system liquidity, raising interbank and commercial deposit rates.",
            ))
            drivers.append(DriverImpact(
                driver=MacroDriver.demand_volume,
                name="Credit-Sensitive Demand Moderation",
                direction=Sign.negative,
                intensity=clamp_intensity(0.55),
                reasoning="Costlier auto loans and residential mortgages cool discretionary retail big-ticket purchases.",
            ))
        else:
            drivers.append(DriverImpact(
                driver=MacroDriver.interest_rates,
                name="Interest Rate Easing",
                direction=Sign.negative,
                intensity=clamp_intensity(0.80),
                reasoning="Policy rate reduction reduces lending costs, stimulating credit demand and unlocking bond treasury gains.",
            ))
            drivers.append(DriverImpact(
                driver=MacroDriver.liquidity_availability,
                name="System Liquidity Expansion",
                direction=Sign.positive,
                intensity=clamp_intensity(0.70),
                reasoning="Accommodative monetary stance expands available banking liquidity and reduces cost of funds.",
            ))

    elif category == EventTaxonomyCategory.fx_currency:
        # USD/INR rising = rupee weakening
        if is_up:
            drivers.append(DriverImpact(
                driver=MacroDriver.fx_exposure,
                name="Rupee Depreciation (USD/INR Up)",
                direction=Sign.positive,
                intensity=clamp_intensity(0.85),
                reasoning="Weaker rupee provides a direct margin windfall for USD/EUR export billings while raising landed import costs.",
            ))
            drivers.append(DriverImpact(
                driver=MacroDriver.input_cost,
                name="Imported Inflation & Raw Material Cost",
                direction=Sign.positive,
                intensity=clamp_intensity(0.60),
                reasoning="Landed costs for dollar-denominated imported goods (crude, electronics, chemicals, active pharma ingredients) rise.",
            ))
        else:
            drivers.append(DriverImpact(
                driver=MacroDriver.fx_exposure,
                name="Rupee Appreciation (USD/INR Down)",
                direction=Sign.negative,
                intensity=clamp_intensity(0.80),
                reasoning="Stronger rupee lowers import bills for domestic manufacturers but compresses net rupee realization on IT/Pharma exports.",
            ))

    elif category == EventTaxonomyCategory.inflation_macro:
        drivers.append(DriverImpact(
            driver=MacroDriver.input_cost,
            name="Retail & Wholesale Price Inflation",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.75),
            reasoning="Broad-based price pressure elevates operating costs across raw materials, packaging, and logistics.",
        ))
        drivers.append(DriverImpact(
            driver=MacroDriver.interest_rates,
            name="Tightening Policy Expectations",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.70),
            reasoning="Persistent inflation triggers heightened expectations of central bank policy rate tightening and higher bond yields.",
        ))

    elif category == EventTaxonomyCategory.fiscal_policy:
        drivers.append(DriverImpact(
            driver=MacroDriver.demand_volume,
            name="Government Capex & Fiscal Stimulus",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.80),
            reasoning="Budgetary allocations to infrastructure, manufacturing PLI schemes, and public capex drive order inflows.",
        ))
        drivers.append(DriverImpact(
            driver=MacroDriver.regulatory_burden,
            name="Fiscal Duty & Tax Adjustments",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.50),
            reasoning="Customs tariffs, GST revisions, and sector-specific incentives shift relative corporate margin structures.",
        ))

    elif category == EventTaxonomyCategory.geopolitical_trade or category == EventTaxonomyCategory.regulatory_policy:
        drivers.append(DriverImpact(
            driver=MacroDriver.regulatory_burden,
            name="Regulatory & Trade Compliance Friction",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.80),
            reasoning="Trade barriers, tariffs, licensing mandates, or compliance audits increase operational friction and market access costs.",
        ))
        drivers.append(DriverImpact(
            driver=MacroDriver.input_cost,
            name="Supply Chain Friction & Logistics Premium",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.65),
            reasoning="Alternative route logistics, freight insurance surcharges, and compliance overheads lift landed costs.",
        ))

    else:
        # Default macro transmission
        drivers.append(DriverImpact(
            driver=MacroDriver.market_sentiment,
            name="Market Risk Sentiment & Liquidity",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.60),
            reasoning="Macro event influences foreign portfolio flows (FPI), equity valuation multiples, and sectoral risk premiums.",
        ))
        drivers.append(DriverImpact(
            driver=MacroDriver.demand_volume,
            name="Aggregate Demand & Corporate Revenue",
            direction=Sign.positive if is_up else Sign.negative,
            intensity=clamp_intensity(0.55),
            reasoning="Underlying economic velocity and consumer sentiment drive volume growth across cyclical sectors.",
        ))

    return drivers


# ─── 5. Dynamic Sector Matrix Generator ───────────────────────────────────────

def compute_dynamic_sector_matrix(
    news_text: str,
    event: ExtractedEvent,
    propagated_assets: Optional[list] = None,
) -> DynamicSectorMatrix:
    """
    Computes the full dynamic sector exposure matrix by combining event taxonomy,
    active macroeconomic drivers, and empirical sectoral sensitivity models.
    """
    category, cat_label = classify_event_taxonomy(news_text, event)
    direction = event.direction
    active_drivers = evaluate_macro_drivers(category, news_text, direction)

    # Driver impact map for quick calculation: driver -> signed float value
    driver_val_map: dict[MacroDriver, float] = {}
    for d in active_drivers:
        sign_mult = 1.0 if d.direction == Sign.positive else (-1.0 if d.direction == Sign.negative else 0.0)
        driver_val_map[d.driver] = sign_mult * d.intensity

    positive_sectors: list[SectorExposureItem] = []
    negative_sectors: list[SectorExposureItem] = []
    mixed_sectors: list[SectorExposureItem] = []
    neutral_sectors: list[SectorExposureItem] = []

    for profile in SECTOR_PROFILES:
        sector_name = profile["name"]
        sensitivities = profile["sensitivities"]
        
        # Calculate net score = sum(driver_impact * sensitivity)
        contributions: list[tuple[str, float]] = []
        pos_force = 0.0
        neg_force = 0.0

        for driver, val in driver_val_map.items():
            sens = sensitivities.get(driver, 0.0)
            effect = val * sens
            if abs(effect) > 0.05:
                contributions.append((driver.value, effect))
                if effect > 0:
                    pos_force += effect
                else:
                    neg_force += abs(effect)

        net_score = pos_force - neg_force
        # Bound net score to [-1.0, 1.0]
        net_score = max(-1.0, min(1.0, round(net_score, 2)))

        # Active driver names
        active_driver_names = [c[0].replace("_", " ").title() for c in contributions]

        # Determine mechanism explanation
        mech = profile["mechanism_templates"].get("default", "")
        if "interest_rates" in driver_val_map:
            if driver_val_map[MacroDriver.interest_rates] > 0 and "rates_up" in profile["mechanism_templates"]:
                mech = profile["mechanism_templates"]["rates_up"]
            elif driver_val_map[MacroDriver.interest_rates] < 0 and "rates_down" in profile["mechanism_templates"]:
                mech = profile["mechanism_templates"]["rates_down"]
        elif "input_cost" in driver_val_map and driver_val_map[MacroDriver.input_cost] > 0 and "input_cost_up" in profile["mechanism_templates"]:
            mech = profile["mechanism_templates"]["input_cost_up"]
        elif "fx_exposure" in driver_val_map and driver_val_map[MacroDriver.fx_exposure] > 0 and "inr_weak" in profile["mechanism_templates"]:
            mech = profile["mechanism_templates"]["inr_weak"]
        elif "commodity_pricing" in driver_val_map:
            if driver_val_map[MacroDriver.commodity_pricing] > 0 and "crude_up" in profile["mechanism_templates"]:
                mech = profile["mechanism_templates"]["crude_up"]
            elif driver_val_map[MacroDriver.commodity_pricing] > 0 and "commodity_up" in profile["mechanism_templates"]:
                mech = profile["mechanism_templates"]["commodity_up"]
            elif driver_val_map[MacroDriver.commodity_pricing] < 0 and "crude_down" in profile["mechanism_templates"]:
                mech = profile["mechanism_templates"]["crude_down"]

        # Confidence is derived from driver intensity and sensitivity magnitude
        conf = round(min(0.92, max(0.35, (pos_force + neg_force) * 0.65)), 2)

        item = SectorExposureItem(
            sector_name=sector_name,
            benchmark_index=profile["benchmark"],
            ticker=profile.get("ticker"),
            impact_category="neutral",
            net_score=net_score,
            confidence=conf,
            transmission_mechanism=mech,
            active_drivers=active_driver_names,
            key_beneficiaries=profile.get("beneficiaries", []),
            key_pressured=profile.get("pressured", []),
        )

        # Do not include sectors with no active driver mechanism
        if not active_driver_names or (abs(net_score) < 0.05 and pos_force < 0.15 and neg_force < 0.15):
            continue

        # Categorization logic
        if pos_force > 0.20 and neg_force > 0.20:
            item.impact_category = "mixed"
            mixed_sectors.append(item)
        elif net_score >= 0.10:
            item.impact_category = "positive"
            positive_sectors.append(item)
        elif net_score <= -0.10:
            item.impact_category = "negative"
            negative_sectors.append(item)
        else:
            item.impact_category = "neutral"
            neutral_sectors.append(item)

    # Sort each bucket by net score magnitude / confidence
    positive_sectors.sort(key=lambda s: s.net_score, reverse=True)
    negative_sectors.sort(key=lambda s: s.net_score)
    mixed_sectors.sort(key=lambda s: s.confidence, reverse=True)
    neutral_sectors.sort(key=lambda s: s.confidence, reverse=True)

    summary_text = (
        f"Event classified under '{cat_label}'. "
        f"Activated {len(active_drivers)} macroeconomic transmission channels, identifying "
        f"{len(positive_sectors)} positively positioned sectors, {len(negative_sectors)} pressured sectors, "
        f"and {len(mixed_sectors)} sectors experiencing cross-current drivers."
    )

    methodology = (
        "Sector exposure matrix evaluates dynamic directional sensitivity across NSE sector benchmarks "
        "based on fundamental cost structures, foreign exchange billing currency, pricing power, and monetary sensitivity. "
        "Scores reflect structural economic transmission channels, not guarantees of price performance."
    )

    return DynamicSectorMatrix(
        event_category=category,
        event_category_label=cat_label,
        event_summary=summary_text,
        active_drivers=active_drivers,
        positive_sectors=positive_sectors,
        negative_sectors=negative_sectors,
        mixed_sectors=mixed_sectors,
        neutral_sectors=neutral_sectors,
        methodology_note=methodology,
    )

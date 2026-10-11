"""Domain knowledge: sector lexicon, event patterns, sector-effect rules, gazetteers.

Used by Phase 2 (feature extraction) and by the offline fallback engine in llm.py.
Everything here is plain data, so it is easy to extend.
"""
import re


def _any(terms):
    return re.compile(r"\b(?:%s)\b" % "|".join(re.escape(t) for t in terms), re.I)


SECTORS = {
    "Banking & Finance": ["bank", "banks", "banking", "lender", "lenders", "nbfc", "loan", "loans", "credit",
                          "sbi", "axis bank", "kotak", "financial services"],
    "Real Estate": ["real estate", "realty", "housing", "home loan", "home loans", "emi", "emis", "property",
                    "properties", "developer", "developers", "dlf", "mortgage"],
    "Automobile": ["auto", "autos", "automobile", "automobiles", "car", "cars", "vehicle", "vehicles", "ev", "evs",
                   "tata motors", "maruti", "mahindra", "two-wheeler"],
    "Energy": ["oil", "crude", "gas", "petroleum", "opec", "refinery", "refiners", "refining", "ongc",
               "reliance industries", "brent", "energy", "fuel"],
    "Aviation": ["airline", "airlines", "aviation", "indigo", "air india", "aircraft", "jet fuel", "interglobe"],
    "IT Services": ["it services", "software", "infosys", "tcs", "wipro", "hcl", "tech mahindra", "it sector",
                    "nasscom", "outsourcing"],
    "Pharma & Healthcare": ["pharma", "pharmaceutical", "pharmaceuticals", "drug", "drugs", "sun pharma", "cipla",
                            "healthcare", "usfda", "hospital", "hospitals"],
    "FMCG": ["fmcg", "consumer goods", "hindustan unilever", "itc", "nestle", "britannia", "packaged food",
             "packaged-goods"],
    "Metals & Mining": ["steel", "metal", "metals", "aluminium", "aluminum", "copper", "tata steel", "jsw",
                        "hindalco", "mining", "iron ore"],
    "Telecom": ["telecom", "telecoms", "jio", "airtel", "5g", "spectrum"],
    "Paints & Chemicals": ["paint", "paints", "asian paints", "chemical", "chemicals", "specialty chemicals",
                           "pigment"],
}
SECTOR_RE = {s: _any(t) for s, t in SECTORS.items()}

# Marketaux "industry" field -> our sector (only used when the name itself gives no hint)
INDUSTRY_MAP = {
    "Financial Services": "Banking & Finance",
    "Financial": "Banking & Finance",
    "Energy": "Energy",
    "Technology": "IT Services",
    "Healthcare": "Pharma & Healthcare",
    "Consumer Defensive": "FMCG",
    "Basic Materials": "Metals & Mining",
    "Real Estate": "Real Estate",
    "Communication Services": "Telecom",
}


def sector_for_name(name: str):
    for s, rx in SECTOR_RE.items():
        if rx.search(name or ""):
            return s
    return None


MACRO = {
    "RBI": re.compile(r"\b(RBI|Reserve Bank(?: of India)?)\b"),
    "OPEC": re.compile(r"\bOPEC\b"),
    "SEBI": re.compile(r"\bSEBI\b"),
    "US Federal Reserve": re.compile(r"\b(Federal Reserve|the Fed|FOMC)\b"),
}
COMMODITIES = {
    "Crude Oil": re.compile(r"\b(crude oil|crude|brent)\b", re.I),
    "Gold": re.compile(r"\bgold\b", re.I),
    "Natural Gas": re.compile(r"\bnatural gas\b", re.I),
    "Copper": re.compile(r"\bcopper\b", re.I),
}

# (event_type, human label, regex). A rule can fire more than once per article.
_I = re.I
EVENT_RULES = [
    ("rate_hold", "Interest rate hold",
     re.compile(r"(?=.*\brates?\b)(?=.*\b(unchanged|steady|on hold|pause[sd]?|holds?)\b)", _I | re.S)),
    ("rate_hike", "Interest rate hike",
     re.compile(r"\b(hikes?|raises?|raised|increases?|lifts?)\b[^.]{0,40}\brates?\b|\brate hikes?\b", _I)),
    ("rate_cut", "Interest rate cut",
     re.compile(r"\b(cuts?|lowers?|reduces?|slash\w*)\b[^.]{0,40}\brates?\b|\brate cuts?\b", _I)),
    ("oil_surge", "Crude oil surge",
     re.compile(r"\b(crude|oil|brent)\b[^.]{0,60}\b(surge[sd]?|jump\w*|spike[sd]?|rall\w+|climb\w*|soar\w*|rise[sn]?|rose|gains?)\b"
                r"|\b(surge\w*|jump\w*|spike\w*)\b[^.]{0,40}\b(crude|oil|brent)\b", _I)),
    ("oil_drop", "Crude oil drop",
     re.compile(r"\b(crude|oil|brent)\b[^.]{0,60}\b(falls?|fell|drop\w*|slump\w*|plunge\w*|tumble\w*|declin\w*|slide\w*|slid|eases?|eased)\b", _I)),
    ("inflation_up", "Inflation rise",
     re.compile(r"\binflation\b[^.]{0,40}\b(rises?|rose|climbs?|accelerat\w+|higher|surges?|jumps?)\b", _I)),
    ("inflation_down", "Inflation cooling",
     re.compile(r"\binflation\b[^.]{0,40}\b(eases?|cools?|falls?|fell|slows?|declines?)\b", _I)),
    ("earnings_beat", "Earnings beat",
     re.compile(r"\b(beats?|tops?|exceeds?|surpass\w*)\b[^.]{0,40}\b(estimates?|expectations?|forecasts?)\b"
                r"|\b(profit|earnings|revenue)\b[^.]{0,30}\b(jumps?|surges?|rises?|rose|grows?)\b|record (profit|earnings)", _I)),
    ("earnings_miss", "Earnings miss",
     re.compile(r"\b(misses?|missed|falls? short)\b[^.]{0,40}\b(estimates?|expectations?)\b"
                r"|\b(profit|earnings)\b[^.]{0,30}\b(falls?|fell|drops?|declines?|slumps?)\b", _I)),
    ("regulation", "Regulatory action",
     re.compile(r"\b(sebi|regulator|probe|penalt\w+|crackdown|new rules?)\b|\bban(s|ned)?\b", _I)),
    ("merger", "Merger / acquisition",
     re.compile(r"\b(acquir\w+|acquisition|merger|takeover|buyout|stake sale)\b", _I)),
    ("tariff_trade", "Tariff / trade action",
     re.compile(r"\b(tariffs?|export curbs?|sanctions?|trade war|import dut\w+)\b", _I)),
    ("supply_disruption", "Supply disruption",
     re.compile(r"\b(supply[- ](chain )?(disruption|shortage)|shortage|outage|shutdown)\b", _I)),
    ("liquidity_tightening", "Banking liquidity tightening / CRR hike",
     re.compile(r"\b(crr|cash reserve|liquidity)\b[^.]{0,60}\b(tighten\w*|absorb\w*|drain\w*|elevat\w*|curb\w*|rules?)\b|\b(tighten\w*|drain\w*)\b[^.]{0,40}\b(liquidity|cash reserve|crr)\b", _I)),
    ("liquidity_infusion", "Banking liquidity easing / CRR cut",
     re.compile(r"\b(crr|cash reserve|liquidity)\b[^.]{0,60}\b(eas\w*|cut\w*|inject\w*|infus\w*|surplus)\b", _I)),
]

EVENT_FAMILY = {
    "rate_hold": "monetary_policy", "rate_hike": "monetary_policy", "rate_cut": "monetary_policy",
    "liquidity_tightening": "monetary_policy", "liquidity_infusion": "monetary_policy",
    "oil_surge": "crude_oil", "oil_drop": "crude_oil",
    "inflation_up": "inflation", "inflation_down": "inflation",
    "earnings_beat": "earnings", "earnings_miss": "earnings",
    "regulation": "regulation", "merger": "merger",
    "tariff_trade": "trade", "supply_disruption": "supply",
}
# Families whose news is comparable even across different companies
MACRO_FAMILIES = {"monetary_policy", "crude_oil", "inflation"}

EVENT_HORIZON = {"rate_hike": "medium", "rate_cut": "medium", "rate_hold": "short",
                 "liquidity_tightening": "short", "liquidity_infusion": "short",
                 "oil_surge": "short", "oil_drop": "short", "inflation_up": "medium", "inflation_down": "medium"}

# event -> [(sector, score -1..1, mechanism)]. "*" = applies to the sectors detected in the article.
EVENT_SECTOR_EFFECTS = {
    "liquidity_tightening": [
        ("Banking & Finance", -0.45, "Higher cash reserve requirements lock up bank balances without interest, reducing loanable surplus and compressing margins."),
        ("Real Estate", -0.35, "Tighter system liquidity exerts upward pressure on short-term lending rates."),
        ("Automobile", -0.25, "Higher funding costs for non-banking finance companies and retail lenders constrain vehicle financing."),
    ],
    "liquidity_infusion": [
        ("Banking & Finance", 0.45, "Easing reserve requirements releases funds back into commercial banks, lowering short-term rates."),
        ("Real Estate", 0.35, "Plentiful system liquidity keeps lending rates low and supports credit off-take."),
        ("Automobile", 0.25, "Affordable wholesale funding encourages auto loan disbursement."),
    ],
    "rate_hike": [
        ("Real Estate", -0.65, "A higher repo rate raises home-loan EMIs, which dampens housing demand and developer sales."),
        ("Automobile", -0.45, "Costlier vehicle loans weigh on retail auto demand, especially entry-level segments."),
        ("Banking & Finance", -0.25, "Faster policy transmission can lift margins, but slower loan growth and bond-portfolio mark-to-market losses weigh on banks near term."),
    ],
    "rate_cut": [
        ("Real Estate", 0.6, "Cheaper home loans lower EMIs and revive housing demand."),
        ("Automobile", 0.4, "Lower financing costs support vehicle purchases."),
        ("Banking & Finance", 0.3, "Lower funding costs and revived credit demand support loan growth."),
    ],
    "rate_hold": [
        ("Real Estate", 0.4, "The pause removes the threat of further EMI increases and helps housing sentiment recover."),
        ("Automobile", 0.25, "Stable financing costs let buyers who were waiting on loan rates return."),
        ("Banking & Finance", 0.35, "Policy certainty supports valuations and the credit-growth outlook."),
    ],
    "oil_surge": [
        ("Energy", 0.6, "Higher crude prices lift upstream realisations and refining margins."),
        ("Aviation", -0.65, "Jet fuel is a major airline cost, so higher crude squeezes margins."),
        ("Paints & Chemicals", -0.4, "Crude-linked raw materials raise input costs for paint and chemical makers."),
    ],
    "oil_drop": [
        ("Energy", -0.5, "Lower crude prices cut upstream realisations and refining margins."),
        ("Aviation", 0.6, "Cheaper jet fuel directly eases airline operating costs."),
        ("Paints & Chemicals", 0.4, "Softer crude-linked raw material prices improve margins."),
    ],
    "inflation_up": [
        ("FMCG", -0.4, "Higher food and fuel costs squeeze margins of packaged-goods makers."),
        ("Automobile", -0.2, "Rising household costs reduce discretionary spending on vehicles."),
        ("Banking & Finance", -0.15, "Higher inflation raises the odds of tighter policy and rate-sensitive pressure."),
    ],
    "inflation_down": [
        ("FMCG", 0.35, "Cooling input costs help margins of packaged-goods makers."),
        ("Banking & Finance", 0.2, "Lower inflation improves the chance of easier policy."),
        ("Real Estate", 0.2, "Lower inflation raises hopes of lower borrowing costs."),
    ],
    "earnings_beat": [("*", 0.5, "An earnings beat signals stronger demand and margins for this sector's players.")],
    "earnings_miss": [("*", -0.5, "An earnings miss signals weaker demand or margins for this sector's players.")],
    "regulation": [("*", -0.25, "Regulatory action raises compliance cost and uncertainty for the sector.")],
    "merger": [("*", 0.2, "Consolidation can signal improved pricing power and scale benefits.")],
    "tariff_trade": [("*", -0.3, "Trade barriers raise costs or cut export demand for the sector.")],
    "supply_disruption": [("*", -0.35, "Supply disruption raises costs and delays deliveries for the sector.")],
}


def effects_for(event_type, detected_sectors):
    out = []
    for sector, score, why in EVENT_SECTOR_EFFECTS.get(event_type, []):
        if sector == "*":
            out.extend((s, score, why) for s in detected_sectors[:2])
        else:
            out.append((sector, score, why))
    return out


POS_WORDS = {"gain", "gains", "gained", "rise", "rises", "rose", "rally", "rallied", "beat", "beats", "growth",
             "profit", "upgrade", "rebound", "rebounded", "surge", "surges", "surged", "strong", "record",
             "advanced", "boosting", "lifted", "easing", "benefiting", "improve", "improved"}
NEG_WORDS = {"fall", "falls", "fell", "slump", "slumps", "loss", "losses", "miss", "misses", "downgrade",
             "pressure", "pressuring", "dampen", "slip", "slipped", "slides", "slid", "weak", "fear", "worry",
             "worries", "concern", "squeezing", "weigh", "lower", "decline", "declined"}

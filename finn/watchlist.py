"""Default NSE watchlist and research shortcuts."""

PORTFOLIO = [
    ("RELIANCE", "Reliance Industries", "Energy & retail", "Large"),
    ("TCS", "Tata Consultancy Services", "IT services", "Large"),
    ("HDFCBANK", "HDFC Bank", "Banking", "Large"),
    ("INFY", "Infosys", "IT services", "Large"),
    ("BHARTIARTL", "Bharti Airtel", "Telecom", "Large"),
    ("ITC", "ITC", "Consumer", "Large"),
    ("LT", "Larsen & Toubro", "Industrials", "Large"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Healthcare", "Large"),
    ("TMPV", "Tata Motors Passenger Vehicles", "Automotive", "Large"),
    ("TITAN", "Titan Company", "Consumer", "Large"),
    ("ASIANPAINT", "Asian Paints", "Materials", "Large"),
    ("POWERGRID", "Power Grid Corporation", "Utilities", "Large"),
    ("DIXON", "Dixon Technologies", "Electronics", "Mid"),
    ("PERSISTENT", "Persistent Systems", "IT services", "Mid"),
    ("APLAPOLLO", "APL Apollo Tubes", "Materials", "Mid"),
    ("KAYNES", "Kaynes Technology", "Electronics", "Mid"),
    ("KPRMILL", "KPR Mill", "Textiles", "Small / mid"),
    ("CERA", "Cera Sanitaryware", "Building products", "Small"),
]
RESEARCH_COMPANIES = [
    ("TCS", "Tata Consultancy Services"),
    ("INFY", "Infosys"),
    ("HINDUNILVR", "Hindustan Unilever"),
    ("TRENT", "Trent"),
    ("POLYCAB", "Polycab India"),
]


def portfolio():
    return [dict(zip(("symbol", "name", "sector", "size"), item)) for item in PORTFOLIO]

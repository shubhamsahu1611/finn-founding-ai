"""Fictional profiles and relationships for the Network demo.

Public company names identify the scenario. The people, affiliations,
company relationships, and contact history are invented.
"""

from datetime import date
from typing import NamedTuple


class Role(NamedTuple):
    company: str
    title: str
    start: int
    end: int | None = None  # Exclusive year, or open-ended.


class Education(NamedTuple):
    school: str
    programme: str
    start: int
    end: int


class Profile(NamedTuple):
    name: str
    bio: str
    roles: tuple[Role, ...]
    themes: tuple[str, ...]
    relationship: str | None = None
    education: tuple[Education, ...] = ()
    last_spoke: date | None = None


ORGANISATIONS = {
    "HDFCBANK": ("HDFC Bank", ()),
    "TCS": ("Tata Consultancy Services", ()),
    "INFY": ("Infosys", ()),
    "PERSISTENT": ("Persistent Systems", ()),
    "DIXON": ("Dixon Technologies", ("Dixon",)),
    "KAYNES": ("Kaynes Technology", ("Kaynes",)),
    "RELIANCE": ("Reliance Industries", ("Reliance",)),
    "HINDUNILVR": ("Hindustan Unilever", ("HUL",)),
    "TRENT": ("Trent", ()),
    "POLYCAB": ("Polycab India", ("Polycab",)),
    "cedar": ("Cedar Commercial Bank", ("Cedar",)),
    "harbour": ("Harbour Commercial Bank", ("Harbour",)),
    "meridian": ("Meridian Components", ("Meridian",)),
    "fieldstone": ("Fieldstone Devices", ("Fieldstone",)),
    "suryafield": ("Surya Field Energy", ()),
}

THEMES = {
    "semiconductors": ("Semiconductors", ("semiconductor", "chip packaging", "chips")),
    "manufacturing": ("Electronics manufacturing", ("electronics", "plant ramp")),
    "lending": ("Rural lending", ("rural credit", "rural banking")),
    "treasury": ("Bank treasury", ("treasury", "bank finance")),
    "it": ("IT services", ("outsourcing", "technology services")),
    "consumer": ("Consumer distribution", ("distribution", "retail distribution")),
    "energy": ("Clean energy", ("renewables", "clean-energy")),
    "cables": ("Cables and electricals", ("cables", "electricals")),
}

# Directions are from the company being researched to the contact's employer.
COMPANY_LINKS = {
    "DIXON": {"KAYNES": "peer", "meridian": "supplier", "fieldstone": "customer"},
    "KAYNES": {"DIXON": "peer", "meridian": "supplier"},
    "TCS": {"INFY": "peer", "PERSISTENT": "peer"},
    "INFY": {"TCS": "peer", "PERSISTENT": "peer"},
    "RELIANCE": {"suryafield": "sector peer"},
}

PROFILES = {
    "ananya": Profile(
        "Ananya Rao",
        "A fictional executive profile for rehearsing introductions. Her career spans treasury, financial control and planning.",
        (
            Role("harbour", "Chief Financial Officer", 2026),
            Role("cedar", "Head of Treasury and Financial Control", 2015, 2022),
        ),
        ("treasury", "lending"),
        education=(Education("Westbridge School of Management", "MBA", 2003, 2005),),
    ),
    "dev": Profile(
        "Dev Menon",
        "Built treasury controls through a funding squeeze and a multi-year balance-sheet transition.",
        (
            Role("cedar", "Treasury Risk Lead", 2017, 2020),
            Role("HDFCBANK", "Asset and Liability Management Lead", 2021),
        ),
        ("treasury",),
        "Former colleague",
        last_spoke=date(2026, 6, 9),
    ),
    "isha": Profile(
        "Isha Bhat",
        "Ran regional credit teams and worked on underwriting outside major metros.",
        (Role("cedar", "Rural Credit Director", 2022),),
        ("lending",),
        "Business-school acquaintance",
        (Education("Westbridge School of Management", "MBA", 2004, 2006),),
        date(2026, 8, 18),
    ),
    "arjun": Profile(
        "Arjun Mehta",
        "Has taken electronics production lines from commissioning through volume ramp.",
        (
            Role("DIXON", "Plant Operations Lead", 2018, 2024),
            Role("KAYNES", "Manufacturing Program Director", 2024),
        ),
        ("manufacturing", "semiconductors"),
        "Met through an industry roundtable",
        last_spoke=date(2026, 4, 22),
    ),
    "leena": Profile(
        "Leena Shah",
        "Works on packaging yield, component qualification and supplier readiness.",
        (Role("meridian", "Component Engineering Lead", 2020),),
        ("semiconductors", "manufacturing"),
        "Former project collaborator",
        last_spoke=date(2026, 10, 23),
    ),
    "vikram": Profile(
        "Vikram Desai",
        "Leads vendor qualification and capacity planning for an electronics brand.",
        (Role("fieldstone", "Director of Sourcing", 2021),),
        ("manufacturing",),
        "Industry acquaintance",
    ),
    "rohan": Profile(
        "Rohan Kulkarni",
        "Negotiated enterprise outsourcing contracts and managed large delivery transitions.",
        (
            Role("TCS", "Client Delivery Director", 2017, 2023),
            Role("INFY", "Enterprise Account Lead", 2023),
        ),
        ("it",),
        "Former colleague",
        last_spoke=date(2026, 5, 12),
    ),
    "meera": Profile(
        "Meera Thomas",
        "Managed distributor incentives and led a national retail rollout.",
        (
            Role("HINDUNILVR", "Channel Strategy Lead", 2016, 2022),
            Role("TRENT", "Retail Operations Director", 2022),
        ),
        ("consumer",),
        "Former classmate",
    ),
    "neel": Profile(
        "Neel Joshi",
        "Has evaluated equipment capex, project commissioning and supplier bottlenecks.",
        (
            Role("POLYCAB", "Industrial Sales Lead", 2019, 2024),
            Role("suryafield", "Project Commercial Lead", 2024),
        ),
        ("energy", "cables"),
        "Met through an industry roundtable",
    ),
}

# Reported in the mock contact records, independent of inferred overlap.
KNOWN_LINKS = {
    ("dev", "ananya"): "Dev recorded working with Ananya on Cedar's treasury controls.",
}

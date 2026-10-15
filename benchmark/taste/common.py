"""Taste track: shared constants, frozen at F0. See PROTOCOL.md."""

import hashlib
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"                               # public: charts, items, picks, results
PRIVATE = ROOT / "spike" / "out" / "taste"         # ignored: raw pages, raw Qloo and Gemini responses
sys.path.insert(0, str(ROOT / "service"))

SALT = "room-taste-pilot-2026"
SEED = 20261016
GEMINI = "gemini-3.7-flash"
GEMINI_ALT = "gemini-3.6-flash"   # E11 only

# Section 3.1. Every Apple Music city chart in the five countries; San Juan stays out.
GROUPS = {
    "us": ["Atlanta", "Austin", "Chicago", "Dallas", "Denver", "Detroit", "Honolulu", "Houston", "Los Angeles",
           "Miami", "Nashville", "New York City", "San Francisco", "Seattle", "Washington D.C."],
    "gb": ["Birmingham", "Glasgow", "Liverpool", "London", "Manchester"],
    "ca": ["Calgary", "Edmonton", "Ottawa", "Toronto", "Vancouver", "Winnipeg"],
    "za": ["Cape Town", "Durban", "Johannesburg"],
    "in": ["Bengaluru", "Delhi", "Mumbai"],
    "africa": ["Accra", "Johannesburg", "Lagos", "Nairobi"],   # secondary: crosses borders
}
WITHIN = ["us", "gb", "ca", "za", "in"]
COUNTRY = {"us": "United States", "gb": "United Kingdom", "ca": "Canada", "za": "South Africa", "in": "India"}
CITY_COUNTRY = {**{c: COUNTRY[g] for g in WITHIN for c in GROUPS[g]},
                "Accra": "Ghana", "Lagos": "Nigeria", "Nairobi": "Kenya", "Johannesburg": "South Africa"}
CITY_ISO = {**{c: g for g in WITHIN for c in GROUPS[g]}, "Accra": "gh", "Lagos": "ng", "Nairobi": "ke"}

# Chart name -> engine.PRESET key (3.2). Every other chart name equals its key.
NAME_MAP = {"New York City": "New York"}


def preset(city: str) -> str:
    return NAME_MAP.get(city, city)


def label(city: str) -> str:
    """What Gemini sees: 'City, Country'."""
    return f"{city}, {CITY_COUNTRY[city]}"


# Apple Music Top 100 by country, for the national tag (4.6) and the N4 panel.
TOP100 = {
    "us": ("us", "top-100-usa", "pl.606afcbb70264d2eb2b51d8dbcfa6a12"),
    "gb": ("gb", "top-100-uk", "pl.c2273b7e89b44121b3093f67228918e7"),
    "ca": ("ca", "top-100-canada", "pl.79bac9045a2540e0b195e983df8ba569"),
    "za": ("za", "top-100-south-africa", "pl.447bd05172824b89bd745628f7f54c18"),
    "in": ("in", "top-100-india", "pl.c0e98d2423e54c39b3df955c24df3cc5"),
    "ng": ("ng", "top-100-nigeria", "pl.2fc68f6d68004ae993dadfe99de83877"),
    "ke": ("ke", "top-100-kenya", "pl.0b36ea82865d4adeb9d1d62207aab172"),
    "gh": ("gh", "top-100-ghana", "pl.78f1974e882d4952b26ebfb8e017c933"),
}

SHAZAM_COUNTRY = {"us": "united-states", "gb": "united-kingdom", "ca": "canada", "za": "south-africa",
                  "in": "india", "ng": "nigeria", "gh": "ghana", "ke": "kenya"}

# N1. Approximate 2025 metro populations in millions, hand-entered for ordering only (the UN WUP 2018
# download moved). Balancing (4.5) holds any fixed per-pair predictor near 50% whatever these values are.
POPULATION = {
    "New York City": 19.5, "Los Angeles": 12.9, "Chicago": 9.3, "Dallas": 8.1, "Houston": 7.5, "Miami": 6.2,
    "Atlanta": 6.32, "Washington D.C.": 6.28, "San Francisco": 4.6, "Seattle": 4.1, "Detroit": 4.3,
    "Denver": 3.0, "Austin": 2.5, "Nashville": 2.1, "Honolulu": 1.0,
    "London": 9.8, "Manchester": 2.9, "Birmingham": 2.7, "Glasgow": 1.7, "Liverpool": 0.9,
    "Toronto": 6.7, "Vancouver": 2.7, "Calgary": 1.7, "Edmonton": 1.6, "Ottawa": 1.5, "Winnipeg": 0.9,
    "Johannesburg": 6.4, "Cape Town": 4.9, "Durban": 3.5,
    "Delhi": 34.7, "Mumbai": 22.1, "Bengaluru": 14.0,
    "Lagos": 16.5, "Nairobi": 5.5, "Accra": 2.7,
}

# 4.6 genre -> language, frozen. The same-language stratum compares it with the group's majority.
GENRE_LANG = {
    **{g: "en" for g in ["Hip-Hop/Rap", "R&B/Soul", "Pop", "Country", "Alternative", "Rock", "Dance", "Electronic",
                         "Singer/Songwriter", "Christian", "Christian & Gospel", "Gospel", "Soul", "Funk", "Metal",
                         "Indie Pop", "Jazz", "Blues", "Reggae", "House", "UK Hip Hop", "Grime", "Drill", "Rap",
                         "Contemporary R&B", "Hard Rock", "Pop/Rock", "Adult Alternative", "Dancehall",
                         "Americana", "Folk", "Indie Rock", "Soundtrack", "Holiday", "Easy Listening"]},
    **{g: "es" for g in ["Latin", "Música Mexicana", "Música mexicana", "Urbano latino", "Regional Mexicano",
                         "Pop Latino", "Latin Urban", "Latin Pop", "Reggaeton", "Salsa y Tropical",
                         "Música tropical", "Latin Rap", "Norteño", "Corridos", "Banda"]},
    **{g: "hi" for g in ["Bollywood", "Indian Pop", "Hindi", "Indian", "Devotional & Spiritual", "Ghazals",
                         "Indian Classical", "Sufi", "Indie Pop (Indian)"]},
    **{g: "pa" for g in ["Punjabi", "Punjabi Pop", "Haryanvi"]},
    **{g: g.lower()[:2] for g in ["Tamil", "Telugu", "Kannada", "Malayalam", "Marathi", "Bengali"]},
    **{g: "af" for g in ["Afrobeats", "Afro-Pop", "Afropop", "Amapiano", "Afro House", "African", "Kwaito", "Gqom",
                         "Maskandi", "Afro-fusion", "Afro-Beat", "Afro-Soul", "Highlife", "Bongo Flava", "Gengetone"]},
    "K-Pop": "ko", "J-Pop": "ja",
    # Apple genre names seen on the dev charts (review finding 32)
    "Sufi & Ghazals": "hi", "Regional Indian": "pa", "Modern Dancehall": "en", "South Africa": "af",
    "Worldwide": "other", "New Age": "other",
}
MAJORITY_LANG = {"us": "en", "gb": "en", "ca": "en", "za": "en", "in": "hi", "africa": "af"}

MEXICAN_STATES = ["Aguascalientes", "Baja California", "Baja California Sur", "Campeche", "Chiapas", "Chihuahua",
                  "Coahuila", "Colima", "Durango", "Guanajuato", "Guerrero", "Hidalgo", "Jalisco", "Estado de Mexico",
                  "Michoacan", "Morelos", "Nayarit", "Nuevo Leon", "Oaxaca", "Puebla", "Queretaro", "Quintana Roo",
                  "San Luis Potosi", "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz", "Yucatan",
                  "Zacatecas", "Ciudad de Mexico", "CDMX"]
REGIONS = ["Georgia", "Texas", "Illinois", "Colorado", "Michigan", "Hawaii", "Florida", "Tennessee", "California",
           "Washington", "New York", "District of Columbia", "West Midlands", "Scotland", "Greater Manchester",
           "Merseyside", "England", "Ontario", "British Columbia", "Alberta", "Manitoba", "Gauteng", "Western Cape",
           "KwaZulu-Natal", "KZN", "Maharashtra", "Karnataka", "NCR", "Lagos State", "Greater Accra", "Nairobi County"]
NICKNAMES = ["ATL", "NYC", "Bronx", "BX", "H-Town", "HTX", "DFW", "6ix", "YYC", "YVR", "YEG", "CPT", "JHB", "Jozi",
             "DBN", "Brum", "Bombay", "Bangalore", "Dilli"]
NATIONAL = ["America", "American", "USA", "Britain", "British", "UK", "England", "English", "Scotland", "Scottish",
            "Canada", "Canadian", "Africa", "African", "Mzansi", "India", "Indian", "Desi", "Punjabi", "Naija",
            "Mexico", "Mexican", "Boricua"]
DEMONYMS = ["Texan", "Atlantan", "Houstonian", "Angeleno", "New Yorker", "Mancunian", "Glaswegian", "Brummie",
            "Scouse", "Scouser", "Torontonian", "Capetonian", "Mumbaikar"]
CITY_WORDS = sorted({c for g in GROUPS.values() for c in g} | {"New York", "Washington", "Johannesburg"})
GIVEAWAYS = sorted(set(CITY_WORDS + REGIONS + MEXICAN_STATES + NICKNAMES + NATIONAL + DEMONYMS), key=str.lower)


def fold(s: str) -> str:
    """Lower case, accents removed, curly quotes straightened."""
    s = unicodedata.normalize("NFKD", html.unescape(s or "").replace("’", "'"))
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


_GIVE = [re.compile(r"(?<![\w])" + re.escape(fold(w)) + r"(?![\w])") for w in GIVEAWAYS]


def giveaway(name: str) -> str | None:
    f = fold(name)
    for w, rx in zip(GIVEAWAYS, _GIVE):
        if rx.search(f):
            return w
    return None


def sha_order(*parts) -> str:
    return hashlib.sha1("|".join([SALT, *map(str, parts)]).encode()).hexdigest()


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

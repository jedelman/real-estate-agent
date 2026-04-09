"""Property data and search.

Properties are stored as simple JSON dicts. Supports searching by criteria.
"""

from dataclasses import dataclass, field


@dataclass
class SearchCriteria:
    city: str = ""
    state: str = ""
    zip_code: str = ""
    price_min: float = 0
    price_max: float = 10_000_000
    bedrooms_min: int = 0
    bathrooms_min: float = 0
    sqft_min: int = 0
    sqft_max: int = 99_999
    keywords: list[str] = field(default_factory=list)
    limit: int = 10


# Sample listings
SAMPLE_LISTINGS = [
    {
        "external_id": "S001",
        "address": "4821 Oakwood Drive",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78731",
        "neighborhood": "Northwest Hills",
        "price": 875_000,
        "bedrooms": 4,
        "bathrooms": 3.0,
        "sqft": 2800,
        "lot_sqft": 9200,
        "year_built": 2018,
        "garage_spaces": 2,
        "stories": 2,
        "style": "modern",
        "hoa_monthly": 0,
        "features": ["open floor plan", "home office", "chef kitchen", "hardwood floors"],
        "description": "Stunning modern home in Northwest Hills with soaring ceilings and walls of glass. Gourmet kitchen with quartz counters and pro-grade appliances. Dedicated home office. Walking distance to top-rated elementary.",
        "status": "active",
        "days_on_market": 5,
        "listing_url": "https://example.com/S001",
        "photo_urls": [],
    },
    {
        "external_id": "S002",
        "address": "1203 Brentwood Circle",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78757",
        "neighborhood": "Brentwood",
        "price": 650_000,
        "bedrooms": 3,
        "bathrooms": 2.0,
        "sqft": 1950,
        "lot_sqft": 7500,
        "year_built": 1962,
        "garage_spaces": 1,
        "stories": 1,
        "style": "ranch",
        "hoa_monthly": 0,
        "features": ["renovated kitchen", "large backyard", "original hardwoods", "bike lanes nearby"],
        "description": "Charming fully renovated ranch in walkable Brentwood. Open living/dining, updated kitchen with butcher block counters. Large, private backyard perfect for entertaining. Seconds from local coffee shops and Brentwood Park.",
        "status": "active",
        "days_on_market": 12,
        "listing_url": "https://example.com/S002",
        "photo_urls": [],
    },
    {
        "external_id": "S003",
        "address": "902 Ridgecrest Boulevard",
        "city": "Cedar Park",
        "state": "TX",
        "zip_code": "78613",
        "neighborhood": "Buttercup Creek",
        "price": 520_000,
        "bedrooms": 4,
        "bathrooms": 3.5,
        "sqft": 3200,
        "lot_sqft": 8100,
        "year_built": 2022,
        "garage_spaces": 2,
        "stories": 2,
        "style": "craftsman",
        "hoa_monthly": 75,
        "features": ["pool", "game room", "home office", "energy efficient", "3-car garage"],
        "description": "Nearly new craftsman in the coveted Buttercup Creek community. Resort-style pool with covered patio. Upstairs game room. Dedicated main-floor home office. Leander ISD schools. Low HOA.",
        "status": "active",
        "days_on_market": 3,
        "listing_url": "https://example.com/S003",
        "photo_urls": [],
    },
    {
        "external_id": "S004",
        "address": "7715 Shoal Creek Blvd #4",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78757",
        "neighborhood": "North Loop",
        "price": 410_000,
        "bedrooms": 2,
        "bathrooms": 2.0,
        "sqft": 1200,
        "lot_sqft": None,
        "year_built": 2020,
        "garage_spaces": 1,
        "stories": 1,
        "style": "modern",
        "hoa_monthly": 320,
        "features": ["rooftop deck", "walkable", "gym", "dog park"],
        "description": "Sleek urban condo steps from the best of North Loop. Private rooftop deck with downtown skyline views. Community gym and dog park. High HOA covers water, trash, and exterior maintenance.",
        "status": "active",
        "days_on_market": 21,
        "listing_url": "https://example.com/S004",
        "photo_urls": [],
    },
    {
        "external_id": "S005",
        "address": "3340 Manchaca Road",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78704",
        "neighborhood": "78704 / South Austin",
        "price": 940_000,
        "bedrooms": 4,
        "bathrooms": 3.5,
        "sqft": 3050,
        "lot_sqft": 6800,
        "year_built": 2021,
        "garage_spaces": 2,
        "stories": 2,
        "style": "modern farmhouse",
        "hoa_monthly": 0,
        "features": ["home office", "open floor plan", "wine fridge", "natural light", "statement fireplace"],
        "description": "Gorgeous modern farmhouse in the heart of South Austin. Sun-drenched living spaces, 10-foot ceilings, designer finishes throughout. Statement fireplace in great room. Chef's kitchen with waterfall island and integrated appliances. No HOA.",
        "status": "active",
        "days_on_market": 8,
        "listing_url": "https://example.com/S005",
        "photo_urls": [],
    },
    {
        "external_id": "S006",
        "address": "18902 Estates Parkway",
        "city": "Lakeway",
        "state": "TX",
        "zip_code": "78738",
        "neighborhood": "Rough Hollow",
        "price": 1_350_000,
        "bedrooms": 5,
        "bathrooms": 4.5,
        "sqft": 4600,
        "lot_sqft": 18_500,
        "year_built": 2019,
        "garage_spaces": 3,
        "stories": 2,
        "style": "hill country transitional",
        "hoa_monthly": 210,
        "features": ["pool", "outdoor kitchen", "home theater", "wine cellar", "3-car garage", "lake views", "good schools"],
        "description": "Exceptional hill country estate in the prestigious Rough Hollow community. Pool and outdoor kitchen overlooking Lake Travis views. Home theater, wine cellar, and dedicated study. Lake Austin ISD. Community marina and yacht club access.",
        "status": "active",
        "days_on_market": 34,
        "listing_url": "https://example.com/S006",
        "photo_urls": [],
    },
    {
        "external_id": "S007",
        "address": "512 E 45th Street",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78751",
        "neighborhood": "Hyde Park",
        "price": 720_000,
        "bedrooms": 3,
        "bathrooms": 2.0,
        "sqft": 1750,
        "lot_sqft": 6200,
        "year_built": 1938,
        "garage_spaces": 0,
        "stories": 1,
        "style": "craftsman bungalow",
        "hoa_monthly": 0,
        "features": ["original character", "shaded yard", "walkable", "near UT", "front porch"],
        "description": "Beloved Hyde Park craftsman bungalow with all original character intact. Coved ceilings, picture rails, and period built-ins. Deeply shaded corner lot, classic front porch. Walk to UT, coffee shops, and Hyde Park Bar & Grill.",
        "status": "active",
        "days_on_market": 7,
        "listing_url": "https://example.com/S007",
        "photo_urls": [],
    },
    {
        "external_id": "S008",
        "address": "210 Pecan Ridge Lane",
        "city": "Round Rock",
        "state": "TX",
        "zip_code": "78664",
        "neighborhood": "Stone Canyon",
        "price": 475_000,
        "bedrooms": 4,
        "bathrooms": 3.0,
        "sqft": 2950,
        "lot_sqft": 9800,
        "year_built": 2015,
        "garage_spaces": 2,
        "stories": 2,
        "style": "traditional",
        "hoa_monthly": 45,
        "features": ["large yard", "good schools", "community pool", "cul-de-sac", "game room"],
        "description": "Spacious family home on a quiet cul-de-sac in Stone Canyon. Round Rock ISD – all highly rated campuses. Large fenced backyard, game room upstairs. Community pool, trails, and playground.",
        "status": "active",
        "days_on_market": 18,
        "listing_url": "https://example.com/S008",
        "photo_urls": [],
    },
    {
        "external_id": "S009",
        "address": "6001 Shepherd Mountain Cove",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78730",
        "neighborhood": "River Place",
        "price": 1_100_000,
        "bedrooms": 5,
        "bathrooms": 4.0,
        "sqft": 4100,
        "lot_sqft": 14_200,
        "year_built": 2005,
        "garage_spaces": 3,
        "stories": 2,
        "style": "traditional",
        "hoa_monthly": 150,
        "features": ["pool", "home office", "good schools", "greenbelt lot", "3-car garage"],
        "description": "Timeless traditional on a premium greenbelt lot in River Place. Five bedrooms, four full baths, and a private home office. Pool and spa overlooking the canyon. Leander ISD with highly rated River Place Elementary.",
        "status": "active",
        "days_on_market": 44,
        "listing_url": "https://example.com/S009",
        "photo_urls": [],
    },
    {
        "external_id": "S010",
        "address": "1408 Blanco Street",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78703",
        "neighborhood": "Old West Austin",
        "price": 1_650_000,
        "bedrooms": 4,
        "bathrooms": 3.5,
        "sqft": 3300,
        "lot_sqft": 7000,
        "year_built": 2023,
        "garage_spaces": 2,
        "stories": 2,
        "style": "modern",
        "hoa_monthly": 0,
        "features": ["new construction", "rooftop terrace", "home office", "natural light", "designer finishes"],
        "description": "Brand new modern masterpiece in prestigious Old West Austin. Rooftop terrace with panoramic views. Designer finishes, wide-plank oak floors, and bespoke cabinetry. Walk to Clarksville restaurants, Pease Park, and Whole Foods. No HOA.",
        "status": "active",
        "days_on_market": 2,
        "listing_url": "https://example.com/S010",
        "photo_urls": [],
    },
    {
        "external_id": "S011",
        "address": "3802 Speedway",
        "city": "Austin",
        "state": "TX",
        "zip_code": "78751",
        "neighborhood": "North Loop",
        "price": 585_000,
        "bedrooms": 3,
        "bathrooms": 2.0,
        "sqft": 1680,
        "lot_sqft": 5800,
        "year_built": 1948,
        "garage_spaces": 0,
        "stories": 1,
        "style": "cottage",
        "hoa_monthly": 0,
        "features": ["renovated", "garden", "vintage charm", "walkable"],
        "description": "Sweet renovated cottage one block from the North Loop strip. Vintage details meet modern updates—white shaker kitchen, original hardwood floors, clawfoot tub. Lush garden with raised beds. Walk everywhere.",
        "status": "active",
        "days_on_market": 9,
        "listing_url": "https://example.com/S011",
        "photo_urls": [],
    },
    {
        "external_id": "S012",
        "address": "24300 Briarcliff Drive",
        "city": "Spicewood",
        "state": "TX",
        "zip_code": "78669",
        "neighborhood": "Briarcliff",
        "price": 1_200_000,
        "bedrooms": 4,
        "bathrooms": 3.5,
        "sqft": 3800,
        "lot_sqft": 43_560,
        "year_built": 2016,
        "garage_spaces": 2,
        "stories": 1,
        "style": "hill country ranch",
        "hoa_monthly": 30,
        "features": ["1-acre lot", "pool", "lake access", "single story", "sunset views", "privacy"],
        "description": "Expansive hill country ranch on a full acre with private pool and lake access. All single story – perfect for easy living. Open plan great room with floor-to-ceiling windows framing sunset views. Community boat ramp on Lake Travis. Near Marble Falls wine country.",
        "status": "active",
        "days_on_market": 27,
        "listing_url": "https://example.com/S012",
        "photo_urls": [],
    },
]


def load_properties() -> list[dict]:
    """Load all properties."""
    return [p.copy() for p in SAMPLE_LISTINGS]


def property_to_dict(prop: dict | object) -> dict:
    """Convert a property (dict or ORM object) to a plain dict."""
    if isinstance(prop, dict):
        return prop.copy()
    # ORM object (shouldn't happen with new code)
    return {k: getattr(prop, k, None) for k in SAMPLE_LISTINGS[0].keys()}


def search_properties(properties: list[dict], criteria: SearchCriteria) -> list[dict]:
    """Search properties by criteria."""
    q = [p for p in properties if p.get("status") == "active"]

    if criteria.price_max:
        q = [p for p in q if p.get("price", 0) <= criteria.price_max]
    if criteria.price_min:
        q = [p for p in q if p.get("price", 0) >= criteria.price_min]
    if criteria.bedrooms_min:
        q = [p for p in q if p.get("bedrooms", 0) >= criteria.bedrooms_min]
    if criteria.bathrooms_min:
        q = [p for p in q if p.get("bathrooms", 0) >= criteria.bathrooms_min]
    if criteria.sqft_min:
        q = [p for p in q if p.get("sqft", 0) >= criteria.sqft_min]
    if criteria.sqft_max < 99_999:
        q = [p for p in q if p.get("sqft", 0) <= criteria.sqft_max]
    if criteria.city:
        q = [p for p in q if criteria.city.lower() in (p.get("city") or "").lower()]
    if criteria.zip_code:
        q = [p for p in q if p.get("zip_code") == criteria.zip_code]

    # Keyword filter
    if criteria.keywords:
        filtered = []
        for p in q:
            combined = " ".join(
                (p.get("features") or []) + [p.get("description") or ""]
            ).lower()
            if any(kw.lower() in combined for kw in criteria.keywords):
                filtered.append(p)
        q = filtered

    return q[: criteria.limit]

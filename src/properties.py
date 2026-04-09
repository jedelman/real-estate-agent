"""Property search layer.

Supports two backends:
  1. sample  – built-in realistic listings (works out of the box, no API key)
  2. zillow  – unofficial Zillow API via RapidAPI (set RAPIDAPI_KEY in .env)

Add new sources by implementing the `_fetch_*` pattern and wiring it into
`search_properties`.
"""

import os
import random
from dataclasses import dataclass, field
from typing import Any

import httpx

from .database import Property, Session


# ---------------------------------------------------------------------------
# Search criteria dataclass
# ---------------------------------------------------------------------------

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
    keywords: list[str] = field(default_factory=list)  # ["pool", "office", ...]
    limit: int = 10


# ---------------------------------------------------------------------------
# Sample data – enough to demo preference learning without any external API
# ---------------------------------------------------------------------------

SAMPLE_LISTINGS: list[dict[str, Any]] = [
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
        "description": (
            "Stunning modern home in Northwest Hills with soaring ceilings and walls of glass. "
            "Gourmet kitchen with quartz counters and pro-grade appliances. "
            "Dedicated home office. Walking distance to top-rated elementary."
        ),
        "days_on_market": 5,
        "listing_url": "https://example.com/S001",
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
        "description": (
            "Charming fully renovated ranch in walkable Brentwood. "
            "Open living/dining, updated kitchen with butcher block counters. "
            "Large, private backyard perfect for entertaining. "
            "Seconds from local coffee shops and Brentwood Park."
        ),
        "days_on_market": 12,
        "listing_url": "https://example.com/S002",
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
        "description": (
            "Nearly new craftsman in the coveted Buttercup Creek community. "
            "Resort-style pool with covered patio. Upstairs game room. "
            "Dedicated main-floor home office. "
            "Leander ISD schools. Low HOA."
        ),
        "days_on_market": 3,
        "listing_url": "https://example.com/S003",
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
        "description": (
            "Sleek urban condo steps from the best of North Loop. "
            "Private rooftop deck with downtown skyline views. "
            "Community gym and dog park. "
            "High HOA covers water, trash, and exterior maintenance."
        ),
        "days_on_market": 21,
        "listing_url": "https://example.com/S004",
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
        "description": (
            "Gorgeous modern farmhouse in the heart of South Austin. "
            "Sun-drenched living spaces, 10-foot ceilings, designer finishes throughout. "
            "Statement fireplace in great room. "
            "Chef's kitchen with waterfall island and integrated appliances. "
            "No HOA."
        ),
        "days_on_market": 8,
        "listing_url": "https://example.com/S005",
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
        "description": (
            "Exceptional hill country estate in the prestigious Rough Hollow community. "
            "Pool and outdoor kitchen overlooking Lake Travis views. "
            "Home theater, wine cellar, and dedicated study. "
            "Lake Austin ISD. Community marina and yacht club access."
        ),
        "days_on_market": 34,
        "listing_url": "https://example.com/S006",
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
        "description": (
            "Beloved Hyde Park craftsman bungalow with all original character intact. "
            "Coved ceilings, picture rails, and period built-ins. "
            "Deeply shaded corner lot, classic front porch. "
            "Walk to UT, coffee shops, and Hyde Park Bar & Grill."
        ),
        "days_on_market": 7,
        "listing_url": "https://example.com/S007",
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
        "description": (
            "Spacious family home on a quiet cul-de-sac in Stone Canyon. "
            "Round Rock ISD – all highly rated campuses. "
            "Large fenced backyard, game room upstairs. "
            "Community pool, trails, and playground."
        ),
        "days_on_market": 18,
        "listing_url": "https://example.com/S008",
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
        "description": (
            "Timeless traditional on a premium greenbelt lot in River Place. "
            "Five bedrooms, four full baths, and a private home office. "
            "Pool and spa overlooking the canyon. "
            "Leander ISD with highly rated River Place Elementary."
        ),
        "days_on_market": 44,
        "listing_url": "https://example.com/S009",
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
        "description": (
            "Brand new modern masterpiece in prestigious Old West Austin. "
            "Rooftop terrace with panoramic views. "
            "Designer finishes, wide-plank oak floors, and bespoke cabinetry. "
            "Walk to Clarksville restaurants, Pease Park, and Whole Foods. "
            "No HOA."
        ),
        "days_on_market": 2,
        "listing_url": "https://example.com/S010",
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
        "description": (
            "Sweet renovated cottage one block from the North Loop strip. "
            "Vintage details meet modern updates—white shaker kitchen, "
            "original hardwood floors, clawfoot tub. "
            "Lush garden with raised beds. Walk everywhere."
        ),
        "days_on_market": 9,
        "listing_url": "https://example.com/S011",
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
        "description": (
            "Expansive hill country ranch on a full acre with private pool and lake access. "
            "All single story – perfect for easy living. "
            "Open plan great room with floor-to-ceiling windows framing sunset views. "
            "Community boat ramp on Lake Travis. Near Marble Falls wine country."
        ),
        "days_on_market": 27,
        "listing_url": "https://example.com/S012",
    },
]


def _upsert_property(session: Session, data: dict) -> Property:
    """Insert or update a property record."""
    prop = session.query(Property).filter_by(external_id=data["external_id"]).first()
    if not prop:
        prop = Property()
        session.add(prop)
    for k, v in data.items():
        if hasattr(prop, k):
            setattr(prop, k, v)
    if prop.sqft and prop.price:
        prop.price_per_sqft = round(prop.price / prop.sqft, 2)
    session.commit()
    return prop


def seed_sample_data(session: Session):
    """Populate the DB with sample listings if empty."""
    if session.query(Property).count() == 0:
        for listing in SAMPLE_LISTINGS:
            _upsert_property(session, listing)


# ---------------------------------------------------------------------------
# Zillow via RapidAPI (optional)
# ---------------------------------------------------------------------------

async def _fetch_zillow(criteria: SearchCriteria) -> list[dict]:
    """Fetch from Zillow unofficial API via RapidAPI."""
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        return []

    location = criteria.zip_code or f"{criteria.city}, {criteria.state}"
    params = {
        "location": location,
        "home_type": "Houses",
        "minPrice": str(int(criteria.price_min)),
        "maxPrice": str(int(criteria.price_max)),
        "bedsMin": str(criteria.bedrooms_min),
        "bathsMin": str(criteria.bathrooms_min),
    }
    headers = {
        "x-rapidapi-host": "zillow-com1.p.rapidapi.com",
        "x-rapidapi-key": api_key,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://zillow-com1.p.rapidapi.com/propertyExtendedSearch",
            params=params,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()

    results = []
    for item in (data.get("props") or []):
        results.append({
            "external_id": f"Z{item.get('zpid', '')}",
            "source": "zillow",
            "address": item.get("address", ""),
            "city": item.get("city", ""),
            "state": item.get("state", ""),
            "zip_code": item.get("zipcode", ""),
            "price": float(item.get("price", 0)),
            "bedrooms": int(item.get("bedrooms", 0)),
            "bathrooms": float(item.get("bathrooms", 0)),
            "sqft": int(item.get("livingArea", 0)),
            "lot_sqft": int(item.get("lotAreaValue", 0) * 43560
                           if item.get("lotAreaUnit") == "acres" else item.get("lotAreaValue", 0)),
            "year_built": item.get("yearBuilt"),
            "status": item.get("listingStatus", "active").lower(),
            "days_on_market": item.get("daysOnZillow", 0),
            "listing_url": item.get("detailUrl", ""),
            "photo_urls": [item.get("imgSrc", "")] if item.get("imgSrc") else [],
            "features": [],
            "description": item.get("hdpData", {}).get("homeInfo", {}).get("description", ""),
        })
    return results


# ---------------------------------------------------------------------------
# Public search interface
# ---------------------------------------------------------------------------

def search_properties(session: Session, criteria: SearchCriteria) -> list[Property]:
    """Search the local DB. Seed sample data on first call."""
    seed_sample_data(session)

    q = session.query(Property).filter(Property.status == "active")

    if criteria.price_max:
        q = q.filter(Property.price <= criteria.price_max)
    if criteria.price_min:
        q = q.filter(Property.price >= criteria.price_min)
    if criteria.bedrooms_min:
        q = q.filter(Property.bedrooms >= criteria.bedrooms_min)
    if criteria.bathrooms_min:
        q = q.filter(Property.bathrooms >= criteria.bathrooms_min)
    if criteria.sqft_min:
        q = q.filter(Property.sqft >= criteria.sqft_min)
    if criteria.sqft_max < 99_999:
        q = q.filter(Property.sqft <= criteria.sqft_max)
    if criteria.city:
        q = q.filter(Property.city.ilike(f"%{criteria.city}%"))
    if criteria.zip_code:
        q = q.filter(Property.zip_code == criteria.zip_code)

    results = q.limit(criteria.limit * 3).all()

    # Keyword filter (features / description)
    if criteria.keywords:
        filtered = []
        for p in results:
            combined = " ".join((p.features or []) + [p.description or ""]).lower()
            if any(kw.lower() in combined for kw in criteria.keywords):
                filtered.append(p)
        results = filtered

    return results[: criteria.limit]


def property_to_dict(p: Property) -> dict:
    """Serialize a Property ORM object to a plain dict for the agent."""
    return {
        "id": p.id,
        "external_id": p.external_id,
        "address": p.address,
        "city": p.city,
        "state": p.state,
        "zip_code": p.zip_code,
        "neighborhood": p.neighborhood,
        "price": p.price,
        "price_per_sqft": p.price_per_sqft,
        "hoa_monthly": p.hoa_monthly,
        "bedrooms": p.bedrooms,
        "bathrooms": p.bathrooms,
        "sqft": p.sqft,
        "lot_sqft": p.lot_sqft,
        "year_built": p.year_built,
        "garage_spaces": p.garage_spaces,
        "stories": p.stories,
        "style": p.style,
        "features": p.features or [],
        "description": p.description,
        "days_on_market": p.days_on_market,
        "listing_url": p.listing_url,
        "status": p.status,
    }

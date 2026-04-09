"""Database models and session management."""

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, Integer, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_PATH = Path(__file__).parent.parent / "data" / "agent.db"
DB_PATH.parent.mkdir(exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Preferences(Base):
    """Structured preference model for the buyer. One row per customer."""

    __tablename__ = "preferences"

    id = Column(Integer, primary_key=True)
    customer_name = Column(String, default="Buyer")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Budget
    budget_max = Column(Float, nullable=True)
    budget_min = Column(Float, nullable=True)

    # Location
    target_cities = Column(JSON, default=list)       # ["Austin", "Round Rock"]
    target_zip_codes = Column(JSON, default=list)
    target_neighborhoods = Column(JSON, default=list)
    max_commute_minutes = Column(Integer, nullable=True)
    commute_destination = Column(String, nullable=True)

    # Physical requirements
    bedrooms_min = Column(Integer, nullable=True)
    bedrooms_max = Column(Integer, nullable=True)
    bathrooms_min = Column(Float, nullable=True)
    sqft_min = Column(Integer, nullable=True)
    sqft_max = Column(Integer, nullable=True)
    garage_spaces_min = Column(Integer, nullable=True)

    # Style & vibe
    preferred_styles = Column(JSON, default=list)    # ["modern", "craftsman", "ranch"]
    preferred_vibes = Column(JSON, default=list)     # ["cozy", "bright", "grand"]

    # Must-haves (boolean flags)
    needs_home_office = Column(Boolean, default=False)
    needs_pool = Column(Boolean, default=False)
    needs_large_yard = Column(Boolean, default=False)
    needs_good_schools = Column(Boolean, default=False)
    needs_walkability = Column(Boolean, default=False)
    needs_new_construction = Column(Boolean, default=False)
    needs_single_story = Column(Boolean, default=False)
    needs_open_floor_plan = Column(Boolean, default=False)

    # Deal-breakers (things to AVOID)
    deal_breakers = Column(JSON, default=list)       # ["HOA", "highway noise", "small kitchen"]

    # Flexible preferences (free-form key→value pairs)
    extra_preferences = Column(JSON, default=dict)

    # Notes the agent has collected
    raw_notes = Column(Text, default="")


class Property(Base):
    """A real estate listing, fetched from an external source."""

    __tablename__ = "properties"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, index=True)
    source = Column(String, default="sample")
    fetched_at = Column(DateTime, default=datetime.utcnow)

    # Location
    address = Column(String)
    city = Column(String)
    state = Column(String)
    zip_code = Column(String)
    neighborhood = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    # Financials
    price = Column(Float)
    price_per_sqft = Column(Float, nullable=True)
    hoa_monthly = Column(Float, nullable=True)
    property_tax_annual = Column(Float, nullable=True)

    # Physical
    bedrooms = Column(Integer)
    bathrooms = Column(Float)
    sqft = Column(Integer)
    lot_sqft = Column(Integer, nullable=True)
    year_built = Column(Integer, nullable=True)
    garage_spaces = Column(Integer, default=0)
    stories = Column(Integer, default=1)

    # Style
    style = Column(String, nullable=True)    # ranch, craftsman, modern, colonial, etc.
    description = Column(Text, nullable=True)

    # Features (list of strings)
    features = Column(JSON, default=list)    # ["pool", "home office", "open floor plan"]

    # Status
    status = Column(String, default="active")  # active, pending, sold
    days_on_market = Column(Integer, default=0)

    # URLs
    listing_url = Column(String, nullable=True)
    photo_urls = Column(JSON, default=list)


class SavedProperty(Base):
    """Properties the buyer has expressed interest in."""

    __tablename__ = "saved_properties"

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer)
    external_id = Column(String)
    saved_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="liked")   # liked, disliked, touring, offered
    notes = Column(Text, default="")
    agent_rationale = Column(Text, default="")  # Why the agent recommended it


class Conversation(Base):
    """Full conversation history."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    role = Column(String)        # user | assistant
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

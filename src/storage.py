"""Simple persistent storage for preferences and saved properties.

Supports two backends:
  - json: Local JSON files (default, good for development)
  - d1: Cloudflare D1 (requires D1_TOKEN and D1_DATABASE_ID env vars)
"""

import json
import os
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Optional

# ------------------------------------------------------------------ Storage interface

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass
class Preferences:
    """Buyer's preference profile."""
    customer_name: str = "Buyer"
    budget_max: Optional[float] = None
    budget_min: Optional[float] = None
    target_cities: list[str] = field(default_factory=list)
    target_neighborhoods: list[str] = field(default_factory=list)
    bedrooms_min: Optional[int] = None
    bedrooms_max: Optional[int] = None
    bathrooms_min: Optional[float] = None
    sqft_min: Optional[int] = None
    sqft_max: Optional[int] = None
    garage_spaces_min: Optional[int] = None
    preferred_styles: list[str] = field(default_factory=list)
    preferred_vibes: list[str] = field(default_factory=list)
    needs_home_office: bool = False
    needs_pool: bool = False
    needs_large_yard: bool = False
    needs_good_schools: bool = False
    needs_walkability: bool = False
    needs_new_construction: bool = False
    needs_single_story: bool = False
    needs_open_floor_plan: bool = False
    deal_breakers: list[str] = field(default_factory=list)
    extra_preferences: dict = field(default_factory=dict)
    max_commute_minutes: Optional[int] = None
    commute_destination: Optional[str] = None
    raw_notes: str = ""
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SavedProperty:
    """A bookmarked property."""
    external_id: str
    status: str = "liked"  # liked, disliked, touring, offered
    notes: str = ""
    agent_rationale: str = ""
    saved_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class PreferencesStore:
    """Persistent storage for preferences and saved properties."""

    def __init__(self, backend: str = "json"):
        self.backend = backend
        if backend == "json":
            self.prefs_file = DATA_DIR / "preferences.json"
            self.saved_file = DATA_DIR / "saved.json"

    def get_preferences(self, customer_name: str = "Buyer") -> Preferences:
        if self.backend == "json":
            if self.prefs_file.exists():
                data = json.loads(self.prefs_file.read_text())
                return Preferences(**data)
            return Preferences(customer_name=customer_name)
        return Preferences(customer_name=customer_name)

    def save_preferences(self, prefs: Preferences) -> None:
        prefs.updated_at = datetime.utcnow().isoformat()
        if self.backend == "json":
            self.prefs_file.write_text(json.dumps(prefs.to_dict(), indent=2))

    def update_preferences(self, customer_name: str, updates: dict) -> Preferences:
        prefs = self.get_preferences(customer_name)
        # Merge preferences
        for key, value in updates.items():
            if not hasattr(prefs, key):
                continue
            if key == "raw_notes" and value:
                existing = prefs.raw_notes or ""
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                prefs.raw_notes = f"{existing}\n[{timestamp}] {value}".strip()
            elif key == "extra_preferences" and isinstance(value, dict):
                existing = prefs.extra_preferences or {}
                existing.update(value)
                prefs.extra_preferences = existing
            elif key in {
                "target_cities", "target_neighborhoods", "preferred_styles",
                "preferred_vibes", "deal_breakers"
            } and isinstance(value, list):
                # Merge lists (dedupe)
                existing_list = getattr(prefs, key) or []
                merged = list(dict.fromkeys(existing_list + value))
                setattr(prefs, key, merged)
            else:
                setattr(prefs, key, value)
        self.save_preferences(prefs)
        return prefs

    def get_saved_properties(self) -> list[SavedProperty]:
        if self.backend == "json":
            if self.saved_file.exists():
                data = json.loads(self.saved_file.read_text())
                return [SavedProperty(**item) for item in data]
            return []
        return []

    def save_property(self, prop: SavedProperty) -> None:
        if self.backend == "json":
            saved = self.get_saved_properties()
            # Update or add
            for i, s in enumerate(saved):
                if s.external_id == prop.external_id:
                    saved[i] = prop
                    break
            else:
                saved.append(prop)
            self.saved_file.write_text(
                json.dumps([asdict(s) for s in saved], indent=2)
            )

    def clear(self, keep_preferences: bool = False) -> None:
        if self.backend == "json":
            if not keep_preferences:
                self.prefs_file.unlink(missing_ok=True)
            self.saved_file.unlink(missing_ok=True)

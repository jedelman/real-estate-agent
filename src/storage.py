"""Persistent storage: config, preferences, saved properties.

Single source of truth. One ConfigStore and one PreferencesStore should be
created per process and shared — do not instantiate multiples.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# App config  (agent identity + Managed Agent IDs)
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    agent_name: str = "Cassie"
    customer_name: str = "Sarah"
    setup_complete: bool = False
    # Managed Agent infrastructure IDs (created once, reused)
    managed_agent_id: Optional[str] = None
    environment_id: Optional[str] = None
    # Active session (one per conversation; reset on "Start Over")
    session_id: Optional[str] = None


class ConfigStore:
    def __init__(self):
        self._path = DATA_DIR / "config.json"

    def load(self) -> AppConfig:
        if self._path.exists():
            return AppConfig(**json.loads(self._path.read_text()))
        return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        self._path.write_text(json.dumps(asdict(cfg), indent=2))

    def is_configured(self) -> bool:
        return self.load().setup_complete

    def update(self, **kwargs) -> AppConfig:
        cfg = self.load()
        for k, v in kwargs.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        self.save(cfg)
        return cfg


# ---------------------------------------------------------------------------
# Buyer preferences
# ---------------------------------------------------------------------------

@dataclass
class Preferences:
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

    def summary(self) -> str:
        """Human-readable summary for injecting into agent context."""
        lines = []
        if self.budget_min or self.budget_max:
            lo = f"${self.budget_min:,.0f}" if self.budget_min else "any"
            hi = f"${self.budget_max:,.0f}" if self.budget_max else "any"
            lines.append(f"Budget: {lo} – {hi}")
        if self.target_cities:
            lines.append(f"Preferred cities: {', '.join(self.target_cities)}")
        if self.target_neighborhoods:
            lines.append(f"Preferred neighborhoods: {', '.join(self.target_neighborhoods)}")
        if self.bedrooms_min:
            lines.append(f"Bedrooms: {self.bedrooms_min}+")
        if self.bathrooms_min:
            lines.append(f"Bathrooms: {self.bathrooms_min}+")
        if self.sqft_min:
            lines.append(f"Min sqft: {self.sqft_min:,}")
        if self.preferred_styles:
            lines.append(f"Style: {', '.join(self.preferred_styles)}")
        if self.preferred_vibes:
            lines.append(f"Vibes: {', '.join(self.preferred_vibes)}")
        must_haves = [
            label for flag, label in [
                (self.needs_home_office, "home office"),
                (self.needs_pool, "pool"),
                (self.needs_good_schools, "good schools"),
                (self.needs_single_story, "single story"),
                (self.needs_open_floor_plan, "open floor plan"),
                (self.needs_walkability, "walkable neighborhood"),
                (self.needs_large_yard, "large yard"),
                (self.needs_new_construction, "new construction"),
            ] if flag
        ]
        if must_haves:
            lines.append(f"Must-haves: {', '.join(must_haves)}")
        if self.deal_breakers:
            lines.append(f"Deal-breakers: {', '.join(self.deal_breakers)}")
        if self.commute_destination:
            minutes = f" (under {self.max_commute_minutes} min)" if self.max_commute_minutes else ""
            lines.append(f"Commute to: {self.commute_destination}{minutes}")
        if self.extra_preferences:
            for k, v in self.extra_preferences.items():
                lines.append(f"{k}: {v}")
        return "\n".join(lines) if lines else "No preferences recorded yet."


class PreferencesStore:
    def __init__(self):
        self._path = DATA_DIR / "preferences.json"
        self._saved_path = DATA_DIR / "saved.json"

    def get(self, customer_name: str = "Buyer") -> Preferences:
        if self._path.exists():
            data = json.loads(self._path.read_text())
            return Preferences(**data)
        return Preferences(customer_name=customer_name)

    def save(self, prefs: Preferences) -> None:
        prefs.updated_at = datetime.utcnow().isoformat()
        self._path.write_text(json.dumps(prefs.to_dict(), indent=2))

    def apply_updates(self, customer_name: str, updates: dict) -> Preferences:
        """Merge validated updates into the preference store."""
        prefs = self.get(customer_name)
        _LIST_FIELDS = {
            "target_cities", "target_neighborhoods", "preferred_styles",
            "preferred_vibes", "deal_breakers",
        }
        for key, value in updates.items():
            if not hasattr(prefs, key) or value is None:
                continue
            if key == "raw_notes" and isinstance(value, str):
                ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                existing = prefs.raw_notes or ""
                prefs.raw_notes = f"{existing}\n[{ts}] {value}".strip()
            elif key == "extra_preferences" and isinstance(value, dict):
                merged = prefs.extra_preferences or {}
                merged.update(value)
                prefs.extra_preferences = merged
            elif key in _LIST_FIELDS and isinstance(value, list):
                existing = getattr(prefs, key) or []
                setattr(prefs, key, list(dict.fromkeys(existing + value)))
            else:
                setattr(prefs, key, value)
        self.save(prefs)
        return prefs

    # --- Saved properties ---

    @dataclass
    class SavedEntry:
        external_id: str
        address: str = ""
        price: float = 0
        status: str = "liked"
        notes: str = ""
        agent_rationale: str = ""
        saved_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def get_saved(self) -> list:
        if self._saved_path.exists():
            data = json.loads(self._saved_path.read_text())
            return [PreferencesStore.SavedEntry(**item) for item in data]
        return []

    def save_property(self, entry) -> None:
        saved = self.get_saved()
        for i, s in enumerate(saved):
            if s.external_id == entry.external_id:
                saved[i] = entry
                break
        else:
            saved.append(entry)
        self._saved_path.write_text(
            json.dumps([asdict(s) for s in saved], indent=2)
        )

    def clear(self, keep_preferences: bool = False) -> None:
        self._saved_path.unlink(missing_ok=True)
        if not keep_preferences:
            self._path.unlink(missing_ok=True)

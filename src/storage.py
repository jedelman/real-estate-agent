"""Persistent storage: config, preferences, saved properties.

Supports two backends selected by environment variable:
  STORAGE_BACKEND=json  (default)  — local JSON files, no infra needed
  STORAGE_BACKEND=d1               — Cloudflare D1 via REST API
                                     requires CF_API_TOKEN, CF_ACCOUNT_ID,
                                     CF_D1_DATABASE_ID

Single source of truth. Create one ConfigStore and one PreferencesStore
per process and share them (see @st.cache_resource in app.py).
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# D1 REST client
# ---------------------------------------------------------------------------

class _D1Client:
    """Thin wrapper around the Cloudflare D1 HTTP API."""

    def __init__(self):
        account_id  = os.environ["CF_ACCOUNT_ID"]
        database_id = os.environ["CF_D1_DATABASE_ID"]
        self._url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{account_id}/d1/database/{database_id}/query"
        )
        self._token = os.environ["CF_API_TOKEN"]

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        """Run a SQL statement and return result rows as a list of dicts."""
        import urllib.request

        payload = json.dumps({"sql": sql, "params": params or []}).encode()
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())

        if not body.get("success"):
            errors = body.get("errors", [])
            raise RuntimeError(f"D1 error: {errors}")

        results = body.get("result", [{}])
        return results[0].get("results", [])


# ---------------------------------------------------------------------------
# App config  (agent identity + Managed Agent IDs)
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    agent_name: str = "Cassie"
    customer_name: str = "Sarah"
    setup_complete: bool = False
    managed_agent_id: Optional[str] = None
    environment_id: Optional[str] = None
    session_id: Optional[str] = None


def _backend() -> str:
    return os.getenv("STORAGE_BACKEND", "json").lower()


class ConfigStore:
    """Stores and retrieves AppConfig. Backend-agnostic."""

    def __init__(self):
        self._path = DATA_DIR / "config.json"

    # -- JSON backend --

    def _json_load(self) -> AppConfig:
        if self._path.exists():
            return AppConfig(**json.loads(self._path.read_text()))
        return AppConfig()

    def _json_save(self, cfg: AppConfig) -> None:
        self._path.write_text(json.dumps(asdict(cfg), indent=2))

    # -- D1 backend --

    def _d1_load(self) -> AppConfig:
        rows = _D1Client().execute("SELECT key, value FROM config")
        data = {r["key"]: r["value"] for r in rows}
        kwargs = {}
        for f in AppConfig.__dataclass_fields__:
            if f in data:
                raw = data[f]
                # Coerce booleans stored as strings
                if raw in ("true", "True"):
                    kwargs[f] = True
                elif raw in ("false", "False"):
                    kwargs[f] = False
                elif raw == "null":
                    kwargs[f] = None
                else:
                    kwargs[f] = raw
        return AppConfig(**kwargs)

    def _d1_save(self, cfg: AppConfig) -> None:
        d1 = _D1Client()
        for key, value in asdict(cfg).items():
            d1.execute(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                [key, json.dumps(value) if not isinstance(value, str) else value],
            )

    # -- Public API --

    def load(self) -> AppConfig:
        if _backend() == "d1":
            return self._d1_load()
        return self._json_load()

    def save(self, cfg: AppConfig) -> None:
        if _backend() == "d1":
            self._d1_save(cfg)
        else:
            self._json_save(cfg)

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
        for k, v in (self.extra_preferences or {}).items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines) if lines else "No preferences recorded yet."


class PreferencesStore:
    """Stores buyer preferences and saved/reacted-to properties."""

    def __init__(self):
        self._prefs_path = DATA_DIR / "preferences.json"
        self._saved_path = DATA_DIR / "saved.json"

    # -- JSON backend --

    def _json_get(self, customer_name: str) -> Preferences:
        if self._prefs_path.exists():
            data = json.loads(self._prefs_path.read_text())
            return Preferences(**data)
        return Preferences(customer_name=customer_name)

    def _json_save_prefs(self, prefs: Preferences) -> None:
        self._prefs_path.write_text(json.dumps(prefs.to_dict(), indent=2))

    def _json_get_saved(self) -> list:
        if self._saved_path.exists():
            return [
                PreferencesStore.SavedEntry(**item)
                for item in json.loads(self._saved_path.read_text())
            ]
        return []

    def _json_save_entry(self, entry) -> None:
        saved = self._json_get_saved()
        for i, s in enumerate(saved):
            if s.external_id == entry.external_id:
                saved[i] = entry
                break
        else:
            saved.append(entry)
        self._saved_path.write_text(json.dumps([asdict(s) for s in saved], indent=2))

    # -- D1 backend --

    def _d1_get(self, customer_name: str) -> Preferences:
        rows = _D1Client().execute(
            "SELECT data FROM preferences WHERE customer_name = ?", [customer_name]
        )
        if rows:
            return Preferences(**json.loads(rows[0]["data"]))
        return Preferences(customer_name=customer_name)

    def _d1_save_prefs(self, prefs: Preferences) -> None:
        _D1Client().execute(
            "INSERT INTO preferences (customer_name, data, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(customer_name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            [prefs.customer_name, json.dumps(prefs.to_dict())],
        )

    def _d1_get_saved(self) -> list:
        rows = _D1Client().execute(
            "SELECT * FROM saved_properties ORDER BY saved_at DESC"
        )
        return [PreferencesStore.SavedEntry(**r) for r in rows]

    def _d1_save_entry(self, entry) -> None:
        _D1Client().execute(
            "INSERT INTO saved_properties "
            "(external_id, address, price, status, notes, agent_rationale) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(external_id) DO UPDATE SET "
            "status=excluded.status, notes=excluded.notes, "
            "agent_rationale=excluded.agent_rationale",
            [
                entry.external_id, entry.address, entry.price,
                entry.status, entry.notes, entry.agent_rationale,
            ],
        )

    # -- Public API --

    @dataclass
    class SavedEntry:
        external_id: str
        address: str = ""
        price: float = 0
        status: str = "liked"
        notes: str = ""
        agent_rationale: str = ""
        saved_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def get(self, customer_name: str = "Buyer") -> Preferences:
        if _backend() == "d1":
            return self._d1_get(customer_name)
        return self._json_get(customer_name)

    def save(self, prefs: Preferences) -> None:
        prefs.updated_at = datetime.utcnow().isoformat()
        if _backend() == "d1":
            self._d1_save_prefs(prefs)
        else:
            self._json_save_prefs(prefs)

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
                prefs.raw_notes = f"{prefs.raw_notes or ''}\n[{ts}] {value}".strip()
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

    def get_saved(self) -> list:
        if _backend() == "d1":
            return self._d1_get_saved()
        return self._json_get_saved()

    def save_property(self, entry) -> None:
        if _backend() == "d1":
            self._d1_save_entry(entry)
        else:
            self._json_save_entry(entry)

    def save_messages(self, messages: list) -> None:
        if _backend() == "d1":
            _D1Client().execute(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                ["conversation_messages", json.dumps(messages)],
            )
        else:
            (DATA_DIR / "messages.json").write_text(json.dumps(messages, indent=2))

    def load_messages(self) -> list:
        if _backend() == "d1":
            rows = _D1Client().execute(
                "SELECT value FROM config WHERE key = 'conversation_messages'"
            )
            return json.loads(rows[0]["value"]) if rows else []
        path = DATA_DIR / "messages.json"
        return json.loads(path.read_text()) if path.exists() else []

    def clear(self, keep_preferences: bool = False) -> None:
        if _backend() == "json":
            self._saved_path.unlink(missing_ok=True)
            (DATA_DIR / "messages.json").unlink(missing_ok=True)
            if not keep_preferences:
                self._prefs_path.unlink(missing_ok=True)
        else:
            d1 = _D1Client()
            d1.execute("DELETE FROM saved_properties")
            d1.execute("DELETE FROM config WHERE key = 'conversation_messages'")
            if not keep_preferences:
                d1.execute("DELETE FROM preferences")

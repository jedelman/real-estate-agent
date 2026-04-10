"""Preference extractor — CHECKS pattern applied to preference learning.

After each agent response we run a fast, cheap haiku call to extract
structured preference signals from the conversation. Signals are validated
against the Preferences schema before being applied to the store.

This decouples preference learning from the main agent, giving us:
  - A clear validation boundary (CHECKS)
  - Preferences that accumulate from ANY conversation style
  - No hallucinated preferences (we validate types before storing)
"""

import json
import os
from typing import Any

import anthropic

_SCHEMA = {
    "budget_max": "number",
    "budget_min": "number",
    "target_cities": "list[str]",
    "target_neighborhoods": "list[str]",
    "bedrooms_min": "int",
    "bedrooms_max": "int",
    "bathrooms_min": "number",
    "sqft_min": "int",
    "sqft_max": "int",
    "garage_spaces_min": "int",
    "preferred_styles": "list[str]",
    "preferred_vibes": "list[str]",
    "needs_home_office": "bool",
    "needs_pool": "bool",
    "needs_large_yard": "bool",
    "needs_good_schools": "bool",
    "needs_walkability": "bool",
    "needs_new_construction": "bool",
    "needs_single_story": "bool",
    "needs_open_floor_plan": "bool",
    "deal_breakers": "list[str]",
    "max_commute_minutes": "int",
    "commute_destination": "str",
    "raw_notes": "str",
    "extra_preferences": "dict",
}

_SYSTEM = """\
You extract home-buying preference signals from a real estate conversation.

Given a conversation between a buyer and an agent, return a JSON object containing
ONLY the fields that were explicitly or strongly implicitly mentioned. Omit all
other fields entirely. Return {} if nothing new was said.

The valid fields and types are:
""" + "\n".join(f"  {k}: {v}" for k, v in _SCHEMA.items()) + """

Rules:
- Only include a field if it was clearly stated or strongly implied.
- Indirect signals count: "we both work from home" → needs_home_office: true
- "I hate HOA drama" → deal_breakers: ["HOA"]
- Combine vibes from natural language: "bright and cozy feel" → preferred_vibes: ["bright", "cozy"]
- For list fields, return only NEW values (they will be merged, not replaced).
- raw_notes: use for any preference that doesn't fit a structured field.
- Never invent or assume preferences not grounded in the conversation.
- Return valid JSON only. No explanation.
"""


def _validate(raw: dict) -> dict:
    """Type-check extracted values against the schema. Drop invalid ones."""
    validated = {}
    for key, value in raw.items():
        if key not in _SCHEMA:
            continue
        expected = _SCHEMA[key]
        if value is None:
            continue
        try:
            if expected == "number":
                validated[key] = float(value)
            elif expected == "int":
                validated[key] = int(value)
            elif expected == "bool":
                if isinstance(value, bool):
                    validated[key] = value
                elif isinstance(value, str):
                    validated[key] = value.lower() in ("true", "yes", "1")
            elif expected == "str":
                validated[key] = str(value)
            elif expected == "list[str]":
                if isinstance(value, list):
                    validated[key] = [str(v) for v in value if v]
            elif expected == "dict":
                if isinstance(value, dict):
                    validated[key] = value
        except (TypeError, ValueError):
            continue
    return validated


def extract_and_apply(
    conversation: list[dict],
    store,
    customer_name: str,
) -> dict:
    """Run preference extraction and apply validated updates to the store.

    Args:
        conversation: List of {"role": ..., "content": ...} dicts.
        store: A PreferencesStore instance.
        customer_name: Used to look up the right preferences record.

    Returns:
        The validated preference updates that were applied (empty dict if none).
    """
    if not conversation:
        return {}

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Only send the last few turns to keep latency low
    recent = conversation[-6:]

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM,
            messages=recent,
        )
        raw_text = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        raw = json.loads(raw_text)
    except Exception:
        return {}

    if not raw:
        return {}

    validated = _validate(raw)
    if validated:
        store.apply_updates(customer_name, validated)

    return validated

"""Claude-powered real estate agent.

The agent uses tool_use to interact with the property database and preference
model. Every conversation turn is persisted so preferences accumulate over time.

Tools available to the agent:
  - update_preferences      – store structured preference data
  - get_preferences         – read current preference profile
  - search_properties       – find matching listings
  - get_property_details    – full detail on a single listing
  - save_property           – bookmark a listing with a status + notes
  - get_saved_properties    – review bookmarked listings
  - proactive_recommendations – score ALL active listings vs preferences
"""

import json
import os
from datetime import datetime
from typing import Any

import anthropic

from .properties import SearchCriteria, load_properties, property_to_dict, search_properties
from .storage import Preferences, PreferencesStore, SavedProperty

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "update_preferences",
        "description": (
            "Update the buyer's preference profile. Call this whenever the user reveals "
            "anything about what they want or don't want in a home. Be liberal about capturing "
            "preferences – indirect signals count (e.g. 'we work from home' → needs_home_office=true). "
            "Only pass fields you want to change; omit fields you want to leave unchanged."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "budget_max": {"type": "number", "description": "Maximum budget in dollars"},
                "budget_min": {"type": "number", "description": "Minimum budget in dollars"},
                "target_cities": {"type": "array", "items": {"type": "string"}, "description": "Preferred cities"},
                "target_neighborhoods": {"type": "array", "items": {"type": "string"}},
                "bedrooms_min": {"type": "integer"},
                "bedrooms_max": {"type": "integer"},
                "bathrooms_min": {"type": "number"},
                "sqft_min": {"type": "integer"},
                "sqft_max": {"type": "integer"},
                "garage_spaces_min": {"type": "integer"},
                "preferred_styles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "e.g. modern, craftsman, ranch, modern farmhouse, craftsman bungalow",
                },
                "preferred_vibes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "e.g. cozy, bright, grand, private, walkable",
                },
                "needs_home_office": {"type": "boolean"},
                "needs_pool": {"type": "boolean"},
                "needs_large_yard": {"type": "boolean"},
                "needs_good_schools": {"type": "boolean"},
                "needs_walkability": {"type": "boolean"},
                "needs_new_construction": {"type": "boolean"},
                "needs_single_story": {"type": "boolean"},
                "needs_open_floor_plan": {"type": "boolean"},
                "deal_breakers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Things to actively avoid, e.g. HOA, highway noise, small kitchen",
                },
                "extra_preferences": {
                    "type": "object",
                    "description": "Free-form key/value pairs for anything not covered above",
                },
                "raw_notes": {
                    "type": "string",
                    "description": "Append a note about what the buyer said (don't overwrite existing notes)",
                },
                "max_commute_minutes": {"type": "integer"},
                "commute_destination": {"type": "string"},
            },
        },
    },
    {
        "name": "get_preferences",
        "description": "Retrieve the buyer's current full preference profile.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_properties",
        "description": (
            "Search for listings that match given criteria. "
            "Use the buyer's known preferences to build the criteria. "
            "Returns up to `limit` matching properties."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "state": {"type": "string"},
                "zip_code": {"type": "string"},
                "price_min": {"type": "number"},
                "price_max": {"type": "number"},
                "bedrooms_min": {"type": "integer"},
                "bathrooms_min": {"type": "number"},
                "sqft_min": {"type": "integer"},
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Feature keywords to filter on, e.g. ['pool', 'home office']",
                },
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "get_property_details",
        "description": "Get full details about a specific property by its external_id (e.g. 'S001').",
        "input_schema": {
            "type": "object",
            "properties": {
                "external_id": {"type": "string"},
            },
            "required": ["external_id"],
        },
    },
    {
        "name": "save_property",
        "description": (
            "Save or update a property in the buyer's shortlist. "
            "Status options: liked, disliked, touring, offered. "
            "Include agent_rationale explaining why this property matches (or doesn't) the preferences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "external_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["liked", "disliked", "touring", "offered"],
                },
                "notes": {"type": "string", "description": "Any notes from the conversation"},
                "agent_rationale": {
                    "type": "string",
                    "description": "Why this property does or doesn't match the buyer's preferences",
                },
            },
            "required": ["external_id", "status"],
        },
    },
    {
        "name": "get_saved_properties",
        "description": "Get all properties the buyer has saved, with their statuses.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "proactive_recommendations",
        "description": (
            "Score all active listings against the buyer's current preference profile and return "
            "the top matches with a personalized explanation for each. "
            "Call this to proactively surface great matches, especially after learning new preferences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "top_n": {
                    "type": "integer",
                    "default": 3,
                    "description": "How many top recommendations to return",
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------

_store = PreferencesStore(backend="json")


def _preferences_to_dict(prefs: Preferences) -> dict:
    return {
        "customer_name": prefs.customer_name,
        "budget_min": prefs.budget_min,
        "budget_max": prefs.budget_max,
        "target_cities": prefs.target_cities or [],
        "target_neighborhoods": prefs.target_neighborhoods or [],
        "bedrooms_min": prefs.bedrooms_min,
        "bedrooms_max": prefs.bedrooms_max,
        "bathrooms_min": prefs.bathrooms_min,
        "sqft_min": prefs.sqft_min,
        "sqft_max": prefs.sqft_max,
        "garage_spaces_min": prefs.garage_spaces_min,
        "preferred_styles": prefs.preferred_styles or [],
        "preferred_vibes": prefs.preferred_vibes or [],
        "needs_home_office": prefs.needs_home_office,
        "needs_pool": prefs.needs_pool,
        "needs_large_yard": prefs.needs_large_yard,
        "needs_good_schools": prefs.needs_good_schools,
        "needs_walkability": prefs.needs_walkability,
        "needs_new_construction": prefs.needs_new_construction,
        "needs_single_story": prefs.needs_single_story,
        "needs_open_floor_plan": prefs.needs_open_floor_plan,
        "deal_breakers": prefs.deal_breakers or [],
        "extra_preferences": prefs.extra_preferences or {},
        "max_commute_minutes": prefs.max_commute_minutes,
        "commute_destination": prefs.commute_destination,
        "raw_notes": prefs.raw_notes,
        "updated_at": prefs.updated_at,
    }


def _score_property_dict(prop: dict, prefs: Preferences) -> tuple[int, list[str]]:
    """Score a property dict against preferences."""
    score = 50
    reasons = []

    # Budget
    if prefs.budget_max and prop.get("price", 0) > prefs.budget_max:
        score -= 30
    elif prefs.budget_max and prop.get("price", 0) <= prefs.budget_max * 0.9:
        score += 10
        reasons.append(f"well within budget at ${prop.get('price', 0):,.0f}")

    # Bedrooms
    if prefs.bedrooms_min and prop.get("bedrooms", 0) >= prefs.bedrooms_min:
        score += 8
        reasons.append(f"{prop.get('bedrooms')} beds meets your minimum")
    elif prefs.bedrooms_min and prop.get("bedrooms", 0) < prefs.bedrooms_min:
        score -= 15

    # Style
    features_lower = [f.lower() for f in (prop.get("features") or [])]
    desc_lower = (prop.get("description") or "").lower()
    style_lower = (prop.get("style") or "").lower()

    if prefs.preferred_styles:
        for s in prefs.preferred_styles:
            if s.lower() in style_lower:
                score += 12
                reasons.append(f"matches your love of {s} style")
                break

    # Must-haves
    if prefs.needs_home_office:
        if "home office" in features_lower or "office" in desc_lower:
            score += 12
            reasons.append("has a dedicated home office")
        else:
            score -= 10

    if prefs.needs_pool:
        if "pool" in features_lower:
            score += 12
            reasons.append("has a pool")
        else:
            score -= 8

    if prefs.needs_good_schools:
        if "good schools" in features_lower or "isd" in desc_lower or "elementary" in desc_lower:
            score += 12
            reasons.append("located in a top-rated school district")
        else:
            score -= 5

    if prefs.needs_single_story:
        if prop.get("stories") == 1:
            score += 10
            reasons.append("single story layout")
        else:
            score -= 12

    if prefs.needs_open_floor_plan:
        if "open floor plan" in features_lower or "open plan" in desc_lower:
            score += 8
            reasons.append("open floor plan")

    if prefs.needs_walkability:
        if "walkable" in features_lower or "walk" in desc_lower:
            score += 8
            reasons.append("highly walkable neighborhood")

    if prefs.needs_large_yard:
        lot_sqft = prop.get("lot_sqft")
        if lot_sqft and lot_sqft >= 8000:
            score += 8
            reasons.append(f"large {lot_sqft:,} sq ft lot")
        else:
            score -= 5

    if prefs.needs_new_construction:
        year_built = prop.get("year_built")
        if year_built and year_built >= 2020:
            score += 10
            reasons.append(f"new construction ({year_built})")
        else:
            score -= 5

    # Deal breakers
    for db in (prefs.deal_breakers or []):
        db_lower = db.lower()
        if db_lower == "hoa" and prop.get("hoa_monthly", 0) and prop.get("hoa_monthly", 0) > 0:
            score -= 25
        elif db_lower in features_lower or db_lower in desc_lower:
            score -= 20

    # Sqft
    sqft = prop.get("sqft", 0)
    if prefs.sqft_min and sqft < prefs.sqft_min:
        score -= 12
    elif prefs.sqft_min and sqft >= prefs.sqft_min * 1.1:
        score += 5
        reasons.append(f"generously sized at {sqft:,} sqft")

    # Neighborhoods
    if prefs.target_neighborhoods:
        for n in prefs.target_neighborhoods:
            if n.lower() in (prop.get("neighborhood") or "").lower():
                score += 15
                reasons.append(f"in your preferred neighborhood ({prop.get('neighborhood')})")
                break

    # Cities
    if prefs.target_cities:
        if prop.get("city") in prefs.target_cities:
            score += 5

    return max(0, min(100, score)), reasons


def _score_property(prop, prefs: Preferences) -> tuple[int, list[str]]:
    """Return (score 0-100, list of match reasons)."""
    score = 50
    reasons = []

    # Budget
    if prefs.budget_max and prop.price > prefs.budget_max:
        score -= 30
    elif prefs.budget_max and prop.price <= prefs.budget_max * 0.9:
        score += 10
        reasons.append(f"well within budget at ${prop.price:,.0f}")

    # Bedrooms
    if prefs.bedrooms_min and prop.bedrooms >= prefs.bedrooms_min:
        score += 8
        reasons.append(f"{prop.bedrooms} beds meets your minimum")
    elif prefs.bedrooms_min and prop.bedrooms < prefs.bedrooms_min:
        score -= 15

    # Style
    features_lower = [f.lower() for f in (prop.features or [])]
    desc_lower = (prop.description or "").lower()
    style_lower = (prop.style or "").lower()

    if prefs.preferred_styles:
        for s in prefs.preferred_styles:
            if s.lower() in style_lower:
                score += 12
                reasons.append(f"matches your love of {s} style")
                break

    # Must-haves
    if prefs.needs_home_office:
        if "home office" in features_lower or "office" in desc_lower:
            score += 12
            reasons.append("has a dedicated home office")
        else:
            score -= 10

    if prefs.needs_pool:
        if "pool" in features_lower:
            score += 12
            reasons.append("has a pool")
        else:
            score -= 8

    if prefs.needs_good_schools:
        if "good schools" in features_lower or "isd" in desc_lower or "elementary" in desc_lower:
            score += 12
            reasons.append("located in a top-rated school district")
        else:
            score -= 5

    if prefs.needs_single_story:
        if prop.stories == 1:
            score += 10
            reasons.append("single story layout")
        else:
            score -= 12

    if prefs.needs_open_floor_plan:
        if "open floor plan" in features_lower or "open plan" in desc_lower:
            score += 8
            reasons.append("open floor plan")

    if prefs.needs_walkability:
        if "walkable" in features_lower or "walk" in desc_lower:
            score += 8
            reasons.append("highly walkable neighborhood")

    if prefs.needs_large_yard:
        if prop.lot_sqft and prop.lot_sqft >= 8000:
            score += 8
            reasons.append(f"large {prop.lot_sqft:,} sq ft lot")
        else:
            score -= 5

    if prefs.needs_new_construction:
        if prop.year_built and prop.year_built >= 2020:
            score += 10
            reasons.append(f"new construction ({prop.year_built})")
        else:
            score -= 5

    # Deal breakers
    for db in (prefs.deal_breakers or []):
        db_lower = db.lower()
        if db_lower == "hoa" and prop.hoa_monthly and prop.hoa_monthly > 0:
            score -= 25
        elif db_lower in features_lower or db_lower in desc_lower:
            score -= 20

    # Sqft
    if prefs.sqft_min and prop.sqft < prefs.sqft_min:
        score -= 12
    elif prefs.sqft_min and prop.sqft >= prefs.sqft_min * 1.1:
        score += 5
        reasons.append(f"generously sized at {prop.sqft:,} sqft")

    # Neighborhoods
    if prefs.target_neighborhoods:
        for n in prefs.target_neighborhoods:
            if n.lower() in (prop.neighborhood or "").lower():
                score += 15
                reasons.append(f"in your preferred neighborhood ({prop.neighborhood})")
                break

    # Cities
    if prefs.target_cities:
        if prop.city in prefs.target_cities:
            score += 5

    return max(0, min(100, score)), reasons


def _execute_tool(tool_name: str, tool_input: dict, customer_name: str, all_properties: list) -> Any:
    """Execute a tool call and return a JSON-serializable result."""

    if tool_name == "get_preferences":
        prefs = _store.get_preferences(customer_name)
        return _preferences_to_dict(prefs)

    elif tool_name == "update_preferences":
        prefs = _store.update_preferences(customer_name, tool_input)
        return {"status": "ok", "updated_fields": list(tool_input.keys())}

    elif tool_name == "search_properties":
        criteria = SearchCriteria(
            city=tool_input.get("city", ""),
            state=tool_input.get("state", ""),
            zip_code=tool_input.get("zip_code", ""),
            price_min=tool_input.get("price_min", 0),
            price_max=tool_input.get("price_max", 10_000_000),
            bedrooms_min=tool_input.get("bedrooms_min", 0),
            bathrooms_min=tool_input.get("bathrooms_min", 0),
            sqft_min=tool_input.get("sqft_min", 0),
            keywords=tool_input.get("keywords", []),
            limit=tool_input.get("limit", 5),
        )
        results = search_properties(all_properties, criteria)
        return [property_to_dict(p) for p in results]

    elif tool_name == "get_property_details":
        ext_id = tool_input["external_id"]
        for prop in all_properties:
            if prop["external_id"] == ext_id:
                return prop
        return {"error": f"Property {ext_id} not found"}

    elif tool_name == "save_property":
        ext_id = tool_input["external_id"]
        prop_found = any(p["external_id"] == ext_id for p in all_properties)
        if not prop_found:
            return {"error": f"Property {ext_id} not found"}

        saved = SavedProperty(
            external_id=ext_id,
            status=tool_input.get("status", "liked"),
            notes=tool_input.get("notes", ""),
            agent_rationale=tool_input.get("agent_rationale", ""),
        )
        _store.save_property(saved)
        return {"status": "saved", "external_id": ext_id}

    elif tool_name == "get_saved_properties":
        saved = _store.get_saved_properties()
        # Enrich with property data
        result = []
        for s in saved:
            for prop in all_properties:
                if prop["external_id"] == s.external_id:
                    d = prop.copy()
                    d["saved_status"] = s.status
                    d["saved_notes"] = s.notes
                    d["agent_rationale"] = s.agent_rationale
                    result.append(d)
                    break
        return result

    elif tool_name == "proactive_recommendations":
        top_n = tool_input.get("top_n", 3)
        prefs = _store.get_preferences(customer_name)
        saved = _store.get_saved_properties()

        # Get already disliked to exclude
        disliked_ids = {s.external_id for s in saved if s.status == "disliked"}

        scored = []
        for prop in all_properties:
            if prop["external_id"] in disliked_ids:
                continue
            score, reasons = _score_property_dict(prop, prefs)
            scored.append((score, reasons, prop))

        scored.sort(key=lambda x: x[0], reverse=True)
        recommendations = []
        for score, reasons, prop in scored[:top_n]:
            d = prop.copy()
            d["match_score"] = score
            d["match_reasons"] = reasons
            recommendations.append(d)
        return recommendations

    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt(customer_name: str, agent_name: str = "Cassie") -> str:
    today = datetime.utcnow().strftime("%B %d, %Y")
    return f"""You are {agent_name}, a warm and highly skilled real estate agent helping {customer_name} find her dream home. Today is {today}.

## GROUND RULES — read these first

### Anti-hallucination (critical)
- **Never invent properties.** Every property you mention must come from a `search_properties`, `get_property_details`, or `proactive_recommendations` tool call in *this conversation*. If you haven't called a tool yet, you have no listings to show.
- **Never fabricate details.** Do not guess, round, or embellish addresses, prices, square footage, features, schools, or neighborhoods. Use only exact values returned by tools.
- **Never assume availability.** Do not tell {customer_name} a property is available, has been reduced in price, or has any status you haven't confirmed from a tool result.
- **If a search returns nothing**, say so honestly and explain the filter that found no results. Do not substitute a made-up listing.
- **If you're unsure**, say "let me check" and call the appropriate tool — don't guess.

### Memory & preference learning
- Call `update_preferences` silently (without narrating it) whenever {customer_name} reveals anything about what she wants or doesn't want — hard requirements *and* soft signals alike.
  - Examples: "we both work from home" → `needs_home_office=true`; "I hate HOA drama" → `deal_breakers=["HOA"]`; "something bright and airy" → `preferred_vibes=["bright", "airy"]`
- Preferences accumulate — never overwrite existing values, always merge.
- After updating preferences, immediately run `proactive_recommendations` and share the top matches.

### Recommendations
- Always call `proactive_recommendations` (or `search_properties`) *before* describing specific homes. Never describe a home from memory.
- Lead with *why* a property matches {customer_name} specifically — connect features to things she has actually said.
- If she reacts positively or negatively to a property, call `save_property` to record it and extract new preference signals from her reaction.

## Conversation style
- Be warm, perceptive, and genuine — not salesy, not scripted.
- Ask one follow-up question at a time to sharpen your understanding.
- Format property details clearly (address, price, beds/baths/sqft, standout features) but keep the narrative personal and front and center.
- Never use filler phrases like "Great question!" or "Absolutely!".
- Keep responses focused — don't pad with unnecessary sentences.

## What you know right now
- You have access to a curated set of active listings. Treat them as your MLS.
- You do NOT know any listings outside of what the tools return.
- You do NOT know current mortgage rates, tax values, or neighborhood crime stats unless you have tool data for them.
"""


# ---------------------------------------------------------------------------
# Main chat function
# ---------------------------------------------------------------------------

def chat(
    user_message: str,
    messages_history: list | None = None,
    customer_name: str | None = None,
    agent_name: str | None = None,
) -> str:
    """Process a user message and return the agent's response."""
    customer_name = customer_name or os.getenv("CUSTOMER_NAME", "Sarah")
    agent_name = agent_name or os.getenv("AGENT_NAME", "Cassie")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Load properties
    all_properties = load_properties()

    # Build message history
    messages = (messages_history or []).copy()
    messages.append({"role": "user", "content": user_message})

    # Agentic loop
    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_build_system_prompt(customer_name, agent_name),
            tools=TOOLS,
            messages=messages,
        )

        # Collect text blocks for the final reply
        text_parts = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "end_turn":
            final_text = "\n".join(text_parts)
            return final_text

        if response.stop_reason == "tool_use":
            # Execute all tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(
                        block.name, block.input, customer_name, all_properties
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })

            # Add assistant turn + tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason
        break

    final_text = "\n".join(text_parts) if text_parts else "I'm sorry, something went wrong."
    return final_text


def reset_conversation(keep_preferences: bool = False) -> dict:
    """Clear conversation history. Optionally keep preferences."""
    _store.clear(keep_preferences=keep_preferences)
    return {"status": "reset"}

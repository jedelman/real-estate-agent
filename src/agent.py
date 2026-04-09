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

from .database import Conversation, Preferences, Property, SavedProperty, Session, get_session
from .properties import SearchCriteria, property_to_dict, search_properties, seed_sample_data

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

def _get_or_create_preferences(session: Session, customer_name: str) -> Preferences:
    prefs = session.query(Preferences).first()
    if not prefs:
        prefs = Preferences(customer_name=customer_name)
        session.add(prefs)
        session.commit()
    return prefs


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
        "updated_at": prefs.updated_at.isoformat() if prefs.updated_at else None,
    }


def _score_property(prop: Property, prefs: Preferences) -> tuple[int, list[str]]:
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


def _execute_tool(tool_name: str, tool_input: dict, session: Session, customer_name: str) -> Any:
    """Execute a tool call and return a JSON-serializable result."""

    if tool_name == "get_preferences":
        prefs = _get_or_create_preferences(session, customer_name)
        return _preferences_to_dict(prefs)

    elif tool_name == "update_preferences":
        prefs = _get_or_create_preferences(session, customer_name)
        list_fields = {"target_cities", "target_neighborhoods", "target_zip_codes",
                       "preferred_styles", "preferred_vibes", "deal_breakers"}
        for key, value in tool_input.items():
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
            elif key in list_fields and isinstance(value, list):
                # Merge lists (dedupe)
                existing_list = getattr(prefs, key) or []
                merged = list(dict.fromkeys(existing_list + value))
                setattr(prefs, key, merged)
            else:
                setattr(prefs, key, value)
        prefs.updated_at = datetime.utcnow()
        session.commit()
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
        results = search_properties(session, criteria)
        return [property_to_dict(p) for p in results]

    elif tool_name == "get_property_details":
        seed_sample_data(session)
        prop = session.query(Property).filter_by(
            external_id=tool_input["external_id"]
        ).first()
        if not prop:
            return {"error": f"Property {tool_input['external_id']} not found"}
        return property_to_dict(prop)

    elif tool_name == "save_property":
        seed_sample_data(session)
        prop = session.query(Property).filter_by(
            external_id=tool_input["external_id"]
        ).first()
        if not prop:
            return {"error": f"Property {tool_input['external_id']} not found"}

        saved = session.query(SavedProperty).filter_by(
            external_id=tool_input["external_id"]
        ).first()
        if not saved:
            saved = SavedProperty(
                property_id=prop.id,
                external_id=tool_input["external_id"],
            )
            session.add(saved)

        saved.status = tool_input.get("status", "liked")
        saved.notes = tool_input.get("notes", "")
        saved.agent_rationale = tool_input.get("agent_rationale", "")
        session.commit()
        return {"status": "saved", "external_id": tool_input["external_id"]}

    elif tool_name == "get_saved_properties":
        saved = session.query(SavedProperty).all()
        result = []
        for s in saved:
            prop = session.query(Property).filter_by(id=s.property_id).first()
            if prop:
                d = property_to_dict(prop)
                d["saved_status"] = s.status
                d["saved_notes"] = s.notes
                d["agent_rationale"] = s.agent_rationale
                result.append(d)
        return result

    elif tool_name == "proactive_recommendations":
        seed_sample_data(session)
        top_n = tool_input.get("top_n", 3)
        prefs = _get_or_create_preferences(session, customer_name)
        all_props = session.query(Property).filter_by(status="active").all()

        # Get already disliked to exclude
        disliked_ids = {
            s.external_id
            for s in session.query(SavedProperty).filter_by(status="disliked").all()
        }

        scored = []
        for prop in all_props:
            if prop.external_id in disliked_ids:
                continue
            score, reasons = _score_property(prop, prefs)
            scored.append((score, reasons, prop))

        scored.sort(key=lambda x: x[0], reverse=True)
        recommendations = []
        for score, reasons, prop in scored[:top_n]:
            d = property_to_dict(prop)
            d["match_score"] = score
            d["match_reasons"] = reasons
            recommendations.append(d)
        return recommendations

    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _build_system_prompt(customer_name: str) -> str:
    return f"""You are an expert real estate agent AI helping {customer_name} find her dream home.
You are warm, perceptive, and genuinely excited about finding the perfect match.

## Your core job
1. **Learn her preferences** through natural conversation. Every detail matters — not just hard requirements, but vibes, lifestyle hints, and even offhand comments. Silently call `update_preferences` whenever you learn something new.
2. **Proactively recommend** listings that match what she's told you. Don't wait to be asked — if you've just learned new preferences, immediately run `proactive_recommendations` and surface great matches.
3. **Explain the match** in personal terms. Don't just list features — connect them to what *she* said she wanted.
4. **Remember everything.** Preferences accumulate across conversations. Never forget what she's told you.

## Conversation style
- Be conversational and warm, not salesy.
- Ask follow-up questions to sharpen your understanding (one at a time).
- When showing properties, lead with why it matches *her* specifically, then give the facts.
- Format property recommendations clearly with key stats, but keep the narrative front and center.
- If she reacts to a property (positively or negatively), use `save_property` and extract preference signals from her reaction.

## First interaction
If this looks like a first conversation (no preferences set yet), warmly introduce yourself and ask an open-ended question to start learning what she's looking for. Don't bombard her with a form — have a real conversation.

## Today's date: {datetime.utcnow().strftime("%B %d, %Y")}
"""


# ---------------------------------------------------------------------------
# Main chat function
# ---------------------------------------------------------------------------

def chat(user_message: str, customer_name: str | None = None) -> str:
    """Process a user message and return the agent's response."""
    customer_name = customer_name or os.getenv("CUSTOMER_NAME", "Sarah")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    with get_session() as session:
        # Load conversation history
        history = session.query(Conversation).order_by(Conversation.timestamp).all()
        messages = [{"role": h.role, "content": h.content} for h in history]
        messages.append({"role": "user", "content": user_message})

        # Agentic loop
        while True:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=_build_system_prompt(customer_name),
                tools=TOOLS,
                messages=messages,
            )

            # Collect text blocks for the final reply
            text_parts = [b.text for b in response.content if b.type == "text"]

            if response.stop_reason == "end_turn":
                final_text = "\n".join(text_parts)
                # Persist exchange
                session.add(Conversation(role="user", content=user_message))
                session.add(Conversation(role="assistant", content=final_text))
                session.commit()
                return final_text

            if response.stop_reason == "tool_use":
                # Execute all tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = _execute_tool(
                            block.name, block.input, session, customer_name
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
        session.add(Conversation(role="user", content=user_message))
        session.add(Conversation(role="assistant", content=final_text))
        session.commit()
        return final_text


def reset_conversation(keep_preferences: bool = False) -> dict:
    """Clear conversation history. Optionally keep preferences."""
    with get_session() as session:
        session.query(Conversation).delete()
        if not keep_preferences:
            session.query(SavedProperty).delete()
            session.query(Preferences).delete()
        session.commit()
    return {"status": "reset"}

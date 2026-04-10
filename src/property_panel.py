"""Property card extraction and rendering.

After each agent response, a fast haiku call extracts any properties the
agent described into structured dicts. These are rendered as interactive
cards in the UI with reaction buttons (❤️ Love / 👎 Pass / 📅 Tour).

User reactions are fed back into the agent session as a structured message
so the agent can update its recommendations accordingly.
"""

import json
import os

import anthropic
import streamlit as st

_EXTRACT_SYSTEM = """\
You extract real estate property listings that were described in an agent response.

Return a JSON array. Each element represents one distinct property mentioned.
Use this schema exactly:

{
  "address": "Full street address",
  "city": "City name",
  "state": "State abbreviation (e.g. TX)",
  "price": 850000,
  "bedrooms": 4,
  "bathrooms": 3.0,
  "sqft": 2800,
  "year_built": 2019,
  "hoa_monthly": 0,
  "style": "modern farmhouse",
  "features": ["home office", "open floor plan"],
  "why_it_matches": "One or two sentences connecting this home to the buyer's stated preferences.",
  "listing_url": "https://..."
}

Rules:
- Only include properties with a real, specific address — not hypothetical examples.
- Use null for any field not explicitly mentioned in the response.
- If no properties are described, return [].
- Return valid JSON only. No explanation.
"""


def extract_properties(agent_response: str) -> list[dict]:
    """Extract structured property dicts from an agent response."""
    if not agent_response.strip():
        return []

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": agent_response}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        props = json.loads(raw)
        return props if isinstance(props, list) else []
    except Exception:
        return []


def reaction_message(prop: dict, reaction: str, notes: str = "") -> str:
    """Build the feedback message sent back to the agent after a user reaction."""
    addr = prop.get("address", "that property")
    price = f"${prop.get('price', 0):,.0f}" if prop.get("price") else ""
    label = {"liked": "❤️ love it", "disliked": "👎 pass", "touring": "📅 want to tour"}
    emoji_label = label.get(reaction, reaction)
    msg = f"[USER REACTION] I {emoji_label} — {addr}{f' ({price})' if price else ''}."
    if notes:
        msg += f" My thoughts: {notes}"
    return msg


def _prop_key(prop: dict, idx: int) -> str:
    """Stable key for a property card widget."""
    addr = (prop.get("address") or "").replace(" ", "_")[:30]
    return f"prop_{idx}_{addr}"


def render_property_cards(
    property_cards: list[dict],
    on_reaction,          # callable(prop, reaction, notes)
    reactions: dict,      # {prop_key: "liked"|"disliked"|"touring"}
) -> None:
    """Render all property cards in the panel.

    Args:
        property_cards: List of extracted property dicts.
        on_reaction: Called when user clicks a reaction button.
        reactions: Current reaction state per card key.
    """
    if not property_cards:
        st.caption("Properties the agent mentions will appear here.")
        return

    for idx, prop in enumerate(property_cards):
        key = _prop_key(prop, idx)
        current_reaction = reactions.get(key)

        with st.container(border=True):
            # Header row
            addr = prop.get("address") or "Unknown address"
            city_state = f"{prop.get('city', '')}, {prop.get('state', '')}".strip(", ")
            price = prop.get("price")

            st.markdown(f"**{addr}**")
            if city_state:
                st.caption(city_state)
            if price:
                st.metric("List price", f"${price:,.0f}", label_visibility="collapsed")

            # Key stats
            stats = []
            if prop.get("bedrooms"):
                stats.append(f"{prop['bedrooms']} bd")
            if prop.get("bathrooms"):
                stats.append(f"{prop['bathrooms']} ba")
            if prop.get("sqft"):
                stats.append(f"{prop['sqft']:,} sqft")
            if prop.get("year_built"):
                stats.append(f"Built {prop['year_built']}")
            if prop.get("hoa_monthly"):
                stats.append(f"HOA ${prop['hoa_monthly']}/mo")
            if stats:
                st.write(" · ".join(stats))

            if prop.get("style"):
                st.write(f"*{prop['style'].title()}*")

            if prop.get("features"):
                st.write(", ".join(prop["features"]))

            if prop.get("why_it_matches"):
                st.info(prop["why_it_matches"], icon="💡")

            if prop.get("listing_url"):
                st.markdown(f"[View listing →]({prop['listing_url']})")

            # Reaction buttons (disabled if already reacted)
            reacted = current_reaction is not None
            if reacted:
                labels = {"liked": "❤️ Loved it", "disliked": "👎 Passed", "touring": "📅 Touring"}
                st.success(labels.get(current_reaction, current_reaction))
            else:
                notes_key = f"notes_{key}"
                notes = st.text_input(
                    "Thoughts?",
                    key=notes_key,
                    placeholder="Optional — tell the agent why",
                    label_visibility="collapsed",
                )
                col1, col2, col3 = st.columns(3)
                if col1.button("❤️ Love it", key=f"love_{key}", use_container_width=True):
                    on_reaction(prop, "liked", notes, key)
                if col2.button("👎 Pass", key=f"pass_{key}", use_container_width=True):
                    on_reaction(prop, "disliked", notes, key)
                if col3.button("📅 Tour", key=f"tour_{key}", use_container_width=True):
                    on_reaction(prop, "touring", notes, key)

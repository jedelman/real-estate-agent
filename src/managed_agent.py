"""Managed Agent lifecycle and session management.

Creates the Anthropic Managed Agent once (storing the ID in config) and
manages per-conversation sessions. The agent has unrestricted web access,
using web_search and web_fetch to find real property listings.

Lifecycle:
  - Agent definition: created once per deployment, referenced by ID
  - Environment: created once per deployment, referenced by ID
  - Session: created once per conversation, re-used for all turns
"""

import os
from datetime import datetime

import anthropic

from .storage import AppConfig, ConfigStore, Preferences


def _system_prompt(agent_name: str, customer_name: str, prefs: Preferences) -> str:
    pref_summary = prefs.summary()
    today = datetime.utcnow().strftime("%B %d, %Y")
    return f"""\
You are {agent_name}, a warm and highly skilled real estate agent helping \
{customer_name} find her dream home. Today is {today}.

## {customer_name}'s current preferences
{pref_summary}

## Your core job
1. **Find real properties.** Use web_search and web_fetch to find actual current \
listings on Zillow, Redfin, Realtor.com, or local MLS sites. Never describe a \
property you haven't retrieved from the web in this session.
2. **Learn her preferences** through natural conversation. Every detail matters — \
not just hard requirements, but vibes, lifestyle hints, and indirect signals.
3. **Explain every match personally.** Connect each property's features to what \
{customer_name} specifically told you. Don't just list stats.
4. **Ask one follow-up question at a time** to sharpen your understanding.

## Anti-hallucination rules (strictly enforced)
- **Never invent or estimate property details.** Address, price, sqft, features, \
  school district, HOA — use only values you retrieved from the web this session.
- **Never describe a property you haven't fetched.** If web_search returns titles \
  and snippets, use web_fetch to get the full listing before presenting it.
- **If a search returns no results**, say so honestly. Do not substitute sample data.
- **If you're unsure about any detail**, say so and go look it up.
- **Do not reference listings from a prior session** — you are starting fresh.

## Search strategy
- Start with the buyer's known preferences (above) as search filters.
- Try multiple sources if the first search is thin (Zillow → Redfin → Realtor.com).
- Fetch full listing pages to get accurate details (price, beds/baths, sqft, features).
- Extract and report: address, list price, beds, baths, sqft, lot size, year built, \
  HOA fee, key features, school district, days on market, and listing URL.

## Tone & style
- Warm, perceptive, genuine — not salesy or scripted.
- Lead with *why* a property matches her, then the facts.
- Never use filler phrases like "Great question!" or "Absolutely!".
- Keep responses focused and personal.
"""


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def provision(config_store: ConfigStore, prefs: Preferences) -> str:
    """Ensure the Managed Agent and environment exist. Return session_id for a new session.

    Creates the agent + environment on first call and stores their IDs in
    config.json for reuse. Always creates a fresh session (one per conversation).
    """
    cfg = config_store.load()
    client = _get_client()

    # Create agent if not yet provisioned
    if not cfg.managed_agent_id:
        agent = client.beta.agents.create(
            name=f"{cfg.agent_name} — Real Estate Agent",
            model="claude-sonnet-4-6",  # Sonnet for web browsing quality
            system=_system_prompt(cfg.agent_name, cfg.customer_name, prefs),
            tools=[{"type": "agent_toolset_20260401"}],
        )
        cfg = config_store.update(managed_agent_id=agent.id)

    # Create environment if not yet provisioned
    if not cfg.environment_id:
        env = client.beta.environments.create(
            name="real-estate-agent-env",
            config={
                "type": "cloud",
                "networking": {"type": "unrestricted"},
            },
        )
        cfg = config_store.update(environment_id=env.id)

    # Always start a fresh session for each conversation
    session = client.beta.sessions.create(
        agent=cfg.managed_agent_id,
        environment_id=cfg.environment_id,
        title=f"Session for {cfg.customer_name} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
    )
    config_store.update(session_id=session.id)
    return session.id


def stream_message(session_id: str):
    """Generator that yields (event_type, text_chunk) tuples from an open SSE stream.

    Caller is responsible for sending the user event before or after opening
    the stream. This generator processes SSE events and yields:
      ("text", str)        — text delta to display
      ("tool", str)        — tool name being used (for status display)
      ("done", "")         — agent reached idle state

    Usage:
        session_id = provision(config_store, prefs)
        send_user_event(session_id, user_message)
        for event_type, chunk in stream_message(session_id):
            ...
    """
    client = _get_client()
    with client.beta.sessions.events.stream(session_id) as stream:
        for event in stream:
            match event.type:
                case "agent.message":
                    for block in event.content:
                        if hasattr(block, "text"):
                            yield ("text", block.text)
                case "agent.tool_use":
                    yield ("tool", getattr(event, "name", "tool"))
                case "session.status_idle":
                    yield ("done", "")
                    return


def send_user_event(session_id: str, message: str) -> None:
    """Send a user message event to an existing session."""
    client = _get_client()
    client.beta.sessions.events.send(
        session_id,
        events=[{
            "type": "user.message",
            "content": [{"type": "text", "text": message}],
        }],
    )


def update_agent_system_prompt(
    config_store: ConfigStore,
    prefs: Preferences,
) -> None:
    """Update the managed agent's system prompt when preferences change significantly.

    Creates a new agent version with the updated preferences baked in.
    The next new session will pick up the updated prompt automatically.
    """
    cfg = config_store.load()
    if not cfg.managed_agent_id:
        return
    client = _get_client()
    client.beta.agents.update(
        cfg.managed_agent_id,
        system=_system_prompt(cfg.agent_name, cfg.customer_name, prefs),
    )

"""Managed Agent lifecycle and session management.

The agent definition contains only generic rules (no customer-specific info).
Customer identity and preferences are injected fresh into every new session
via the opening user message — so a name change in onboarding is reflected
immediately without reprovisioning.

Lifecycle:
  - Agent:        created once, stored as managed_agent_id in config.json
  - Environment:  created once, stored as environment_id in config.json
  - Session:      created once per conversation; session_id in config.json
"""

import os
from datetime import datetime

import anthropic

from .storage import ConfigStore, Preferences

# ---------------------------------------------------------------------------
# Agent system prompt — generic, no customer-specific content
# ---------------------------------------------------------------------------

_AGENT_SYSTEM = """\
You are a warm, expert personal real estate agent. At the start of every \
session you will receive a [SESSION CONTEXT] block that tells you:
  - Your agent name for this session
  - Your customer's name
  - Their current home search preferences

Use that context to personalize every response. Update your understanding as \
the conversation reveals new preferences.

## Anti-hallucination rules (strictly enforced)
- **Never invent or estimate property details.** Address, price, sqft, \
  features, school district, HOA — use only values you retrieved from the web \
  in this session.
- **Never describe a property you haven't fetched.** Use web_search to find \
  candidates, then web_fetch the full listing page before presenting details.
- **If a search returns no results**, say so honestly. Do not substitute \
  invented listings.
- **If you are unsure about any detail**, say so and look it up.
- **Do not reference listings from a prior session** — you are starting fresh.

## Search strategy
- Start with the buyer's preferences from [SESSION CONTEXT] as filters.
- Try multiple sources if the first search is thin \
  (Zillow → Redfin → Realtor.com → local broker sites).
- Fetch full listing pages; extract: address, list price, beds, baths, sqft, \
  lot size, year built, HOA fee, notable features, school district, \
  days on market, and listing URL.

## Tone & style
- Warm, perceptive, genuine — not salesy or scripted.
- Lead with *why* a property matches this specific buyer, then the facts.
- Ask one follow-up question at a time to sharpen your understanding.
- Never use filler phrases like "Great question!" or "Absolutely!".
"""


def _session_context_block(
    agent_name: str, customer_name: str, prefs: Preferences, saved: list = None
) -> str:
    """Injected as the opening of the first user turn in every new session."""
    today = datetime.utcnow().strftime("%B %d, %Y")
    lines = [
        f"[SESSION CONTEXT — {today}]",
        f"Agent name: {agent_name}",
        f"Customer name: {customer_name}",
        f"Current preferences:\n{prefs.summary()}",
    ]
    active = [s for s in (saved or []) if s.status != "disliked"]
    if active:
        lines.append("\nProperties already on the buyer's radar (reference these; don't re-present as new):")
        status_emoji = {"liked": "❤️", "touring": "📅", "offered": "🏷️"}
        for s in active:
            badge = status_emoji.get(s.status, "•")
            detail = f"  {badge} {s.address or s.external_id}"
            if s.price:
                detail += f" (${s.price:,.0f})"
            if s.status != "liked":
                detail += f" [{s.status}]"
            if s.notes:
                detail += f"\n     Buyer note: {s.notes}"
            if s.agent_rationale:
                detail += f"\n     Why it matched: {s.agent_rationale}"
            lines.append(detail)
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _clear_stale(config_store: ConfigStore, clear_agent: bool = False, clear_env: bool = False) -> None:
    """Remove stale IDs from config so the next call recreates them."""
    updates = {}
    if clear_agent:
        updates["managed_agent_id"] = None
    if clear_env:
        updates["environment_id"] = None
    updates["session_id"] = None
    config_store.update(**updates)


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

def provision(config_store: ConfigStore, prefs: Preferences) -> str:
    """Ensure agent + environment exist; create and return a new session_id.

    On first call: creates the Managed Agent and environment and saves their
    IDs to config.json. Subsequent calls reuse those IDs.

    Always creates a fresh session (one per conversation).
    If an API call fails because a stored ID is stale (deleted in console),
    clears the stale ID and retries once.
    """
    cfg = config_store.load()
    client = _client()

    # -- Agent --
    if not cfg.managed_agent_id:
        agent = client.beta.agents.create(
            name="Real Estate Agent",
            model="claude-sonnet-4-6",
            system=_AGENT_SYSTEM,
            tools=[{"type": "agent_toolset_20260401"}],
        )
        cfg = config_store.update(managed_agent_id=agent.id)

    # -- Environment --
    if not cfg.environment_id:
        env = client.beta.environments.create(
            name="real-estate-agent-env",
            config={
                "type": "cloud",
                "networking": {"type": "unrestricted"},
            },
        )
        cfg = config_store.update(environment_id=env.id)

    # -- Session --
    try:
        session = client.beta.sessions.create(
            agent=cfg.managed_agent_id,
            environment_id=cfg.environment_id,
            title=f"{cfg.customer_name} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        )
    except anthropic.NotFoundError:
        # Agent or environment was deleted from the console — reprovision both
        _clear_stale(config_store, clear_agent=True, clear_env=True)
        return provision(config_store, prefs)  # one retry

    config_store.update(session_id=session.id)
    return session.id


def build_greeting_prompt(
    agent_name: str, customer_name: str, prefs: Preferences, saved: list = None
) -> str:
    """First user message for a new session: context block + greeting request."""
    context = _session_context_block(agent_name, customer_name, prefs, saved)
    return (
        context
        + f"Hello! Please introduce yourself as {agent_name} and warmly start "
        "our first home-search conversation. Ask me one open question to get "
        "started — don't list requirements yet."
    )


def build_context_prefix(
    agent_name: str, customer_name: str, prefs: Preferences, saved: list = None
) -> str:
    """Prepend this to any user message in a *resumed* session after a refresh,
    so the agent is re-oriented without a full new session."""
    return _session_context_block(agent_name, customer_name, prefs, saved)


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------

def send_user_event(session_id: str, message: str) -> None:
    client = _client()
    client.beta.sessions.events.send(
        session_id,
        events=[{
            "type": "user.message",
            "content": [{"type": "text", "text": message}],
        }],
    )


def stream_message(session_id: str):
    """Yield (event_type, chunk) from the SSE stream.

    Types:
      ("text", str)   — text to display
      ("tool", str)   — tool name being invoked
      ("done", "")    — agent reached idle state
    """
    client = _client()
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

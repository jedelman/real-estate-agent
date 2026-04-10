"""Streamlit app — real estate agent powered by Claude Managed Agents.

Layout:
  Left (chat):     Conversation with Cassie
  Right (panel):   Property cards extracted from each response;
                   reaction buttons feed back into the agent session
  Sidebar:         Buyer profile (preferences + saved)
"""

import os
import threading

import streamlit as st
from dotenv import load_dotenv

from src.extractor import extract_and_apply
from src.managed_agent import build_greeting_prompt, provision, send_user_event, stream_message
from src.property_panel import extract_properties, reaction_message, render_property_cards
from src.storage import AppConfig, ConfigStore, PreferencesStore

load_dotenv()

# Push Streamlit secrets into env vars so all modules can use os.environ uniformly
for _k in ["ANTHROPIC_API_KEY", "STORAGE_BACKEND",
           "CF_API_TOKEN", "CF_ACCOUNT_ID", "CF_D1_DATABASE_ID"]:
    if _k not in os.environ and _k in st.secrets:
        os.environ[_k] = st.secrets[_k]

st.set_page_config(
    page_title="Your Real Estate Agent",
    page_icon="🏡",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

@st.cache_resource
def get_stores():
    return ConfigStore(), PreferencesStore()

config_store, pref_store = get_stores()


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

def run_onboarding():
    st.markdown("## Welcome to your personal real estate agent 🏡")
    st.write(
        "Let's spend 30 seconds setting things up so the experience feels "
        "personal from the very first message."
    )
    st.divider()

    with st.form("onboarding_form"):
        st.subheader("About you")
        customer_name = st.text_input("What's your name?", value="Sarah")

        st.subheader("Your agent")
        agent_name = st.text_input(
            "What would you like to call your agent?", value="Cassie"
        )
        st.radio("Agent pronouns", ["She/Her", "He/Him", "They/Them"],
                 horizontal=True, index=0)

        st.divider()
        submitted = st.form_submit_button("Let's get started →", use_container_width=True)

    if submitted:
        if not customer_name.strip() or not agent_name.strip():
            st.error("Please fill in both fields.")
            st.stop()
        cfg = AppConfig(
            agent_name=agent_name.strip(),
            customer_name=customer_name.strip(),
            setup_complete=True,
        )
        config_store.save(cfg)
        st.session_state.cfg = cfg
        st.rerun()


# ---------------------------------------------------------------------------
# Load config — gate on onboarding
# ---------------------------------------------------------------------------

if "cfg" not in st.session_state:
    cfg = config_store.load()
    if not cfg.setup_complete:
        run_onboarding()
        st.stop()
    st.session_state.cfg = cfg

cfg: AppConfig = st.session_state.cfg

# Session state defaults — restore checkpointed messages on first load
for key, default in [
    ("messages", pref_store.load_messages() if cfg.session_id else []),
    ("session_id", cfg.session_id),
    ("initialized", bool(cfg.session_id)),  # skip greeting if resuming
    ("property_cards", []),   # accumulated across the whole conversation
    ("reactions", {}),        # prop_key → "liked"|"disliked"|"touring"
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Sidebar — buyer profile
# ---------------------------------------------------------------------------

with st.sidebar:
    prefs = pref_store.get(cfg.customer_name)
    st.markdown(f"### {cfg.customer_name}'s Profile")
    st.caption(f"Agent: {cfg.agent_name}")

    has_prefs = any([
        prefs.budget_max, prefs.target_cities, prefs.bedrooms_min,
        prefs.preferred_styles, prefs.deal_breakers, prefs.needs_home_office,
        prefs.needs_pool, prefs.needs_good_schools,
    ])

    if has_prefs:
        with st.expander("📋 Preferences", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                if prefs.budget_max:
                    st.metric("Max Budget", f"${prefs.budget_max:,.0f}")
                if prefs.bedrooms_min:
                    st.metric("Min Beds", prefs.bedrooms_min)
            with col2:
                if prefs.sqft_min:
                    st.metric("Min Sqft", f"{prefs.sqft_min:,.0f}")
                if prefs.bathrooms_min:
                    st.metric("Min Baths", prefs.bathrooms_min)
            if prefs.target_cities:
                st.write("**Cities:**", ", ".join(prefs.target_cities))
            if prefs.preferred_styles:
                st.write("**Style:**", ", ".join(prefs.preferred_styles))
            if prefs.preferred_vibes:
                st.write("**Vibes:**", ", ".join(prefs.preferred_vibes))
            must_haves = [
                lbl for flag, lbl in [
                    (prefs.needs_home_office, "Home office"),
                    (prefs.needs_pool, "Pool"),
                    (prefs.needs_good_schools, "Good schools"),
                    (prefs.needs_single_story, "Single story"),
                    (prefs.needs_open_floor_plan, "Open floor plan"),
                    (prefs.needs_walkability, "Walkability"),
                    (prefs.needs_large_yard, "Large yard"),
                    (prefs.needs_new_construction, "New construction"),
                ] if flag
            ]
            if must_haves:
                st.write("**Must-haves:**", ", ".join(must_haves))
            if prefs.deal_breakers:
                st.write("**Deal-breakers:**", ", ".join(prefs.deal_breakers))
    else:
        st.info(f"👉 Chat with {cfg.agent_name} to build your profile!")

    saved = pref_store.get_saved()
    liked = [s for s in saved if s.status == "liked"]
    if liked:
        with st.expander(f"❤️ Saved ({len(liked)})", expanded=False):
            for s in liked:
                with st.container(border=True):
                    st.write(f"**{s.address or s.external_id}**")
                    if s.price:
                        st.write(f"${s.price:,.0f}")
                    if s.agent_rationale:
                        st.caption(s.agent_rationale)

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 New chat", use_container_width=True):
            pref_store.save_messages([])
            st.session_state.update({
                "messages": [],
                "session_id": None,
                "initialized": False,
                "property_cards": [],
                "reactions": {},
            })
            config_store.update(session_id=None)
            st.rerun()
    with col_b:
        if st.button("⚙️ Setup", use_container_width=True):
            config_store.update(
                setup_complete=False,
                session_id=None,
                managed_agent_id=None,
                environment_id=None,
            )
            pref_store.clear(keep_preferences=False)
            for k in ["cfg", "messages", "session_id", "initialized",
                      "property_cards", "reactions"]:
                st.session_state.pop(k, None)
            st.rerun()


# ---------------------------------------------------------------------------
# Main layout: chat (left) | property panel (right)
# ---------------------------------------------------------------------------

col_chat, col_panel = st.columns([3, 2], gap="large")


# ---------------------------------------------------------------------------
# Property panel (right column)
# ---------------------------------------------------------------------------

with col_panel:
    st.subheader("Properties", anchor=False)

    def handle_reaction(prop: dict, reaction: str, notes: str, key: str):
        """Save reaction, update UI state, and send feedback to the agent."""
        # Persist to storage
        entry = PreferencesStore.SavedEntry(
            external_id=key,
            address=prop.get("address", ""),
            price=prop.get("price", 0),
            status=reaction,
            notes=notes,
            agent_rationale=prop.get("why_it_matches", ""),
        )
        pref_store.save_property(entry)

        # Update local reaction state
        st.session_state.reactions[key] = reaction

        # Build and display feedback message in chat
        feedback = reaction_message(prop, reaction, notes)
        st.session_state.messages.append({"role": "user", "content": feedback})

        # Send to managed agent session
        if st.session_state.session_id:
            try:
                send_user_event(st.session_state.session_id, feedback)
                # Stream the agent's response to the reaction
                with col_chat:
                    with st.chat_message("user"):
                        st.markdown(feedback)
                    with st.chat_message("assistant"):
                        response_text = _stream_response(
                            st.session_state.session_id,
                            already_sent=True,  # already sent above
                        )
                st.session_state.messages.append(
                    {"role": "assistant", "content": response_text}
                )
                _post_process(response_text)
            except Exception:
                pass

        st.rerun()

    render_property_cards(
        st.session_state.property_cards,
        on_reaction=handle_reaction,
        reactions=st.session_state.reactions,
    )


# ---------------------------------------------------------------------------
# Chat (left column)
# ---------------------------------------------------------------------------

with col_chat:
    st.subheader(f"Chat with {cfg.agent_name}", anchor=False)
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])


# ---------------------------------------------------------------------------
# Helpers (defined after columns so they can render into col_chat / col_panel)
# ---------------------------------------------------------------------------

def _ensure_session() -> str:
    if not st.session_state.session_id:
        prefs = pref_store.get(cfg.customer_name)
        session_id = provision(config_store, prefs)
        st.session_state.session_id = session_id
    return st.session_state.session_id


def _stream_response(session_id: str, user_message: str = "", already_sent: bool = False) -> str:
    """Send (optionally) and stream a response. Returns full response text."""
    if not already_sent and user_message:
        send_user_event(session_id, user_message)

    with col_chat:
        placeholder = st.empty()
        tool_status = st.empty()

    full_text = ""
    for event_type, chunk in stream_message(session_id):
        if event_type == "text":
            full_text += chunk
            with col_chat:
                placeholder.markdown(full_text + "▌")
        elif event_type == "tool":
            with col_chat:
                tool_status.caption(f"🔍 {chunk}…")
        elif event_type == "done":
            with col_chat:
                tool_status.empty()
            break

    with col_chat:
        placeholder.markdown(full_text)
    return full_text


def _post_process(response_text: str):
    """After each response: checkpoint messages + extract preferences + extract property cards."""
    conversation = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    # Checkpoint immediately (before background work) so a refresh never loses a turn
    pref_store.save_messages(st.session_state.messages)

    def _run():
        # Preference extraction (CHECKS pattern)
        extract_and_apply(conversation, pref_store, cfg.customer_name)
        # Property extraction
        new_props = extract_properties(response_text)
        if new_props:
            # Dedupe by address
            existing_addrs = {p.get("address") for p in st.session_state.property_cards}
            for p in new_props:
                if p.get("address") not in existing_addrs:
                    st.session_state.property_cards.append(p)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=8)  # wait up to 8s so cards appear on the same rerun


# ---------------------------------------------------------------------------
# Auto-greet on first load
# ---------------------------------------------------------------------------

if not st.session_state.initialized:
    prefs = pref_store.get(cfg.customer_name)
    is_returning = any([prefs.budget_max, prefs.target_cities, prefs.bedrooms_min])

    if is_returning:
        greeting = (
            f"Welcome back, {cfg.customer_name}! Your preferences are loaded. "
            "What would you like to explore today?"
        )
        st.session_state.messages.append({"role": "assistant", "content": greeting})
        with col_chat:
            with st.chat_message("assistant"):
                st.markdown(greeting)
    else:
        with col_chat:
            with st.chat_message("assistant"):
                try:
                    session_id = _ensure_session()
                    prefs = pref_store.get(cfg.customer_name)
                    greeting_prompt = build_greeting_prompt(
                        cfg.agent_name, cfg.customer_name, prefs
                    )
                    greeting = _stream_response(session_id, greeting_prompt)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": greeting}
                    )
                except Exception as e:
                    fallback = (
                        f"Hi {cfg.customer_name}! I'm {cfg.agent_name}, your personal "
                        "real estate agent. What kind of home are you dreaming of?"
                    )
                    st.markdown(fallback)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": fallback}
                    )

    st.session_state.initialized = True


# ---------------------------------------------------------------------------
# Chat input (must be at page level, not inside a column)
# ---------------------------------------------------------------------------

user_input = st.chat_input(f"Message {cfg.agent_name}…")
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with col_chat:
        with st.chat_message("user"):
            st.markdown(user_input)

    with col_chat:
        with st.chat_message("assistant"):
            try:
                session_id = _ensure_session()
                response_text = _stream_response(session_id, user_input)
            except Exception as e:
                response_text = (
                    f"I'm having trouble connecting. "
                    f"Please check your API key and try again.\n\n`{e}`"
                )
                with col_chat:
                    st.markdown(response_text)

    st.session_state.messages.append({"role": "assistant", "content": response_text})
    _post_process(response_text)
    st.rerun()

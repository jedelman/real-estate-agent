"""Streamlit app — real estate agent powered by Claude Managed Agents.

Architecture:
  - Managed Agent (Anthropic cloud): web_search + web_fetch for real listings
  - Preference Extractor: haiku call after each response to capture signals
  - PreferencesStore / ConfigStore: JSON persistence (D1-swappable)
  - Streamlit: UI + session orchestration
"""

import os
import threading

import streamlit as st
from dotenv import load_dotenv

from src.extractor import extract_and_apply
from src.managed_agent import provision, send_user_event, stream_message
from src.storage import AppConfig, ConfigStore, PreferencesStore

load_dotenv()

st.set_page_config(page_title="Your Real Estate Agent", page_icon="🏡", layout="wide")

# ---------------------------------------------------------------------------
# Singletons — one store per process (ValueModels fix)
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
        agent_gender = st.radio(
            "Agent pronouns", ["She/Her", "He/Him", "They/Them"],
            horizontal=True, index=0,
        )

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
# Load config (gate on onboarding)
# ---------------------------------------------------------------------------

if "cfg" not in st.session_state:
    cfg = config_store.load()
    if not cfg.setup_complete:
        run_onboarding()
        st.stop()
    st.session_state.cfg = cfg

cfg: AppConfig = st.session_state.cfg

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = cfg.session_id  # resume if exists
if "initialized" not in st.session_state:
    st.session_state.initialized = False


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    prefs = pref_store.get(cfg.customer_name)
    st.markdown(f"### {cfg.customer_name}'s Home Profile")
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
        st.info(f"👉 Start chatting with {cfg.agent_name} to build your profile!")

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
            st.session_state.messages = []
            st.session_state.session_id = None
            st.session_state.initialized = False
            config_store.update(session_id=None)
            st.rerun()
    with col_b:
        if st.button("⚙️ Setup", use_container_width=True):
            config_store.update(setup_complete=False, session_id=None)
            pref_store.clear(keep_preferences=False)
            for k in ["cfg", "messages", "session_id", "initialized"]:
                st.session_state.pop(k, None)
            st.rerun()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

st.subheader(f"Chat with {cfg.agent_name}", anchor=False)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


def _ensure_session() -> str:
    """Provision a Managed Agent session if one doesn't exist yet."""
    if not st.session_state.session_id:
        prefs = pref_store.get(cfg.customer_name)
        session_id = provision(config_store, prefs)
        st.session_state.session_id = session_id
    return st.session_state.session_id


def _stream_response(session_id: str, user_message: str) -> str:
    """Send a message and stream the response into the chat. Returns full text."""
    send_user_event(session_id, user_message)

    placeholder = st.empty()
    full_text = ""
    tool_status = st.empty()

    for event_type, chunk in stream_message(session_id):
        if event_type == "text":
            full_text += chunk
            placeholder.markdown(full_text + "▌")
        elif event_type == "tool":
            tool_status.caption(f"🔍 Using {chunk}…")
        elif event_type == "done":
            tool_status.empty()
            break

    placeholder.markdown(full_text)
    return full_text


# Auto-greet on first load
if not st.session_state.initialized:
    prefs = pref_store.get(cfg.customer_name)
    is_returning = any([prefs.budget_max, prefs.target_cities, prefs.bedrooms_min])

    if is_returning:
        greeting = (
            f"Welcome back, {cfg.customer_name}! Your preferences are loaded. "
            "What would you like to explore today?"
        )
        st.session_state.messages.append({"role": "assistant", "content": greeting})
        with st.chat_message("assistant"):
            st.markdown(greeting)
    else:
        with st.chat_message("assistant"):
            try:
                session_id = _ensure_session()
                greeting_prompt = (
                    f"Hello! My name is {cfg.customer_name}. "
                    f"Please introduce yourself as {cfg.agent_name} and warmly "
                    "start our first conversation about finding my dream home. "
                    "Ask me one open question to get started — don't list requirements yet."
                )
                greeting = _stream_response(session_id, greeting_prompt)
                st.session_state.messages.append({"role": "assistant", "content": greeting})
            except Exception as e:
                fallback = (
                    f"Hi {cfg.customer_name}! I'm {cfg.agent_name}, your personal "
                    "real estate agent. What kind of home are you dreaming of?"
                )
                st.markdown(fallback)
                st.session_state.messages.append({"role": "assistant", "content": fallback})

    st.session_state.initialized = True


# Chat input
user_input = st.chat_input(f"Message {cfg.agent_name}…")
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        try:
            session_id = _ensure_session()
            response_text = _stream_response(session_id, user_input)
        except Exception as e:
            response_text = (
                f"I'm having trouble connecting right now. "
                f"Please check your API key and try again.\n\n`{e}`"
            )
            st.markdown(response_text)

    st.session_state.messages.append({"role": "assistant", "content": response_text})

    # Extract preference signals in the background (CHECKS pattern)
    conversation = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages
    ]

    def _extract():
        extract_and_apply(conversation, pref_store, cfg.customer_name)

    t = threading.Thread(target=_extract, daemon=True)
    t.start()

    st.rerun()  # Refresh sidebar with updated preferences

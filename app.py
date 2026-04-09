"""Streamlit app for the real estate agent."""

import os

import streamlit as st
from dotenv import load_dotenv

from src.agent import chat, reset_conversation
from src.properties import load_properties
from src.storage import AppConfig, ConfigStore, PreferencesStore

load_dotenv()

st.set_page_config(page_title="Your Real Estate Agent", page_icon="🏡", layout="wide")

config_store = ConfigStore()
store = PreferencesStore(backend="json")
all_properties = load_properties()


# ---------------------------------------------------------------------------
# Onboarding – only shown on first run (before config.setup_complete is True)
# ---------------------------------------------------------------------------

def run_onboarding():
    """Full-screen setup wizard. Returns once the user submits."""
    st.markdown(
        """
        <style>
        .onboard-wrap { max-width: 560px; margin: 80px auto 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown("## Welcome to your personal real estate agent 🏡")
        st.write(
            "Let's spend 30 seconds setting things up so the experience feels personal "
            "right from the first message."
        )
        st.divider()

        with st.form("onboarding_form"):
            st.subheader("About the buyer")
            customer_name = st.text_input(
                "What's your name?",
                value="Sarah",
                help="The agent will use this throughout the conversation.",
            )

            st.subheader("About the agent")
            agent_name = st.text_input(
                "What would you like to call your agent?",
                value="Cassie",
                help="Give your agent a name that feels right.",
            )
            agent_gender = st.radio(
                "Agent pronouns",
                options=["She/Her", "He/Him", "They/Them"],
                horizontal=True,
                index=0,
            )

            st.divider()
            submitted = st.form_submit_button("Let's get started →", use_container_width=True)

        if submitted:
            if not customer_name.strip():
                st.error("Please enter your name.")
                st.stop()
            if not agent_name.strip():
                st.error("Please enter an agent name.")
                st.stop()

            cfg = AppConfig(
                agent_name=agent_name.strip(),
                customer_name=customer_name.strip(),
                setup_complete=True,
            )
            # Stash gender hint in extra_preferences via the store so agent can use it
            cfg_data = {"agent_pronouns": agent_gender}
            config_store.save(cfg)

            st.session_state.cfg = cfg
            st.session_state.agent_pronouns = agent_gender
            st.rerun()


# ---------------------------------------------------------------------------
# Load or gate on config
# ---------------------------------------------------------------------------

if "cfg" not in st.session_state:
    cfg = config_store.load()
    if not cfg.setup_complete:
        run_onboarding()
        st.stop()
    st.session_state.cfg = cfg

cfg: AppConfig = st.session_state.cfg

# Initialize the rest of session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "initialized" not in st.session_state:
    st.session_state.initialized = False


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(f"### 👤 {cfg.customer_name}'s Home Profile")
    st.caption(f"Agent: {cfg.agent_name}")

    prefs = store.get_preferences(cfg.customer_name)

    has_prefs = any([
        prefs.budget_max, prefs.target_cities, prefs.bedrooms_min,
        prefs.preferred_styles, prefs.deal_breakers,
        prefs.needs_home_office, prefs.needs_pool, prefs.needs_good_schools,
    ])

    if has_prefs:
        with st.expander("📋 Preferences", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                if prefs.budget_max:
                    st.metric("Max Budget", f"${prefs.budget_max:,.0f}")
                if prefs.bedrooms_min:
                    st.metric("Min Beds", prefs.bedrooms_min)
                if prefs.bathrooms_min:
                    st.metric("Min Baths", prefs.bathrooms_min)
            with col2:
                if prefs.sqft_min:
                    st.metric("Min Sqft", f"{prefs.sqft_min:,.0f}")

            if prefs.target_cities:
                st.write("**Locations:**", ", ".join(prefs.target_cities))
            if prefs.target_neighborhoods:
                st.write("**Neighborhoods:**", ", ".join(prefs.target_neighborhoods))
            if prefs.preferred_styles:
                st.write("**Styles:**", ", ".join(prefs.preferred_styles))
            if prefs.preferred_vibes:
                st.write("**Vibes:**", ", ".join(prefs.preferred_vibes))

            must_haves = [
                label for flag, label in [
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

    # Saved properties
    saved = store.get_saved_properties()
    liked = [s for s in saved if s.status == "liked"]
    if liked:
        with st.expander(f"❤️ Saved ({len(liked)})", expanded=False):
            for s in liked:
                for prop in all_properties:
                    if prop["external_id"] == s.external_id:
                        with st.container(border=True):
                            st.write(f"**{prop['address']}**")
                            st.write(
                                f"{prop['bedrooms']}bd / {prop['bathrooms']}ba "
                                f"· {prop['sqft']:,} sqft"
                            )
                            st.write(f"**${prop['price']:,.0f}**")
                            if s.agent_rationale:
                                st.caption(s.agent_rationale)
                        break

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 New chat", use_container_width=True, help="Keep preferences, clear chat"):
            st.session_state.messages = []
            st.session_state.initialized = False
            st.rerun()
    with col_b:
        if st.button("⚙️ Setup", use_container_width=True, help="Re-run onboarding"):
            cfg_obj = config_store.load()
            cfg_obj.setup_complete = False
            config_store.save(cfg_obj)
            for key in ["cfg", "messages", "initialized"]:
                st.session_state.pop(key, None)
            reset_conversation(keep_preferences=False)
            st.rerun()


# ---------------------------------------------------------------------------
# Chat area
# ---------------------------------------------------------------------------

st.subheader(f"Chat with {cfg.agent_name}", anchor=False)

# Display conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Auto-greet on first load
if not st.session_state.initialized:
    prefs = store.get_preferences(cfg.customer_name)
    is_returning = any([
        prefs.budget_max, prefs.target_cities, prefs.bedrooms_min,
        prefs.preferred_styles,
    ])

    if is_returning:
        greeting = (
            f"Welcome back, {cfg.customer_name}! I've got your preferences loaded. "
            "What would you like to explore today?"
        )
        st.session_state.messages.append({"role": "assistant", "content": greeting})
    else:
        with st.spinner(f"{cfg.agent_name} is getting ready…"):
            greeting = chat(
                f"Hello! My name is {cfg.customer_name}. Please introduce yourself as {cfg.agent_name} "
                f"and warmly kick off our first home-search conversation.",
                messages_history=[],
                customer_name=cfg.customer_name,
                agent_name=cfg.agent_name,
            )
        st.session_state.messages.append({"role": "assistant", "content": greeting})

    st.session_state.initialized = True
    st.rerun()

# Chat input
user_input = st.chat_input(f"Message {cfg.agent_name}…")
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.spinner(f"{cfg.agent_name} is thinking…"):
        # Exclude the message we just appended – it's passed as user_message
        messages_for_api = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
        ]
        response = chat(
            user_input,
            messages_history=messages_for_api,
            customer_name=cfg.customer_name,
            agent_name=cfg.agent_name,
        )

    st.session_state.messages.append({"role": "assistant", "content": response})
    with st.chat_message("assistant"):
        st.markdown(response)

"""Streamlit app for the real estate agent."""

import os

import streamlit as st
from dotenv import load_dotenv

from src.agent import chat, reset_conversation
from src.properties import load_properties, property_to_dict
from src.storage import PreferencesStore

load_dotenv()

st.set_page_config(page_title="Your Real Estate Agent", layout="wide")
st.title("🏡 Your Personal Real Estate Agent")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "customer_name" not in st.session_state:
    st.session_state.customer_name = os.getenv("CUSTOMER_NAME", "Sarah")
if "initialized" not in st.session_state:
    st.session_state.initialized = False

store = PreferencesStore(backend="json")
all_properties = load_properties()

# Sidebar
with st.sidebar:
    st.subheader("Your Home Profile")

    # Preferences tab
    prefs = store.get_preferences(st.session_state.customer_name)

    if any([
        prefs.budget_max, prefs.target_cities, prefs.bedrooms_min,
        prefs.preferred_styles, prefs.deal_breakers
    ]):
        with st.expander("📋 Current Preferences", expanded=True):
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
            if prefs.preferred_styles:
                st.write("**Styles:**", ", ".join(prefs.preferred_styles))
            if prefs.deal_breakers:
                st.write("**Deal-breakers:**", ", ".join(prefs.deal_breakers))
            if prefs.needs_home_office:
                st.write("✓ Needs home office")
            if prefs.needs_pool:
                st.write("✓ Needs pool")
            if prefs.needs_good_schools:
                st.write("✓ Needs good schools")
            if prefs.needs_single_story:
                st.write("✓ Single story")
    else:
        st.info("👉 Start chatting to build your profile!")

    # Saved properties
    saved = store.get_saved_properties()
    if saved:
        with st.expander(f"❤️ Saved Properties ({len(saved)})", expanded=False):
            for s in saved:
                for prop in all_properties:
                    if prop["external_id"] == s.external_id:
                        with st.container(border=True):
                            st.write(f"**{prop['address']}**")
                            st.write(f"{prop['bedrooms']}bd/{prop['bathrooms']}ba • {prop['sqft']:,} sqft")
                            st.write(f"${prop['price']:,.0f}")
                            st.caption(f"Status: {s.status.upper()}")
                        break

    # Reset button
    if st.button("🔄 Start Over", use_container_width=True):
        reset_conversation(keep_preferences=False)
        st.session_state.messages = []
        st.rerun()

# Main chat area
st.subheader(f"Chat with Cassie 🏡", anchor=False)

# Display conversation
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Auto-greet on first load
if not st.session_state.initialized:
    # Check if there are any preferences
    prefs = store.get_preferences(st.session_state.customer_name)
    if not any([
        prefs.budget_max, prefs.target_cities, prefs.bedrooms_min,
        prefs.preferred_styles
    ]):
        # First time – greet
        with st.spinner("Cassie is thinking..."):
            greeting = chat(
                "Hello! Please greet me warmly and start our first conversation about finding my dream home.",
                messages_history=[],
                customer_name=st.session_state.customer_name,
            )
        st.session_state.messages.append({"role": "assistant", "content": greeting})
    else:
        # Returning user
        greeting = "Welcome back! Your preferences are loaded. What would you like to explore today?"
        st.session_state.messages.append({"role": "assistant", "content": greeting})

    st.session_state.initialized = True
    st.rerun()

# Chat input
user_input = st.chat_input("Tell me what you're looking for…")
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Get response
    with st.spinner("Cassie is thinking..."):
        messages_for_api = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]  # exclude the latest user message
        ]
        response = chat(
            user_input,
            messages_history=messages_for_api,
            customer_name=st.session_state.customer_name,
        )

    st.session_state.messages.append({"role": "assistant", "content": response})
    with st.chat_message("assistant"):
        st.markdown(response)

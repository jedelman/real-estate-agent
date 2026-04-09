"""FastAPI web server for the real estate agent."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from .agent import chat, reset_conversation
from .database import Preferences, Property, SavedProperty, get_session, init_db
from .properties import property_to_dict, seed_sample_data

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Real Estate Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup():
    init_db()
    with get_session() as session:
        seed_sample_data(session)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    customer_name: str | None = None


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")
    try:
        reply = chat(req.message, req.customer_name)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@app.get("/api/preferences")
def api_get_preferences():
    with get_session() as session:
        prefs = session.query(Preferences).first()
        if not prefs:
            return {}
        return {
            "customer_name": prefs.customer_name,
            "budget_min": prefs.budget_min,
            "budget_max": prefs.budget_max,
            "target_cities": prefs.target_cities or [],
            "target_neighborhoods": prefs.target_neighborhoods or [],
            "bedrooms_min": prefs.bedrooms_min,
            "bathrooms_min": prefs.bathrooms_min,
            "sqft_min": prefs.sqft_min,
            "preferred_styles": prefs.preferred_styles or [],
            "preferred_vibes": prefs.preferred_vibes or [],
            "needs_home_office": prefs.needs_home_office,
            "needs_pool": prefs.needs_pool,
            "needs_good_schools": prefs.needs_good_schools,
            "needs_single_story": prefs.needs_single_story,
            "needs_open_floor_plan": prefs.needs_open_floor_plan,
            "needs_walkability": prefs.needs_walkability,
            "deal_breakers": prefs.deal_breakers or [],
            "extra_preferences": prefs.extra_preferences or {},
            "raw_notes": prefs.raw_notes,
        }


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@app.get("/api/properties")
def api_get_properties():
    with get_session() as session:
        seed_sample_data(session)
        props = session.query(Property).filter_by(status="active").all()
        return [property_to_dict(p) for p in props]


@app.get("/api/saved")
def api_get_saved():
    with get_session() as session:
        saved = session.query(SavedProperty).all()
        results = []
        for s in saved:
            prop = session.query(Property).filter_by(id=s.property_id).first()
            if prop:
                d = property_to_dict(prop)
                d["saved_status"] = s.status
                d["saved_notes"] = s.notes
                d["agent_rationale"] = s.agent_rationale
                results.append(d)
        return results


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class ResetRequest(BaseModel):
    keep_preferences: bool = False


@app.post("/api/reset")
def api_reset(req: ResetRequest):
    return reset_conversation(keep_preferences=req.keep_preferences)


# ---------------------------------------------------------------------------
# Serve the SPA
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")

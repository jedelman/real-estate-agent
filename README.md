# Your Personal Real Estate Agent 🏡

An agentic real estate buying experience powered by Claude Haiku, built with Streamlit.

## The Vision

Instead of scrolling through static listings, you have a real estate agent who:
- **Learns your preferences** through natural conversation (not forms)
- **Remembers everything** you say across sessions
- **Proactively recommends** properties that match your evolving taste
- **Explains the match** in personal terms, connecting each property to what *you* specifically want

The agent uses Claude's tool_use to dynamically search, save, and score listings in real-time, all while building a rich understanding of your ideal home.

## Quick Start

### Prerequisites
- Python 3.9+
- Anthropic API key (get one at https://console.anthropic.com/)

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
# Optionally set CUSTOMER_NAME (default: "Sarah")

# Run the app
streamlit run app.py
```

The app will open at `http://localhost:8501`. Start chatting!

## Architecture

### Core Files

**`app.py`** — Streamlit frontend
- Chat interface with real-time message history
- Live preference sidebar (updates as you chat)
- Saved properties tab
- Clean, responsive single-column layout

**`src/agent.py`** — Claude-powered agent loop
- 7 tools: search, update/get preferences, save property, proactive recommendations, etc.
- Agentic loop: Claude calls tools, processes results, responds
- Conversation is stateless (history passed in)
- System prompt guides warm, perceptive, non-salesy tone

**`src/storage.py`** — Preference & property storage
- Simple `PreferencesStore` dataclass
- JSON backend by default (`data/preferences.json`, `data/saved.json`)
- **Drop-in swappable** for D1, Supabase, or any backend
- Merges preference updates (never overwrites; accumulates)

**`src/properties.py`** — Property search
- 12 realistic Austin-area sample listings (pre-loaded)
- `SearchCriteria` dataclass + `search_properties()` function
- Simple dict-based (no ORM)
- Easy to add real data sources (Zillow API, MLS, etc.)

## How Preferences Work

The agent learns and stores:

### Hard Requirements
- Budget (min/max)
- Location (cities, neighborhoods, zip codes, max commute)
- Size (beds, baths, sqft)
- Style (modern, craftsman, ranch, farmhouse, etc.)
- Garage spaces, lot size

### Soft Preferences
- Vibes (cozy, bright, grand, private, walkable)
- Must-haves (home office, pool, good schools, open floor plan, single story, etc.)
- Deal-breakers (HOA, highway noise, small kitchen, etc.)
- Free-form notes (captured from conversation)

### How It Works

1. **Silent learning** — Agent extracts preferences from every message
   - "We work from home" → `needs_home_office=true`
   - "South Austin is special to us" → `target_neighborhoods=["South Austin"]`
   - "Would never deal with HOA" → `deal_breakers=["HOA"]`

2. **Accumulation** — Preferences merge, never reset
   - Say "Austin or Round Rock" on day 1, "Also love Lakeway" on day 2?
   - You now have all three in `target_cities`

3. **Proactive matching** — Agent scores all listings against your profile
   - Bedrooms, budget, style, must-haves, deal-breakers, neighborhoods
   - Surfaces top 3 matches with personalized rationales
   - Triggered after preference updates or on demand

## Preference Scoring

When the agent runs `proactive_recommendations`, it scores each listing:

- **Must-haves**: +8 to +15 points each
- **Deal-breakers**: -25 to -20 points each
- **Budget**: +10 if well within range, -30 if over
- **Neighborhood match**: +15 points
- **Style match**: +12 points
- **Size & other features**: ±5 points each

Final score: 0–100. Top matches are recommended.

## Using D1 (Cloudflare)

The storage layer is designed to swap D1 in easily.

### Local Development (Current)
Uses JSON files in `data/` directory. Perfect for testing.

### Production with D1

1. Set up Cloudflare D1 database:
   ```bash
   npm install -g @cloudflare/wrangler
   wrangler d1 create real-estate-agent
   ```

2. Create schema in D1:
   ```sql
   CREATE TABLE IF NOT EXISTS preferences (
     id INTEGER PRIMARY KEY,
     customer_name TEXT,
     budget_max REAL,
     budget_min REAL,
     target_cities JSON,
     ... (see storage.py Preferences dataclass for full schema)
   );
   ```

3. Update `src/storage.py`:
   ```python
   _store = PreferencesStore(backend="d1", d1_token=os.getenv("D1_TOKEN"))
   ```

4. Implement D1 REST API calls in `PreferencesStore` for the `d1` backend

Alternatively, use **Supabase**, **Firebase**, or **any SQL DB** — just implement the backend.

## Chat Examples

**First message:**
> "Hi! I'm looking for a home in Austin. We both work from home and want something with good bones, maybe modern or craftsman. Budget is under a million."

**Agent response:**
> "What a journey! I'm Cassie, your personal real estate agent. I love that you're looking for a space where you can both thrive. Modern and craftsman have such different vibes—can you tell me a bit more about which feels more 'you'? And when you say good bones, are you thinking new construction or older homes with character?"

**Later:**
> "Actually, we'd love a pool too. And we're open to Round Rock or Cedar Park if the right place comes along."

**Agent response:**
> "Pool + work-from-home space + open to growing outward! I've got three properties that just came into focus. Check these out..." [Proactive recommendations with match scores]

## Tech Stack

- **UI**: Streamlit (simple, fast, zero JavaScript)
- **Agent**: Claude Haiku 4.5 (fast, cheap, capable)
- **Storage**: JSON (local) / D1 (production)
- **Language**: Python 3.9+

## Limitations & Next Steps

- **Properties**: Currently 12 sample Austin-area listings. To add real data:
  - Integrate Zillow API (via RapidAPI or unofficial endpoint)
  - Integrate Redfin or Realtor.com
  - Build MLS scraper
  
- **Geography**: All samples are Austin/Hill Country. Trivial to expand.

- **Persistence**: JSON files work great locally. For production, swap in D1 or Supabase.

- **Multi-user**: App is single-user (session per person). To handle multiple buyers:
  - Add login / user ID
  - Namespace storage by user_id
  - Pass customer_name dynamically

## Development

### Adding a Real Property Source

In `src/properties.py`, add a new function:

```python
async def fetch_zillow_properties(criteria: SearchCriteria) -> list[dict]:
    """Fetch from Zillow RapidAPI."""
    # ... call Zillow API, return dicts matching SAMPLE_LISTINGS schema
    pass
```

Then update `load_properties()` to call it.

### Customizing the Agent

Edit `src/agent.py`:
- System prompt (in `_build_system_prompt`)
- Tool definitions (in `TOOLS`)
- Scoring logic (in `_score_property_dict`)
- Max tokens, model version, etc.

### Styling the Streamlit UI

Streamlit's default look is clean. For custom CSS, use:
```python
st.markdown("""
    <style>
        /* Custom CSS here */
    </style>
""", unsafe_allow_html=True)
```

## Deployment

### Streamlit Cloud (Easiest)

1. Push to GitHub
2. Go to https://streamlit.io/cloud
3. Deploy from repo
4. Add `ANTHROPIC_API_KEY` as secret in Settings
5. Done

### Docker

```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### Cloudflare Workers (with D1)

Deploy the Streamlit app as a Worker, backed by D1 for preferences and listings.

## Credits

Built with ❤️ using Claude Haiku, Streamlit, and a dash of real estate magic.

---

**Questions?** Check the code—it's well-commented. Or ask the agent directly; she's pretty smart. 🏡

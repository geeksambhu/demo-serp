# Jetpot

## What is Jetpot?

Jetpot is a Streamlit travel planner for quick trip research. Enter an origin airport, a budget, and either a destination or an explore-style search, then review real SerpApi-powered flight ideas or complete trip bundles ranked for value.

This is built for a SerpApi PyCon raffle challenge and tuned for a short live demo:

- useful enough to answer "Where can I fly cheaply this weekend?"
- fast to explain in under a minute
- transparent about the underlying source data

## Why SerpApi?

SerpApi provides structured access to public flight, hotel, and destination data, which makes it practical to build a travel research layer without scraping HTML or pretending to be a booking site. This app uses the official SerpApi Python SDK (`pip install serpapi`) and keeps the API key in an environment variable.

## Features

- Search from an origin airport with a specific destination or an explore mode
- Pull live flight data from SerpApi using `google_flights` or `google_travel_explore`
- Rank results by price, duration, stops, and budget-aware deal quality
- Highlight best value, cheapest, and fastest options
- Show top ranked flight cards for demo-friendly scanning
- Support cache-first demos with preset phrases and saved JSON responses in `demo_cache/`
- Support cache-first complete trip bundles in `trip_cache/` for DFW to SFO, Denver, and Hawaii
- Include a raw response expander for debugging and transparency
- Never expose the SerpApi key in the UI

## Setup with uv

```bash
uv venv
source .venv/bin/activate
uv sync
cp .env.example .env
# add SERPAPI_KEY=your_serpapi_key_here
uv run streamlit run app.py
```

To prewarm the demo cache with the bundled preset phrases:

```bash
uv run python scripts/capture_demo_cache.py
```

To prewarm the complete-trip cache for the bundled DFW prompts:

```bash
uv run python scripts/capture_trip_cache.py
```

## Environment variables

Required:

- `SERPAPI_KEY`: your SerpApi API key

Local development uses `python-dotenv`, so a `.env` file works automatically. On Streamlit Community Cloud, add `SERPAPI_KEY` in the app Secrets settings. The app reads the environment variable first and falls back to `st.secrets` for Community Cloud deployment.

Example `.env`:

```env
SERPAPI_KEY=your_serpapi_key_here
```

## Example searches

- Origin `AUS`, destination `LAX`, 3-day trip, budget `$350`
- Origin `JFK`, destination `SFO`, 4-day trip, budget `$500`
- Origin `DFW`, explore mode, long weekend, budget `$250`
- Origin `LGB`, explore mode, short trip, budget `$200`

Demo prompt presets included in [`demo_presets.json`](/Users/shiva/Developer/serpapi/demo_presets.json):

- "Where can I fly cheaply this weekend from Austin?"
- "Show me a 3-day Los Angeles trip from Austin under $350"
- "What are good 3-day trips from Dallas under $300?"
- "Find a cheap New York weekend from Los Angeles under $400"
- "Give me a quick getaway from Long Beach under $200"
- "Which San Francisco flight from JFK is the best value for a long weekend?"

To conserve the 250-search monthly free tier, run each demo prompt once with live data and keep the captured JSON files under `demo_cache/` for replay.

Complete trip prompts included in [`trip_prompts.json`](/Users/shiva/Developer/serpapi/trip_prompts.json):

- "Plan me a trip under $1000 from DFW to SFO"
- "Plan me a trip under $1000 from DFW to Denver"
- "Plan me a trip under $1000 from DFW to Hawaii"

## How deal scoring works

Each itinerary starts at `100` points:

- subtract `price / 10`
- subtract `duration_minutes / 60`
- subtract `15` points per stop
- add `10` points if price is within the user budget
- clamp the final score between `0` and `100`

This favors cheap, short, nonstop trips without pretending the score is a booking recommendation.

## Deployment note

For Streamlit Cloud compatibility, keep `requirements.txt` in sync:

```bash
uv pip compile pyproject.toml -o requirements.txt
```

Streamlit Community Cloud checklist:

- keep `app.py` at the repo root
- commit `requirements.txt`
- commit `runtime.txt` to pin a supported Python version
- add `SERPAPI_KEY` in the deployed app Secrets panel
- deploy the repo and use `app.py` as the entrypoint

GitHub Actions included in this repo:

- [`.github/workflows/ci.yml`](/Users/shiva/Developer/serpapi/.github/workflows/ci.yml) validates the app on pull requests and pushes to `main`
- [`.github/workflows/comment-streamlit-link.yml`](/Users/shiva/Developer/serpapi/.github/workflows/comment-streamlit-link.yml) comments the Streamlit app URL on a PR after CI passes

To enable the PR comment link, add a repository variable named `STREAMLIT_APP_URL` with your deployed app URL, for example `https://your-app-name.streamlit.app`.

## PyCon raffle note

This project is intentionally scoped to feel polished in a live demo while staying simple enough to build quickly. It focuses on travel inspiration and comparison, not checkout or booking flows.

## Disclaimer

- This is not a booking site.
- This app does not sell tickets.
- It summarizes public flight search data from SerpApi.
- Flight data may change. Always verify prices before booking.

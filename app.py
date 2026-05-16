import hashlib
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import serpapi
import streamlit as st
from dotenv import load_dotenv


load_dotenv()

REQUEST_TIMEOUT_SECONDS = 20
APP_DIR = Path(__file__).parent
CACHE_DIR = APP_DIR / "demo_cache"
PRESET_FILE = APP_DIR / "demo_presets.json"
TRIP_CACHE_DIR = APP_DIR / "trip_cache"
TRIP_PROMPTS_FILE = APP_DIR / "trip_prompts.json"
CACHE_DIR.mkdir(exist_ok=True)
TRIP_CACHE_DIR.mkdir(exist_ok=True)


def get_api_key() -> str | None:
    if env_value := os.getenv("SERPAPI_KEY"):
        return env_value

    try:
        secret_value = st.secrets.get("SERPAPI_KEY")
    except Exception:
        secret_value = None

    return secret_value


def load_demo_presets() -> list[dict[str, Any]]:
    if not PRESET_FILE.exists():
        return []

    try:
        payload = json.loads(PRESET_FILE.read_text())
    except json.JSONDecodeError:
        return []

    return [item for item in payload if isinstance(item, dict)]


def load_trip_prompts() -> list[dict[str, Any]]:
    if not TRIP_PROMPTS_FILE.exists():
        return []

    try:
        payload = json.loads(TRIP_PROMPTS_FILE.read_text())
    except json.JSONDecodeError:
        return []

    return [item for item in payload if isinstance(item, dict)]


def resolve_preset_dates(preset: dict[str, Any]) -> tuple[date, date]:
    departure_offset = int(preset.get("departure_offset_days", 14))
    trip_length = int(preset.get("trip_length_days", 3))
    departure_date = date.today() + timedelta(days=departure_offset)
    return departure_date, departure_date + timedelta(days=trip_length)


def apply_demo_preset(preset: dict[str, Any]) -> None:
    departure_offset = int(preset.get("departure_offset_days", 14))
    trip_length = int(preset.get("trip_length_days", 3))
    departure_date, return_date = resolve_preset_dates(preset)
    st.session_state["origin_input"] = preset.get("origin", "AUS")
    st.session_state["trip_mode_input"] = preset.get("trip_mode", "Specific destination")
    st.session_state["destination_input"] = preset.get("destination", "")
    st.session_state["depart_in_days_input"] = departure_offset
    st.session_state["trip_length_days_input"] = trip_length
    st.session_state["departure_input"] = departure_date
    st.session_state["return_input"] = return_date
    st.session_state["budget_input"] = int(preset.get("budget", 350))


def apply_trip_prompt(prompt: dict[str, Any]) -> None:
    departure_offset = int(prompt.get("departure_offset_days", 21))
    trip_length = int(prompt.get("trip_length_days", 3))
    departure_date, return_date = resolve_preset_dates(prompt)
    st.session_state["origin_input"] = prompt.get("origin", "DFW")
    st.session_state["trip_mode_input"] = "Specific destination"
    st.session_state["destination_input"] = prompt.get("destination", "")
    st.session_state["destination_name_input"] = prompt.get("destination_name", prompt.get("destination", ""))
    st.session_state["hotel_query_input"] = prompt.get("hotel_query", "")
    st.session_state["depart_in_days_input"] = departure_offset
    st.session_state["trip_length_days_input"] = trip_length
    st.session_state["departure_input"] = departure_date
    st.session_state["return_input"] = return_date
    st.session_state["budget_input"] = int(prompt.get("budget", 1000))


def build_search_phrase(origin: str, trip_mode: str, destination: str, budget: float) -> str:
    if trip_mode == "Specific destination":
        return f"Find a best-value trip from {origin} to {destination} under ${int(budget)}"
    return f"Where can I fly cheaply from {origin} under ${int(budget)}?"


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return cleaned.strip("_") or "trip"


def build_active_trip_prompt(
    origin: str,
    destination: str,
    destination_name: str,
    hotel_query: str,
    depart_in_days: int,
    trip_length_days: int,
    budget: float,
) -> dict[str, Any]:
    destination_label = destination_name.strip() or destination
    hotel_label = hotel_query.strip() or f"{destination_label} hotels"
    prompt_id_seed = f"{origin}-{destination}-{destination_label}-{depart_in_days}-{trip_length_days}-{int(budget)}"
    prompt_hash = hashlib.sha1(prompt_id_seed.encode("utf-8")).hexdigest()[:8]
    return {
        "id": f"{slugify(origin)}_{slugify(destination_label)}_{prompt_hash}",
        "phrase": f"Plan me a trip under ${int(budget)} from {origin} to {destination_label}",
        "origin": origin,
        "destination": destination,
        "destination_name": destination_label,
        "hotel_query": hotel_label,
        "departure_offset_days": depart_in_days,
        "trip_length_days": trip_length_days,
        "budget": int(budget),
    }


def build_search_params(origin: str, trip_mode: str, destination: str, departure_date: date, return_date: date) -> dict[str, Any]:
    params: dict[str, Any] = {
        "engine": "google_flights" if trip_mode == "Specific destination" else "google_travel_explore",
        "departure_id": origin,
        "outbound_date": departure_date.isoformat(),
        "return_date": return_date.isoformat(),
        "currency": "USD",
        "hl": "en",
    }
    if trip_mode == "Specific destination":
        params["arrival_id"] = destination
    return params


def build_hotels_params(destination_query: str, departure_date: date, return_date: date) -> dict[str, Any]:
    return {
        "engine": "google_hotels",
        "q": destination_query,
        "check_in_date": departure_date.isoformat(),
        "check_out_date": return_date.isoformat(),
        "adults": 2,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
    }


def build_sights_params(destination_query: str) -> dict[str, Any]:
    return {
        "engine": "google",
        "q": f"top sights in {destination_query}",
        "hl": "en",
        "gl": "us",
    }


def cache_stem_for_params(params: dict[str, Any]) -> str:
    engine = str(params.get("engine", "search")).lower()
    origin = str(params.get("departure_id", "origin")).lower()
    destination = str(params.get("arrival_id", "explore")).lower()
    outbound = str(params.get("outbound_date", "outbound"))
    inbound = str(params.get("return_date", "return"))
    signature = json.dumps(params, sort_keys=True)
    short_hash = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:8]
    return f"{engine}_{origin}_{destination}_{outbound}_{inbound}_{short_hash}"


def cache_path_for_params(params: dict[str, Any]) -> Path:
    return CACHE_DIR / f"{cache_stem_for_params(params)}.json"


def trip_cache_path(prompt: dict[str, Any]) -> Path:
    departure_date, return_date = resolve_preset_dates(prompt)
    prompt_id = str(prompt.get("id", "trip")).lower().replace(" ", "_")
    return TRIP_CACHE_DIR / f"{prompt_id}_{departure_date.isoformat()}_{return_date.isoformat()}.json"


def save_demo_cache(
    cache_path: Path,
    search_phrase: str,
    search_params: dict[str, Any],
    trip_mode: str,
    budget: float,
    raw_response: dict[str, Any],
) -> None:
    payload = {
        "cache_version": 1,
        "captured_at": date.today().isoformat(),
        "search_phrase": search_phrase,
        "trip_mode": trip_mode,
        "budget": int(budget),
        "search_params": search_params,
        "raw_response": raw_response,
    }
    cache_path.write_text(json.dumps(payload, indent=2))


def load_demo_cache(cache_path: Path) -> dict[str, Any]:
    return json.loads(cache_path.read_text())


def list_cache_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for cache_file in sorted(CACHE_DIR.glob("*.json")):
        try:
            payload = load_demo_cache(cache_file)
        except (OSError, json.JSONDecodeError):
            continue

        search_params = payload.get("search_params", {})
        entries.append(
            {
                "path": cache_file,
                "label": payload.get("search_phrase") or cache_file.stem,
                "captured_at": payload.get("captured_at", "unknown"),
                "engine": search_params.get("engine", "unknown"),
                "origin": search_params.get("departure_id", "N/A"),
                "destination": search_params.get("arrival_id", "Explore"),
            }
        )
    return entries


def list_trip_cache_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for cache_file in sorted(TRIP_CACHE_DIR.glob("*.json")):
        try:
            payload = load_trip_cache(cache_file)
        except (OSError, json.JSONDecodeError):
            continue
        prompt = payload.get("prompt", {})
        entries.append(
            {
                "path": cache_file,
                "label": prompt.get("phrase") or cache_file.stem,
                "captured_at": payload.get("captured_at", "unknown"),
                "origin": prompt.get("origin", "N/A"),
                "destination": prompt.get("destination_name") or prompt.get("destination", "N/A"),
            }
        )
    return entries


def clamp_positive_days(value: int) -> int:
    return max(1, value)


def days_until(target_date: date) -> int:
    return clamp_positive_days((target_date - date.today()).days)


AIRPORT_LABELS = {
    "AUS": "Austin",
    "DEN": "Denver",
    "DFW": "Dallas-Fort Worth",
    "HNL": "Honolulu",
    "JFK": "New York",
    "LAX": "Los Angeles",
    "LGB": "Long Beach",
    "SEA": "Seattle",
    "SFO": "San Francisco",
}


def airport_label(code: str) -> str:
    normalized = normalize_airport_code(code)
    return AIRPORT_LABELS.get(normalized, normalized)


def apply_demo_cache_payload(payload: dict[str, Any]) -> None:
    search_params = payload.get("search_params", {})
    trip_mode = str(payload.get("trip_mode", "Specific destination"))
    origin = str(search_params.get("departure_id", "")).upper()
    destination = str(search_params.get("arrival_id", "")).upper()
    outbound_raw = search_params.get("outbound_date")
    return_raw = search_params.get("return_date")

    st.session_state["origin_input"] = origin
    st.session_state["trip_mode_input"] = trip_mode
    st.session_state["destination_input"] = destination
    derived_destination_name = airport_label(destination) if destination else st.session_state.get("destination_name_input", "")
    st.session_state["destination_name_input"] = derived_destination_name
    if destination:
        st.session_state["hotel_query_input"] = f"{derived_destination_name} hotels"

    if outbound_raw and return_raw:
        outbound_date = date.fromisoformat(str(outbound_raw))
        return_date = date.fromisoformat(str(return_raw))
        st.session_state["depart_in_days_input"] = days_until(outbound_date)
        st.session_state["trip_length_days_input"] = clamp_positive_days((return_date - outbound_date).days)

    if budget := payload.get("budget"):
        st.session_state["budget_input"] = int(budget)


def apply_trip_cache_payload(payload: dict[str, Any]) -> None:
    prompt = payload.get("prompt", {})
    if not isinstance(prompt, dict):
        return
    destination_name = str(prompt.get("destination_name", "")).strip() or airport_label(str(prompt.get("destination", "")))
    hotel_query = str(prompt.get("hotel_query", "")).strip()
    if not hotel_query or destination_name.lower() not in hotel_query.lower():
        hotel_query = f"{destination_name} hotels"

    normalized_prompt = {
        **prompt,
        "destination_name": destination_name,
        "hotel_query": hotel_query,
    }
    apply_trip_prompt(normalized_prompt)


def save_trip_cache(cache_path: Path, prompt: dict[str, Any], bundle: dict[str, Any]) -> None:
    payload = {
        "cache_version": 1,
        "captured_at": date.today().isoformat(),
        "prompt": prompt,
        "bundle": bundle,
    }
    cache_path.write_text(json.dumps(payload, indent=2))


def load_trip_cache(cache_path: Path) -> dict[str, Any]:
    return json.loads(cache_path.read_text())


def normalize_airport_code(value: str) -> str:
    return value.strip().upper()


def is_valid_airport_code(value: str) -> bool:
    return len(value) == 3 and value.isalpha()


def parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch == ".")
    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def format_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.0f}"


def parse_duration_to_minutes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).lower()
    hours_match = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)", text)
    minutes_match = re.search(r"(\d+)\s*(?:m|min|mins|minute|minutes)", text)
    if hours_match or minutes_match:
        hours = int(hours_match.group(1)) if hours_match else 0
        minutes = int(minutes_match.group(1)) if minutes_match else 0
        return (hours * 60) + minutes

    digits = re.findall(r"\d+", text)
    if not digits:
        return None

    if len(digits) == 1:
        return int(digits[0])

    try:
        return int(float(value))
    except ValueError:
        return None


def format_duration(minutes: int | None) -> str:
    if minutes is None:
        return "N/A"
    hours, mins = divmod(minutes, 60)
    if hours == 0:
        return f"{mins}m"
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def calculate_deal_score(price: float | None, duration_minutes: int | None, stops: int | None, budget: float) -> int:
    score = 100.0
    if price is not None:
        score -= price / 10
        if price <= budget:
            score += 10
    if duration_minutes is not None:
        score -= duration_minutes / 60
    if stops is not None:
        score -= stops * 15
    return max(0, min(100, round(score)))


def safe_get(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_present(mapping: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def parse_google_flights_result(item: dict[str, Any], source_bucket: str, budget: float) -> dict[str, Any]:
    segments = item.get("flights") or item.get("segments") or []
    first_segment = segments[0] if segments else {}
    last_segment = segments[-1] if segments else {}

    airlines = [segment.get("airline") for segment in segments if segment.get("airline")]
    airline = " / ".join(dict.fromkeys(airlines)) if airlines else item.get("airline") or "Unknown airline"

    departure_airport = safe_get(first_segment, "departure_airport", "id") or safe_get(first_segment, "departure_airport", "name")
    arrival_airport = safe_get(last_segment, "arrival_airport", "id") or safe_get(last_segment, "arrival_airport", "name")
    departure_time = safe_get(first_segment, "departure_airport", "time") or item.get("departure_time")
    arrival_time = safe_get(last_segment, "arrival_airport", "time") or item.get("arrival_time")

    layovers = item.get("layovers")
    stops = len(layovers) if isinstance(layovers, list) else max(0, len(segments) - 1) if segments else None

    duration_minutes = parse_duration_to_minutes(item.get("total_duration"))
    if duration_minutes is None:
        duration_minutes = sum(
            segment_duration
            for segment in segments
            if (segment_duration := parse_duration_to_minutes(segment.get("duration"))) is not None
        ) or None

    price_value = parse_price(item.get("price"))
    travel_class = item.get("travel_class") or item.get("type") or "N/A"
    deal_score = calculate_deal_score(price_value, duration_minutes, stops, budget)

    return {
        "source_bucket": source_bucket,
        "price": price_value,
        "price_display": item.get("price") if isinstance(item.get("price"), str) else format_price(price_value),
        "duration_minutes": duration_minutes,
        "duration_display": format_duration(duration_minutes),
        "airline": airline,
        "departure_airport": departure_airport or "N/A",
        "arrival_airport": arrival_airport or "N/A",
        "departure_time": departure_time or "N/A",
        "arrival_time": arrival_time or "N/A",
        "stops": stops,
        "stops_display": "N/A" if stops is None else "Nonstop" if stops == 0 else f"{stops} stop" if stops == 1 else f"{stops} stops",
        "travel_class": travel_class,
        "deal_score": deal_score,
        "is_actionable": bool(price_value is not None and duration_minutes is not None),
        "under_budget": bool(price_value is not None and price_value <= budget),
        "note": "Verify before booking.",
    }


def parse_google_flights_response(payload: dict[str, Any], budget: float) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for bucket in ("best_flights", "other_flights"):
        for item in payload.get(bucket, []) or []:
            if isinstance(item, dict):
                results.append(parse_google_flights_result(item, bucket, budget))
    return results


def parse_explore_destination(item: dict[str, Any], origin: str, budget: float) -> dict[str, Any]:
    destination_code = (
        safe_get(item, "destination_airport", "code")
        or first_present(item, ["arrival_id", "destination_id", "airport_code", "iata_code"])
    )
    destination_name = first_present(item, ["destination", "city", "title", "name"], default=destination_code or "Unknown destination")

    price_value = parse_price(first_present(item, ["price", "flight_price", "best_price", "lowest_price"]))
    duration_minutes = parse_duration_to_minutes(first_present(item, ["duration", "total_duration", "flight_duration"]))
    stops = first_present(item, ["stops", "stop_count", "number_of_stops"])
    if isinstance(stops, str) and stops.isdigit():
        stops = int(stops)
    if not isinstance(stops, int):
        stops = None

    airline = first_present(item, ["airline", "airlines", "carrier"], default="Various airlines")
    if isinstance(airline, list):
        airline = " / ".join(str(entry) for entry in airline[:3])

    departure_time = first_present(item, ["departure_time", "outbound_departure_time"], default="Flexible")
    arrival_time = first_present(item, ["arrival_time", "outbound_arrival_time"], default="Flexible")
    travel_class = first_present(item, ["travel_class", "class"], default="N/A")

    deal_score = calculate_deal_score(price_value, duration_minutes, stops, budget)

    return {
        "source_bucket": "explore_results",
        "price": price_value,
        "price_display": format_price(price_value),
        "duration_minutes": duration_minutes,
        "duration_display": format_duration(duration_minutes),
        "airline": str(airline),
        "departure_airport": origin,
        "arrival_airport": destination_code or str(destination_name),
        "departure_time": str(departure_time),
        "arrival_time": str(arrival_time),
        "stops": stops,
        "stops_display": "N/A" if stops is None else "Nonstop" if stops == 0 else f"{stops} stop" if stops == 1 else f"{stops} stops",
        "travel_class": str(travel_class),
        "deal_score": deal_score,
        "is_actionable": bool(price_value is not None and duration_minutes is not None),
        "under_budget": bool(price_value is not None and price_value <= budget),
        "destination_label": str(destination_name),
        "note": "Verify before booking.",
    }


def parse_google_travel_explore_response(payload: dict[str, Any], origin: str, budget: float) -> list[dict[str, Any]]:
    candidates = []
    for key in ("destinations", "explore_flights_results", "flights_results", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))

    return [parse_explore_destination(item, origin, budget) for item in candidates]


def parse_hotels_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hotels: list[dict[str, Any]] = []
    for item in payload.get("properties", []) or []:
        if not isinstance(item, dict):
            continue

        total_price = (
            parse_price(safe_get(item, "total_rate", "extracted_lowest"))
            or parse_price(safe_get(item, "total_rate", "lowest"))
            or parse_price(safe_get(item, "rate_per_night", "extracted_lowest"))
            or parse_price(safe_get(item, "rate_per_night", "lowest"))
        )
        nightly_price = (
            parse_price(safe_get(item, "rate_per_night", "extracted_lowest"))
            or parse_price(safe_get(item, "rate_per_night", "lowest"))
        )
        transport_note = "N/A"
        nearby_place = safe_get(item, "nearby_places")
        if isinstance(nearby_place, list) and nearby_place:
            first_place = nearby_place[0]
            if isinstance(first_place, dict):
                place_name = first_place.get("name", "Nearby")
                transportations = first_place.get("transportations") or []
                if transportations and isinstance(transportations[0], dict):
                    mode = transportations[0].get("type", "Transit")
                    duration = transportations[0].get("duration", "")
                    transport_note = f"{place_name} · {mode} {duration}".strip()
                else:
                    transport_note = str(place_name)

        amenities = item.get("amenities") if isinstance(item.get("amenities"), list) else []
        hotels.append(
            {
                "name": item.get("name", "Unknown hotel"),
                "description": item.get("description", "No description available."),
                "total_price": total_price,
                "total_price_display": format_price(total_price),
                "nightly_price": nightly_price,
                "nightly_price_display": format_price(nightly_price),
                "overall_rating": item.get("overall_rating"),
                "reviews": item.get("reviews"),
                "hotel_class": item.get("hotel_class") or "N/A",
                "amenities": amenities[:4],
                "transport_note": transport_note,
                "deal": item.get("deal") or item.get("deal_description"),
                "link": item.get("link") or item.get("serpapi_property_details_link"),
            }
        )
    return hotels


def parse_sights_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    top_sights = payload.get("top_sights") or {}
    sights: list[dict[str, Any]] = []
    for item in top_sights.get("sights", []) or []:
        if not isinstance(item, dict):
            continue
        sights.append(
            {
                "title": item.get("title", "Unknown sight"),
                "description": item.get("description", "No description available."),
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "price": item.get("price"),
                "link": item.get("link"),
            }
        )

    if sights:
        return sights

    for item in payload.get("local_results", []) or []:
        if not isinstance(item, dict):
            continue
        sights.append(
            {
                "title": item.get("title", "Unknown sight"),
                "description": item.get("description", "No description available."),
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "price": item.get("price"),
                "link": item.get("place_id_search") or item.get("link"),
            }
        )
    return sights


def fetch_serpapi_results(params: dict[str, Any], api_key: str) -> dict[str, Any]:
    client = serpapi.Client(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    results = client.search(params)
    return dict(results)


def fetch_trip_bundle_live(prompt: dict[str, Any], api_key: str) -> dict[str, Any]:
    departure_date, return_date = resolve_preset_dates(prompt)
    flights_params = build_search_params(prompt["origin"], "Specific destination", prompt["destination"], departure_date, return_date)
    hotels_params = build_hotels_params(prompt["hotel_query"], departure_date, return_date)
    sights_params = build_sights_params(prompt["destination_name"])

    return {
        "flights": fetch_serpapi_results(flights_params, api_key),
        "hotels": fetch_serpapi_results(hotels_params, api_key),
        "sights": fetch_serpapi_results(sights_params, api_key),
        "metadata": {
            "departure_date": departure_date.isoformat(),
            "return_date": return_date.isoformat(),
            "origin": prompt["origin"],
            "destination": prompt["destination"],
        },
    }


def rank_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        results,
        key=lambda item: (
            not item.get("is_actionable", False),
            -item["deal_score"],
            item["price"] if item["price"] is not None else float("inf"),
            item["duration_minutes"] if item["duration_minutes"] is not None else float("inf"),
        ),
    )


def pick_cheapest(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = [item for item in results if item["price"] is not None]
    return min(priced, key=lambda item: item["price"]) if priced else None


def pick_fastest(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    timed = [item for item in results if item["duration_minutes"] is not None]
    return min(timed, key=lambda item: item["duration_minutes"]) if timed else None


def pick_best_value(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = rank_results(results)
    return ranked[0] if ranked else None


def budget_status_text(result: dict[str, Any]) -> str:
    if result["price"] is None:
        return "Budget unknown"
    return "Under budget" if result["under_budget"] else "Over budget"


def airline_badge_text(airline: str) -> str:
    parts = [part.strip() for part in airline.split("/") if part.strip()]
    if not parts:
        return "Airline"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} +{len(parts) - 1}"


def open_modal(name: str, payload: dict[str, Any]) -> None:
    st.session_state["active_modal"] = name
    st.session_state["modal_payload"] = payload
    st.rerun()


def close_modal() -> None:
    st.session_state["active_modal"] = None
    st.session_state["modal_payload"] = {}
    st.rerun()


def calculate_hotel_score(hotel: dict[str, Any], remaining_budget: float) -> float:
    score = 0.0
    if hotel["overall_rating"] is not None:
        score += float(hotel["overall_rating"]) * 20
    if hotel["total_price"] is not None:
        score -= float(hotel["total_price"]) / 50
        if hotel["total_price"] <= remaining_budget:
            score += 12
    return score


def pick_best_hotel(hotels: list[dict[str, Any]], remaining_budget: float) -> dict[str, Any] | None:
    candidates = [hotel for hotel in hotels if hotel["total_price"] is not None]
    if not candidates:
        return hotels[0] if hotels else None
    return max(candidates, key=lambda hotel: calculate_hotel_score(hotel, remaining_budget))


def pick_cheapest_hotel(hotels: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = [hotel for hotel in hotels if hotel["total_price"] is not None]
    return min(priced, key=lambda hotel: hotel["total_price"]) if priced else None


def build_itinerary_days(sights: list[dict[str, Any]], day_count: int) -> list[dict[str, Any]]:
    capped_sights = sights[: max(3, day_count * 2)]
    itinerary: list[dict[str, Any]] = []
    for day_index in range(day_count):
        day_sights = capped_sights[day_index * 2 : (day_index * 2) + 2]
        if not day_sights:
            break
        itinerary.append(
            {
                "day_label": f"Day {day_index + 1}",
                "headline": day_sights[0]["title"],
                "stops": day_sights,
            }
        )
    return itinerary


def render_highlight_card(title: str, emoji: str, result: dict[str, Any] | None) -> None:
    if result is None:
        st.info(f"{emoji} {title}: No matching option.")
        return

    destination_label = result.get("destination_label") or result["arrival_airport"]
    budget_state = budget_status_text(result)
    st.markdown(
        f"""
        <div class="flight-card spotlight-card">
            <div class="flight-card-header">
                <div class="flight-card-title">{emoji} {title}</div>
                <div class="airline-badge">{airline_badge_text(result["airline"])}</div>
            </div>
            <div class="flight-card-price">{result["price_display"]}</div>
            <div class="flight-card-route">{result["departure_airport"]} → {destination_label}</div>
            <div class="flight-card-meta">{result["airline"]} · {result["duration_display"]} · {result["stops_display"]}</div>
            <div class="flight-time-row">
                <div class="time-block"><span class="time-label">Depart</span><span class="time-value">{result["departure_time"]}</span></div>
                <div class="time-arrow">→</div>
                <div class="time-block"><span class="time-label">Arrive</span><span class="time-value">{result["arrival_time"]}</span></div>
            </div>
            <div class="flight-card-footer">Deal score: {result["deal_score"]} · {budget_state}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ranked_card(result: dict[str, Any], index: int) -> None:
    destination_label = result.get("destination_label") or result["arrival_airport"]
    if result["price"] is None:
        budget_class = "budget-neutral"
    else:
        budget_class = "budget-ok" if result["under_budget"] else "budget-over"
    budget_text = budget_status_text(result)

    st.markdown(
        f"""
        <div class="flight-card">
            <div class="flight-card-header">
                <div class="flight-card-title">#{index} {result["departure_airport"]} → {destination_label}</div>
                <div style="display:flex; gap:0.5rem; align-items:center;">
                    <div class="airline-badge">{airline_badge_text(result["airline"])}</div>
                    <div class="score-pill">Score {result["deal_score"]}</div>
                </div>
            </div>
            <div class="flight-card-price">{result["price_display"]}</div>
            <div class="flight-time-row">
                <div class="time-block"><span class="time-label">Depart</span><span class="time-value">{result["departure_time"]}</span></div>
                <div class="time-arrow">→</div>
                <div class="time-block"><span class="time-label">Arrive</span><span class="time-value">{result["arrival_time"]}</span></div>
            </div>
            <div class="flight-grid">
                <div><strong>Airline</strong><br>{result["airline"]}</div>
                <div><strong>Duration</strong><br>{result["duration_display"]}</div>
                <div><strong>Stops</strong><br>{result["stops_display"]}</div>
                <div><strong>Class</strong><br>{result["travel_class"]}</div>
                <div><strong>From</strong><br>{result["departure_airport"]}</div>
                <div><strong>To</strong><br>{destination_label}</div>
            </div>
            <div class="flight-card-footer">
                <span class="{budget_class}">{budget_text}</span>
                <span>{result["note"]}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hotel_card(title: str, hotel: dict[str, Any] | None) -> None:
    if hotel is None:
        st.info(f"{title}: No hotel result available.")
        return

    amenities_text = " · ".join(hotel["amenities"]) if hotel["amenities"] else "Amenities not listed"
    rating_text = f'{hotel["overall_rating"]} ({hotel["reviews"]} reviews)' if hotel["overall_rating"] is not None else "Rating unavailable"
    st.markdown(
        f"""
        <div class="flight-card">
            <div class="flight-card-title">🏨 {title}</div>
            <div class="flight-card-price">{hotel["total_price_display"]}</div>
            <div class="flight-card-meta">{hotel["name"]} · {hotel["hotel_class"]}</div>
            <div class="flight-card-meta">{rating_text}</div>
            <div class="flight-card-meta">{amenities_text}</div>
            <div class="flight-card-footer">{hotel["transport_note"]}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sight_card(sight: dict[str, Any], index: int) -> None:
    rating_text = f'{sight["rating"]} ({sight["reviews"]} reviews)' if sight.get("rating") is not None else "Rating unavailable"
    price_text = sight.get("price") or "Price not listed"
    st.markdown(
        f"""
        <div class="flight-card">
            <div class="flight-card-title">#{index} {sight["title"]}</div>
            <div class="flight-card-meta">{sight["description"]}</div>
            <div class="flight-card-meta">{rating_text} · {price_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("Flight Options", width="large")
def flight_options_dialog() -> None:
    payload = st.session_state.get("modal_payload", {})
    flights = payload.get("flights", [])
    comparison_rows = payload.get("comparison_rows", [])

    st.write("Best flight and alternate options for this trip.")
    for index, flight in enumerate(flights, start=1):
        render_ranked_card(flight, index)

    if comparison_rows:
        comparison_df = pd.DataFrame(
            [
                {
                    "Airline": row["airline"],
                    "From": row["departure_airport"],
                    "To": row.get("destination_label") or row["arrival_airport"],
                    "Depart": row["departure_time"],
                    "Arrive": row["arrival_time"],
                    "Duration": row["duration_display"],
                    "Stops": row["stops_display"],
                    "Price": row["price_display"],
                    "Score": row["deal_score"],
                }
                for row in comparison_rows
            ]
        )
        st.markdown("**Flight comparison**")
        st.dataframe(comparison_df, use_container_width=True, hide_index=True)

    st.button("Close", on_click=close_modal, use_container_width=True)


@st.dialog("Hotel Options", width="large")
def hotel_options_dialog() -> None:
    payload = st.session_state.get("modal_payload", {})
    hotels = payload.get("hotels", [])
    st.write("Recommended and alternate stay options for this trip.")
    for hotel in hotels:
        render_hotel_card(hotel["name"], hotel)
    st.button("Close", on_click=close_modal, use_container_width=True)


@st.dialog("Things To Do", width="large")
def sights_dialog() -> None:
    payload = st.session_state.get("modal_payload", {})
    sights = payload.get("sights", [])
    st.write("Sightseeing picks pulled from the destination search results.")
    for index, sight in enumerate(sights, start=1):
        render_sight_card(sight, index)
    st.button("Close", on_click=close_modal, use_container_width=True)


@st.dialog("Suggested Itinerary", width="large")
def itinerary_dialog() -> None:
    payload = st.session_state.get("modal_payload", {})
    itinerary = payload.get("itinerary", [])
    for day in itinerary:
        stop_titles = ", ".join(stop["title"] for stop in day["stops"])
        st.markdown(
            f"""
            <div class="flight-card">
                <div class="flight-card-title">{day["day_label"]}</div>
                <div class="flight-card-meta">{day["headline"]}</div>
                <div class="flight-card-footer">{stop_titles}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.button("Close", on_click=close_modal, use_container_width=True)


@st.dialog("Trip Details", width="large")
def trip_details_dialog() -> None:
    payload = st.session_state.get("modal_payload", {})
    title = payload.get("title", "Trip details")
    st.write(title)
    raw = payload.get("raw")
    if raw is not None:
        st.json(raw)
    st.button("Close", on_click=close_modal, use_container_width=True)


def render_trip_bundle(prompt: dict[str, Any], bundle: dict[str, Any], budget: float) -> None:
    parsed_flights = parse_google_flights_response(bundle["flights"], budget)
    actionable_flights = [result for result in parsed_flights if result.get("is_actionable")]
    flight_pool = actionable_flights or parsed_flights
    ranked_flights = rank_results(flight_pool)
    selected_flight = pick_best_value(flight_pool)
    cheapest_flight = pick_cheapest(flight_pool)
    fastest_flight = pick_fastest(flight_pool)

    parsed_hotels = parse_hotels_response(bundle["hotels"])
    remaining_budget = budget - (selected_flight["price"] if selected_flight and selected_flight["price"] is not None else 0)
    best_hotel = pick_best_hotel(parsed_hotels, remaining_budget)
    cheapest_hotel = pick_cheapest_hotel(parsed_hotels)
    top_hotels = sorted(parsed_hotels, key=lambda hotel: -calculate_hotel_score(hotel, remaining_budget))[:3]

    parsed_sights = parse_sights_response(bundle["sights"])
    itinerary = build_itinerary_days(parsed_sights, int(prompt.get("trip_length_days", 3)))

    flight_price = selected_flight["price"] if selected_flight and selected_flight["price"] is not None else 0
    hotel_price = best_hotel["total_price"] if best_hotel and best_hotel["total_price"] is not None else 0
    core_total = flight_price + hotel_price
    displayed_keys: set[tuple[Any, ...]] = set()
    if selected_flight:
        displayed_keys.add(
            (
                selected_flight.get("price"),
                selected_flight.get("duration_minutes"),
                selected_flight.get("departure_time"),
                selected_flight.get("arrival_time"),
                selected_flight.get("airline"),
            )
        )
    alternative_flights = []
    for flight in ranked_flights:
        key = (
            flight.get("price"),
            flight.get("duration_minutes"),
            flight.get("departure_time"),
            flight.get("arrival_time"),
            flight.get("airline"),
        )
        if key in displayed_keys:
            continue
        displayed_keys.add(key)
        alternative_flights.append(flight)
    comparison_rows = [selected_flight] + alternative_flights[:4] if selected_flight else alternative_flights[:5]

    st.subheader("Trip Summary")
    st.caption(prompt["phrase"])

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("Flight", selected_flight["price_display"] if selected_flight else "N/A")
    metric_2.metric("Hotel", best_hotel["total_price_display"] if best_hotel else "N/A")
    metric_3.metric("Core trip total", format_price(core_total if core_total else None))
    metric_4.metric("Budget left", format_price(budget - core_total))

    action_col1, action_col2, action_col3, action_col4, action_col5 = st.columns(5)
    with action_col1:
        with st.popover("View flights", use_container_width=True):
            st.write("Best flight and alternate options for this trip.")
            for index, flight in enumerate(alternative_flights[:5], start=1):
                render_ranked_card(flight, index)
            if comparison_rows:
                comparison_df = pd.DataFrame(
                    [
                        {
                            "Airline": row["airline"],
                            "From": row["departure_airport"],
                            "To": row.get("destination_label") or row["arrival_airport"],
                            "Depart": row["departure_time"],
                            "Arrive": row["arrival_time"],
                            "Duration": row["duration_display"],
                            "Stops": row["stops_display"],
                            "Price": row["price_display"],
                            "Score": row["deal_score"],
                        }
                        for row in comparison_rows
                    ]
                )
                st.markdown("**Flight comparison**")
                st.dataframe(comparison_df, use_container_width=True, hide_index=True)
    with action_col2:
        with st.popover("View hotels", use_container_width=True):
            st.write("Recommended and alternate stay options for this trip.")
            for hotel in top_hotels or parsed_hotels[:5]:
                render_hotel_card(hotel["name"], hotel)
    with action_col3:
        with st.popover("View sights", use_container_width=True):
            st.write("Sightseeing picks pulled from the destination search results.")
            for index, sight in enumerate(parsed_sights[:10], start=1):
                render_sight_card(sight, index)
    with action_col4:
        with st.popover("View itinerary", use_container_width=True):
            for day in itinerary:
                stop_titles = ", ".join(stop["title"] for stop in day["stops"])
                st.markdown(
                    f"""
                    <div class="flight-card">
                        <div class="flight-card-title">{day["day_label"]}</div>
                        <div class="flight-card-meta">{day["headline"]}</div>
                        <div class="flight-card-footer">{stop_titles}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    with action_col5:
        with st.popover("Trip data", use_container_width=True):
            st.write(prompt["phrase"])
            st.json(bundle)

    st.markdown("**Flight picks**")
    flight_highlight_col1, flight_highlight_col2, flight_highlight_col3 = st.columns(3)
    with flight_highlight_col1:
        render_highlight_card("Best Flight", "🧠", selected_flight)
    with flight_highlight_col2:
        render_highlight_card("Cheapest Flight", "💸", cheapest_flight)
    with flight_highlight_col3:
        render_highlight_card("Fastest Flight", "⚡", fastest_flight)

    plan_options = [
        {
            "label": "Option 1: Smart Save",
            "summary": "Cheapest practical combo with sightseeing picks for a lower total.",
            "flight": cheapest_flight or selected_flight,
            "hotel": cheapest_hotel or best_hotel,
            "sights": parsed_sights[:3],
        },
        {
            "label": "Option 2: Best Balance",
            "summary": "Best-value flight plus the strongest hotel fit for the trip budget.",
            "flight": selected_flight,
            "hotel": best_hotel or cheapest_hotel,
            "sights": parsed_sights[3:6] or parsed_sights[:3],
        },
    ]

    option_tabs = st.tabs([option["label"] for option in plan_options])
    for tab, option in zip(option_tabs, plan_options):
        with tab:
            selected_option_flight = option["flight"]
            selected_option_hotel = option["hotel"]
            selected_option_sights = option["sights"]
            option_total = (
                (selected_option_flight["price"] if selected_option_flight and selected_option_flight["price"] is not None else 0)
                + (selected_option_hotel["total_price"] if selected_option_hotel and selected_option_hotel["total_price"] is not None else 0)
            )
            st.markdown(f'<p class="section-note">{option["summary"]}</p>', unsafe_allow_html=True)
            trip_col1, trip_col2, trip_col3 = st.columns([1.15, 1.15, 0.9])
            with trip_col1:
                render_highlight_card("Flight", "✈️", selected_option_flight)
            with trip_col2:
                render_hotel_card("Hotel", selected_option_hotel)
            with trip_col3:
                st.markdown(
                    f"""
                    <div class="flight-card">
                        <div class="flight-card-title">🌤️ Day Plan</div>
                        <div class="flight-card-price">{format_price(option_total if option_total else None)}</div>
                        <div class="flight-card-meta">Budget target: {format_price(budget)}</div>
                        <div class="flight-card-footer">Flight + hotel only. Activity prices appear only when Google lists them.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            if selected_option_sights:
                st.markdown("**Included sightseeing ideas**")
                sight_cols = st.columns(min(3, len(selected_option_sights)))
                for col, sight in zip(sight_cols, selected_option_sights):
                    with col:
                        render_sight_card(sight, selected_option_sights.index(sight) + 1)

    preview_col1, preview_col2 = st.columns(2)
    with preview_col1:
        if top_hotels:
            st.markdown("**Hotel preview**")
            render_hotel_card("Top stay", top_hotels[0])
    with preview_col2:
        if parsed_sights:
            st.markdown("**Sightseeing preview**")
            render_sight_card(parsed_sights[0], 1)


def main() -> None:
    demo_presets = load_demo_presets()
    trip_prompts = load_trip_prompts()
    preset_lookup = {preset["phrase"]: preset for preset in demo_presets if preset.get("phrase")}
    trip_prompt_lookup = {prompt["phrase"]: prompt for prompt in trip_prompts if prompt.get("phrase")}
    cache_entries = list_cache_entries()
    trip_cache_entries = list_trip_cache_entries()
    cache_lookup = {
        f'{entry["label"]} [{entry["origin"]} -> {entry["destination"]}, {entry["captured_at"]}]': entry
        for entry in cache_entries
    }
    trip_cache_lookup = {
        f'{entry["label"]} [{entry["origin"]} -> {entry["destination"]}, {entry["captured_at"]}]': entry
        for entry in trip_cache_entries
    }

    st.set_page_config(page_title="Jetpot", page_icon="🧳", layout="wide")

    st.markdown(
        """
        <style>
            .stApp, .stMarkdown, .stTextInput label, .stNumberInput label, .stSelectbox label, .stRadio label, .stCaption {
                font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
            }
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(34, 139, 230, 0.12), transparent 20%),
                    radial-gradient(circle at top right, rgba(255, 201, 107, 0.18), transparent 18%),
                    linear-gradient(180deg, #f6fbff 0%, #eef5fb 55%, #f8fbfd 100%);
                color: #17324a;
            }
            .hero {
                padding: 1.35rem 1.5rem;
                border-radius: 22px;
                background: linear-gradient(135deg, #0f4c81, #2d7cbf 52%, #ffd27a 150%);
                color: #ffffff;
                margin-bottom: 1rem;
                border: 1px solid rgba(255, 255, 255, 0.16);
                box-shadow: 0 18px 40px rgba(15, 76, 129, 0.16);
            }
            .hero h1 {
                margin: 0;
                font-size: 2.05rem;
                letter-spacing: 0.02em;
            }
            .hero p {
                margin: 0.45rem 0 0;
                font-size: 0.98rem;
                max-width: 52rem;
                color: rgba(255, 255, 255, 0.92);
            }
            .flight-card {
                background: rgba(255, 255, 255, 0.88);
                border: 1px solid rgba(19, 50, 74, 0.08);
                border-radius: 18px;
                padding: 1rem 1.1rem;
                margin-bottom: 0.85rem;
                box-shadow: 0 10px 24px rgba(16, 51, 82, 0.08);
            }
            .spotlight-card {
                min-height: 168px;
            }
            .flight-card-header {
                display: flex;
                justify-content: space-between;
                gap: 0.75rem;
                align-items: center;
                margin-bottom: 0.5rem;
            }
            .flight-card-title {
                font-size: 1.02rem;
                font-weight: 700;
                color: #17324a;
            }
            .flight-card-price {
                font-size: 1.65rem;
                font-weight: 800;
                color: #0f4c81;
                margin: 0.25rem 0 0.4rem;
            }
            .flight-card-route, .flight-card-meta, .flight-card-footer {
                color: #4a667f;
                font-size: 0.95rem;
            }
            .flight-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
                gap: 0.85rem;
                margin: 0.75rem 0;
            }
            .score-pill {
                white-space: nowrap;
                background: #e8f2fb;
                color: #0f4c81;
                padding: 0.3rem 0.65rem;
                border-radius: 999px;
                font-weight: 700;
                border: 1px solid rgba(15, 76, 129, 0.08);
            }
            .budget-ok {
                color: #0b7a4b;
                font-weight: 700;
            }
            .budget-over {
                color: #b55a17;
                font-weight: 700;
            }
            .budget-neutral {
                color: #6b7f94;
                font-weight: 700;
            }
            .disclaimer {
                color: #617b91;
                font-size: 0.95rem;
                margin-top: 0.35rem;
            }
            .section-note {
                color: #5f7890;
                font-size: 0.88rem;
                margin: 0.15rem 0 0.75rem;
            }
            .airline-badge {
                display: inline-flex;
                align-items: center;
                border-radius: 999px;
                background: #f0f6fb;
                color: #0f4c81;
                padding: 0.28rem 0.62rem;
                font-size: 0.8rem;
                font-weight: 700;
                border: 1px solid rgba(15, 76, 129, 0.08);
            }
            .flight-time-row {
                display: flex;
                align-items: center;
                gap: 0.9rem;
                margin: 0.7rem 0 0.85rem;
            }
            .time-block {
                display: flex;
                flex-direction: column;
                gap: 0.1rem;
                min-width: 0;
            }
            .time-label {
                color: #6e879d;
                font-size: 0.76rem;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 700;
            }
            .time-value {
                color: #17324a;
                font-size: 1rem;
                font-weight: 700;
            }
            .time-arrow {
                color: #7f96ab;
                font-size: 1rem;
                font-weight: 700;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="hero">
            <h1>🧳 Jetpot</h1>
            <p>Lucky-feeling travel planning with live flights, stay ideas, and sightseeing picks packed into clear, demo-friendly trip options.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    default_departure = date.today() + timedelta(days=14)
    default_return = default_departure + timedelta(days=3)

    if "origin_input" not in st.session_state:
        st.session_state["origin_input"] = "AUS"
    if "trip_mode_input" not in st.session_state:
        st.session_state["trip_mode_input"] = "Specific destination"
    if "destination_input" not in st.session_state:
        st.session_state["destination_input"] = "LAX"
    if "destination_name_input" not in st.session_state:
        st.session_state["destination_name_input"] = "San Francisco"
    if "hotel_query_input" not in st.session_state:
        st.session_state["hotel_query_input"] = "San Francisco hotels"
    if "departure_input" not in st.session_state:
        st.session_state["departure_input"] = default_departure
    if "return_input" not in st.session_state:
        st.session_state["return_input"] = default_return
    if "budget_input" not in st.session_state:
        st.session_state["budget_input"] = 350
    if "last_preset_phrase" not in st.session_state:
        st.session_state["last_preset_phrase"] = "Custom"
    if "last_trip_prompt" not in st.session_state:
        st.session_state["last_trip_prompt"] = trip_prompts[0]["phrase"] if trip_prompts else "Custom"
    if "depart_in_days_input" not in st.session_state:
        st.session_state["depart_in_days_input"] = 14
    if "trip_length_days_input" not in st.session_state:
        st.session_state["trip_length_days_input"] = 3
    if "experience_mode" not in st.session_state:
        st.session_state["experience_mode"] = "Complete trip"
    if "selected_trip_style" not in st.session_state:
        st.session_state["selected_trip_style"] = trip_prompts[0]["phrase"] if trip_prompts else "Custom"
    if "search_source_input" not in st.session_state:
        st.session_state["search_source_input"] = "Auto (cache first)"
    if "selected_demo_cache_label" not in st.session_state:
        st.session_state["selected_demo_cache_label"] = "Custom"
    if "selected_trip_cache_label" not in st.session_state:
        st.session_state["selected_trip_cache_label"] = "Custom"
    if "active_modal" not in st.session_state:
        st.session_state["active_modal"] = None
    if "modal_payload" not in st.session_state:
        st.session_state["modal_payload"] = {}

    active_modal = st.session_state.get("active_modal")
    if active_modal == "flights":
        flight_options_dialog()
    elif active_modal == "hotels":
        hotel_options_dialog()
    elif active_modal == "sights":
        sights_dialog()
    elif active_modal == "itinerary":
        itinerary_dialog()
    elif active_modal == "trip_details":
        trip_details_dialog()

    with st.sidebar:
        st.header("Plan Your Escape")
        experience_mode = st.radio(
            "Experience",
            options=["Complete trip", "Flight deals"],
            key="experience_mode",
            horizontal=True,
        )
        trip_prompt_labels = ["None"] + list(trip_prompt_lookup.keys())
        selected_trip_prompt_phrase = "None"
        selected_preset_phrase = "Custom"
        data_source = "Auto (cache first)"
        selected_cache_label = None

        if experience_mode == "Complete trip":
            selected_trip_prompt_phrase = st.selectbox(
                "Trip style",
                options=["Custom"] + trip_prompt_labels[1:],
                key="selected_trip_style",
                help="Use a curated starter trip, then customize any field below.",
            )
            if selected_trip_prompt_phrase != "Custom" and selected_trip_prompt_phrase != st.session_state["last_trip_prompt"]:
                apply_trip_prompt(trip_prompt_lookup[selected_trip_prompt_phrase])
                st.session_state["last_trip_prompt"] = selected_trip_prompt_phrase
                st.session_state["selected_trip_cache_label"] = "Custom"
            elif selected_trip_prompt_phrase == "Custom":
                st.session_state["last_trip_prompt"] = "Custom"
            saved_trip_labels = ["Custom"] + list(trip_cache_lookup.keys())
            selected_trip_cache_label = st.selectbox(
                "Saved trips",
                options=saved_trip_labels,
                key="selected_trip_cache_label",
                help="Load a previously built complete trip and reuse its fields.",
            )
            if selected_trip_cache_label != "Custom":
                trip_cache_entry = trip_cache_lookup[selected_trip_cache_label]
                try:
                    trip_cache_payload = load_trip_cache(trip_cache_entry["path"])
                    apply_trip_cache_payload(trip_cache_payload)
                    selected_trip_prompt_phrase = "Custom"
                    st.session_state["last_trip_prompt"] = "Custom"
                except (OSError, json.JSONDecodeError):
                    st.warning("Unable to load that saved trip cache entry.")
            st.caption("Each trip style opens with two packaged options in the main view.")
        else:
            st.markdown("**Flight Search**")
            preset_labels = ["Custom"] + list(preset_lookup.keys())
            selected_preset_phrase = st.selectbox(
                "Flight preset",
                options=preset_labels,
                help="Preset phrases load demo-friendly airport, date, and budget combinations.",
            )
            if selected_preset_phrase != "Custom" and selected_preset_phrase != st.session_state["last_preset_phrase"]:
                apply_demo_preset(preset_lookup[selected_preset_phrase])
                st.session_state["last_preset_phrase"] = selected_preset_phrase
                st.session_state["selected_demo_cache_label"] = "Custom"
            elif selected_preset_phrase == "Custom":
                st.session_state["last_preset_phrase"] = "Custom"

            data_source = st.radio(
                "Search source",
                options=["Auto (cache first)", "Live SerpApi", "Cached demo JSON"],
                key="search_source_input",
                help="Use cached JSON for repeatable demos and fewer API calls.",
            )
            saved_search_labels = ["Custom"] + list(cache_lookup.keys())
            selected_cache_label = st.selectbox(
                "Saved searches",
                options=saved_search_labels,
                key="selected_demo_cache_label",
                help="Load a previously saved flight search and reuse its fields.",
            )
            if selected_cache_label != "Custom":
                cache_entry = cache_lookup[selected_cache_label]
                try:
                    cache_payload_for_form = load_demo_cache(cache_entry["path"])
                    apply_demo_cache_payload(cache_payload_for_form)
                    st.session_state["search_source_input"] = "Cached demo JSON"
                    data_source = "Cached demo JSON"
                    selected_preset_phrase = "Custom"
                    st.session_state["last_preset_phrase"] = "Custom"
                except (OSError, json.JSONDecodeError):
                    st.warning("Unable to load that saved search cache entry.")
            elif data_source == "Cached demo JSON" and not cache_lookup:
                st.caption("No cached demo JSON files found in `demo_cache/` yet.")

        st.markdown("**Trip Details**")
        origin = normalize_airport_code(
            st.text_input(
                "From",
                key="origin_input",
                help="Use a 3-letter airport code like AUS or JFK.",
            )
        )
        trip_mode = st.radio(
            "Mode",
            options=["Specific destination", "Explore cheap destinations"],
            key="trip_mode_input",
            horizontal=True,
        )
        destination = ""
        if trip_mode == "Specific destination":
            destination = normalize_airport_code(
                st.text_input(
                    "To",
                    key="destination_input",
                    help="Use a 3-letter airport code like LAX or CDG.",
                )
            )
        destination_name = st.text_input(
            "Destination name",
            key="destination_name_input",
            help="Used for hotel and sightseeing lookups, for example San Francisco or Honolulu.",
        )
        hotel_query = st.text_input(
            "Hotel area",
            key="hotel_query_input",
            help="Optional custom hotel search phrase, for example Waikiki hotels.",
        )

        depart_col, length_col = st.columns(2)
        with depart_col:
            depart_in_days = st.number_input("Depart in", min_value=1, max_value=365, step=1, key="depart_in_days_input")
        with length_col:
            trip_length_days = st.number_input("Days", min_value=1, max_value=30, step=1, key="trip_length_days_input")
        departure_date = date.today() + timedelta(days=int(depart_in_days))
        return_date = departure_date + timedelta(days=int(trip_length_days))
        st.caption(f"Travel window: {departure_date.isoformat()} → {return_date.isoformat()}")
        max_budget = st.number_input("Budget (USD)", min_value=50, max_value=10000, step=25, key="budget_input")
        st.markdown("**Run**")
        save_to_cache = st.checkbox("Save live results to demo cache", value=True)
        show_debug = st.checkbox("Show raw SerpApi response", value=False)
        search_clicked = st.button("Build my trip", type="primary", use_container_width=True)

    st.caption("Flight data may change. Always verify prices before booking.")

    validation_errors: list[str] = []
    if origin and not is_valid_airport_code(origin):
        validation_errors.append("Origin airport code must be exactly 3 letters.")
    if trip_mode == "Specific destination" and destination and not is_valid_airport_code(destination):
        validation_errors.append("Destination airport code must be exactly 3 letters.")
    if trip_mode == "Specific destination" and not destination:
        validation_errors.append("Destination airport code is required in specific destination mode.")
    if experience_mode == "Complete trip" and not destination_name.strip():
        validation_errors.append("Destination name is required in complete trip mode.")
    if int(st.session_state["trip_length_days_input"]) < 1:
        validation_errors.append("Trip length must be at least 1 day.")

    if validation_errors:
        for error in validation_errors:
            st.warning(error)
        st.stop()

    if not search_clicked:
        st.info("Choose a style, adjust the details, and build your trip.")
        st.stop()

    if experience_mode == "Complete trip":
        active_trip_prompt = build_active_trip_prompt(
            origin=origin,
            destination=destination,
            destination_name=destination_name,
            hotel_query=hotel_query,
            depart_in_days=int(depart_in_days),
            trip_length_days=int(trip_length_days),
            budget=float(max_budget),
        )

        trip_bundle_path = trip_cache_path(active_trip_prompt)
        trip_bundle_payload: dict[str, Any] | None = None
        trip_bundle_source = "live"

        if trip_bundle_path.exists():
            try:
                trip_bundle_payload = load_trip_cache(trip_bundle_path)
            except (OSError, json.JSONDecodeError) as exc:
                st.error(f"Unable to load cached trip bundle: {exc}")
                st.stop()
            st.info(f"Using saved trip from `trip_cache/{trip_bundle_path.name}`.")
            trip_bundle_source = "cache"
        else:
            api_key = get_api_key()
            if not api_key:
                st.error("Missing `SERPAPI_KEY`. Add it to your environment, local `.env`, or Streamlit app Secrets before building a full trip.")
                st.stop()
            try:
                with st.spinner("Building your complete trip with flights, stays, and sightseeing..."):
                    live_bundle = fetch_trip_bundle_live(active_trip_prompt, api_key)
            except serpapi.TimeoutError:
                st.error("The trip bundle request timed out. Try again in a moment.")
                st.stop()
            except serpapi.HTTPError as exc:
                st.error(f"SerpApi returned an HTTP error while building the trip bundle: {exc}")
                st.stop()
            except Exception as exc:
                st.error(f"Unable to reach SerpApi for the trip bundle: {exc}")
                st.stop()

            save_trip_cache(trip_bundle_path, active_trip_prompt, live_bundle)
            trip_bundle_payload = {"bundle": live_bundle}
            st.success(f"Saved trip bundle to `trip_cache/{trip_bundle_path.name}`.")

        if trip_bundle_payload:
            render_trip_bundle(active_trip_prompt, trip_bundle_payload["bundle"], float(active_trip_prompt.get("budget", 1000)))
            with st.expander("Trip Bundle Details", expanded=False):
                st.write(f"Trip bundle source: {trip_bundle_source}")
                st.write(f"Trip cache file: `trip_cache/{trip_bundle_path.name}`")
            if show_debug:
                with st.expander("🔎 Source Data"):
                    st.json(trip_bundle_payload["bundle"])
        st.stop()

    search_phrase = selected_preset_phrase if selected_preset_phrase != "Custom" else build_search_phrase(origin, trip_mode, destination, max_budget)
    base_params = build_search_params(origin, trip_mode, destination, departure_date, return_date)
    matching_cache_path = cache_path_for_params(base_params)
    cache_payload: dict[str, Any] | None = None
    raw_response: dict[str, Any]
    response_source = "live"

    if data_source == "Cached demo JSON":
        if not selected_cache_label:
            st.error("Choose a saved demo JSON file or switch to live mode.")
            st.stop()
        cache_entry = cache_lookup[selected_cache_label]
        try:
            cache_payload = load_demo_cache(cache_entry["path"])
        except (OSError, json.JSONDecodeError) as exc:
            st.error(f"Unable to load cached demo JSON: {exc}")
            st.stop()
        raw_response = cache_payload.get("raw_response", {})
        response_source = "cache"
        st.info(f"Loaded cached result from `{cache_entry['path'].name}`.")
    elif data_source == "Auto (cache first)" and matching_cache_path.exists():
        try:
            cache_payload = load_demo_cache(matching_cache_path)
        except (OSError, json.JSONDecodeError) as exc:
            st.error(f"Unable to load cached demo JSON: {exc}")
            st.stop()
        raw_response = cache_payload.get("raw_response", {})
        response_source = "cache"
        st.info(f"Using cached result from `{matching_cache_path.name}`.")
    else:
        api_key = get_api_key()
        if not api_key:
            st.error("Missing `SERPAPI_KEY`. Add it to your environment, local `.env`, or Streamlit app Secrets before searching.")
            st.stop()

        try:
            with st.spinner("Fetching live flight data from SerpApi..."):
                raw_response = fetch_serpapi_results(base_params, api_key)
        except serpapi.TimeoutError:
            st.error("The SerpApi request timed out. Try again in a moment or narrow the search.")
            st.stop()
        except serpapi.HTTPError as exc:
            st.error(f"SerpApi returned an HTTP error: {exc}")
            st.stop()
        except Exception as exc:
            st.error(f"Unable to reach SerpApi right now: {exc}")
            st.stop()

        if save_to_cache:
            save_demo_cache(
                cache_path=matching_cache_path,
                search_phrase=search_phrase,
                search_params=base_params,
                trip_mode=trip_mode,
                budget=max_budget,
                raw_response=raw_response,
            )
            st.success(f"Saved this search to `demo_cache/{matching_cache_path.name}` for future demos.")

    if raw_response.get("error"):
        st.error(f"SerpApi error: {raw_response['error']}")
        st.stop()

    effective_trip_mode = trip_mode
    if cache_payload and cache_payload.get("trip_mode"):
        effective_trip_mode = str(cache_payload["trip_mode"])

    if effective_trip_mode == "Specific destination":
        parsed_results = parse_google_flights_response(raw_response, max_budget)
    else:
        parsed_results = parse_google_travel_explore_response(raw_response, origin, max_budget)

    if not parsed_results:
        st.warning("No flight options were returned for this search. Try changing dates, destination, or trip mode.")
        if show_debug:
            with st.expander("🔎 Source Data"):
                st.json(raw_response)
        st.stop()

    actionable_results = [result for result in parsed_results if result.get("is_actionable")]
    incomplete_results = [result for result in parsed_results if not result.get("is_actionable")]
    display_results = actionable_results if actionable_results else parsed_results

    ranked_results = rank_results(display_results)
    top_results = ranked_results[:5]
    cheapest = pick_cheapest(display_results)
    fastest = pick_fastest(display_results)
    best_value = pick_best_value(display_results)

    summary_df = pd.DataFrame(ranked_results)

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("Cheapest", cheapest["price_display"] if cheapest else "N/A")
    metric_2.metric("Best deal score", best_value["deal_score"] if best_value else "N/A")
    metric_3.metric("Fastest", fastest["duration_display"] if fastest else "N/A")
    metric_4.metric("Options found", len(display_results))

    if incomplete_results:
        st.info(
            f"Omitted {len(incomplete_results)} destination ideas from ranking because SerpApi did not return complete fare details for them."
        )

    highlight_col1, highlight_col2, highlight_col3 = st.columns(3)
    with highlight_col1:
        render_highlight_card("Best Value", "🧠", best_value)
    with highlight_col2:
        render_highlight_card("Cheapest", "💸", cheapest)
    with highlight_col3:
        render_highlight_card("Fastest", "⚡", fastest)

    st.subheader("Flight Options")
    for index, result in enumerate(top_results, start=1):
        render_ranked_card(result, index)

    st.subheader("Comparison Table")
    display_columns = [
        "departure_airport",
        "arrival_airport",
        "price_display",
        "duration_display",
        "stops_display",
        "airline",
        "deal_score",
    ]
    comparison_df = summary_df[display_columns].rename(
        columns={
            "departure_airport": "From",
            "arrival_airport": "To",
            "price_display": "Price",
            "duration_display": "Duration",
            "stops_display": "Stops",
            "airline": "Airline",
            "deal_score": "Deal Score",
        }
    )
    st.dataframe(comparison_df, use_container_width=True, hide_index=True)

    st.markdown(
        '<p class="disclaimer">This app summarizes public flight search data. It does not sell tickets. Verify before booking.</p>',
        unsafe_allow_html=True,
    )

    with st.expander("Demo Cache Details", expanded=False):
        st.write(f"Search phrase: {search_phrase}")
        st.write(f"Response source: {response_source}")
        if response_source == "cache" and cache_payload:
            st.write(f"Captured at: {cache_payload.get('captured_at', 'unknown')}")
            st.write(f"Cache file: {cache_payload.get('search_params', {})}")
        else:
            st.write(f"Suggested cache file: `demo_cache/{matching_cache_path.name}`")

    if show_debug:
        with st.expander("🔎 Source Data"):
            st.json(raw_response)


if __name__ == "__main__":
    main()

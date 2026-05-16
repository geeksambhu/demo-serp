from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import (
    PRESET_FILE,
    build_search_params,
    cache_path_for_params,
    fetch_serpapi_results,
    get_api_key,
    load_demo_presets,
    resolve_preset_dates,
    save_demo_cache,
)


def main() -> None:
    load_dotenv()
    api_key = get_api_key()
    if not api_key:
        raise SystemExit("Missing SERPAPI_KEY. Add it to your environment or .env before running this script.")

    presets = load_demo_presets()
    if not presets:
        raise SystemExit(f"No demo presets found in {PRESET_FILE}.")

    print(f"Capturing {len(presets)} demo searches...")

    for preset in presets:
        departure_date, return_date = resolve_preset_dates(preset)
        trip_mode = preset["trip_mode"]
        origin = preset["origin"]
        destination = preset.get("destination", "")
        search_phrase = preset["phrase"]

        search_params = build_search_params(origin, trip_mode, destination, departure_date, return_date)
        cache_path = cache_path_for_params(search_params)
        payload = fetch_serpapi_results(search_params, api_key)

        save_demo_cache(
            cache_path=cache_path,
            search_phrase=search_phrase,
            search_params=search_params,
            trip_mode=trip_mode,
            budget=float(preset.get("budget", 350)),
            raw_response=payload,
        )
        print(f"Saved {cache_path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()

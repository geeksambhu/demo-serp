from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import (
    fetch_trip_bundle_live,
    get_api_key,
    load_trip_prompts,
    save_trip_cache,
    trip_cache_path,
)


def main() -> None:
    load_dotenv()
    api_key = get_api_key()
    if not api_key:
        raise SystemExit("Missing SERPAPI_KEY. Add it to your environment or .env before running this script.")

    prompts = load_trip_prompts()
    if not prompts:
        raise SystemExit("No trip prompts found.")

    print(f"Capturing {len(prompts)} trip bundles...")
    for prompt in prompts:
        cache_path = trip_cache_path(prompt)
        bundle = fetch_trip_bundle_live(prompt, api_key)
        save_trip_cache(cache_path, prompt, bundle)
        print(f"Saved {cache_path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()

"""Run a single collection pass (automatic scheduling is a later milestone)."""
import argparse
import json
from .collector import collect_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="StudentPath Source Collector")
    parser.add_argument("--manifest", required=True, help="JSON source manifest")
    parser.add_argument("--db", default="collector.sqlite3", help="SQLite state database")
    parser.add_argument("--fixture-dir", help="Optional local S001.html etc., no network")
    args = parser.parse_args()
    print(json.dumps(collect_manifest(args.db, args.manifest, args.fixture_dir), indent=2))


if __name__ == "__main__":
    main()

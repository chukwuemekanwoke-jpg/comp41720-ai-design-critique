"""Upgrade an existing Collector store without fetching or publishing anything."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3

from .collector import migrate_source_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    uri = Path(args.db).resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
        migrate_source_status(db)
    print("Collector source-status schema upgraded; no fetch or publish performed.")


if __name__ == "__main__":
    main()

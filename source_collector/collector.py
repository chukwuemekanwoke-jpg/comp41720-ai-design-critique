"""Fetch, normalize, version and durably queue official ISD source updates.

Delivery to RabbitMQ is intentionally a separate relay: this module writes a
transactional outbox but never claims that pending events were published.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup

CLEANER_VERSION = "main-text-v1"
OFFICIAL_HOSTS = frozenset({"www.irishimmigration.ie", "irishimmigration.ie"})
MAX_HTML_BYTES = 2 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_official_url(url: str) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError(f"Not an approved official HTTPS source: {url}")


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_official_html(url: str) -> str:
    check_official_url(url)
    request = Request(url, headers={"User-Agent": "StudentPath-Project-Collector/0.1 (academic research)", "Accept": "text/html"})
    with build_opener(OfficialRedirects()).open(request, timeout=15) as response:
        check_official_url(response.geturl())
        if "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError("Source is not HTML")
        payload = response.read(MAX_HTML_BYTES + 1)
        if len(payload) > MAX_HTML_BYTES:
            raise ValueError("Official source exceeded size limit")
        charset = response.headers.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")


def clean_main_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe"]):
        node.decompose()
    for node in list(soup.select('[id*="cookie" i], [class*="cookie" i], [class*="newsletter" i]')):
        node.decompose()
    main = soup.select_one("main") or soup.select_one("article") or soup.select_one(".entry-content") or soup.body or soup
    parts: list[str] = []
    for node in main.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr"]):
        if node.find_parent(["p", "li", "tr"]):
            continue
        if node.name == "tr":
            content = " | ".join(cell.get_text(" ", strip=True) for cell in node.find_all(["td", "th"], recursive=False))
        else:
            content = node.get_text(" ", strip=True)
        content = re.sub(r"\s+", " ", content).strip()
        if content:
            parts.append(content)
    if not parts:
        parts = [main.get_text(" ", strip=True)]
    text = "\n".join(parts)
    return text.strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY, url TEXT NOT NULL,
  last_attempt_at TEXT, last_success_at TEXT, last_error TEXT,
  latest_hash TEXT, latest_snapshot_id TEXT, source_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
  content_sha256 TEXT NOT NULL, cleaner_version TEXT NOT NULL,
  raw_html TEXT NOT NULL, clean_text TEXT NOT NULL, first_fetched_at TEXT NOT NULL,
  FOREIGN KEY(source_id) REFERENCES sources(source_id)
);
CREATE TABLE IF NOT EXISTS outbox (
  event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
  source_version INTEGER NOT NULL, payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
  published_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  UNIQUE(source_id, source_version)
);
"""


class Collector:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.db = sqlite3.connect(self.db_path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def collect(self, source_id: str, url: str, fetcher=fetch_official_html, *, at: str | None = None) -> dict:
        check_official_url(url)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", source_id):
            raise ValueError("Unsafe source_id")
        timestamp = at or utc_now()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            current = self.db.execute("SELECT url FROM sources WHERE source_id=?", (source_id,)).fetchone()
            if current and current["url"] != url:
                raise ValueError("Source URL changed for existing source_id")
            self.db.execute("INSERT OR IGNORE INTO sources(source_id, url) VALUES (?, ?)", (source_id, url))
            self.db.execute("UPDATE sources SET last_attempt_at=? WHERE source_id=?", (timestamp, source_id))
        try:
            html = fetcher(url)
            clean_text = clean_main_text(html)
            if not clean_text:
                raise ValueError("Empty extracted main text")
        except Exception as exc:
            with self.db:
                self.db.execute("UPDATE sources SET last_error=? WHERE source_id=?", (str(exc)[:500], source_id))
            return {"source_id": source_id, "status": "fetch_failed", "error": str(exc)}

        digest = sha256(clean_text)
        snapshot_id = f"{source_id}:{digest}"
        with self.db:
            self.db.execute("BEGIN IMMEDIATE") if not self.db.in_transaction else None
            state = self.db.execute("SELECT latest_hash,source_version FROM sources WHERE source_id=?", (source_id,)).fetchone()
            changed = state["latest_hash"] != digest
            if changed:
                version = state["source_version"] + 1
                self.db.execute("""INSERT OR IGNORE INTO snapshots
                    (snapshot_id,source_id,content_sha256,cleaner_version,raw_html,clean_text,first_fetched_at)
                    VALUES (?,?,?,?,?,?,?)""",
                    (snapshot_id, source_id, digest, CLEANER_VERSION, html, clean_text, timestamp))
                payload = {"event_id": f"{source_id}:{version}", "source_id": source_id,
                           "source_version": version, "snapshot_id": snapshot_id,
                           "content_sha256": digest, "source_url": url,
                           "checked_at": timestamp, "cleaner_version": CLEANER_VERSION}
                self.db.execute("""INSERT INTO outbox(event_id,source_id,source_version,payload_json,created_at)
                    VALUES (?,?,?,?,?)""", (payload["event_id"], source_id, version, json.dumps(payload), timestamp))
                self.db.execute("""UPDATE sources SET last_success_at=?,last_error=NULL,
                    latest_hash=?,latest_snapshot_id=?,source_version=? WHERE source_id=?""",
                    (timestamp, digest, snapshot_id, version, source_id))
            else:
                version = state["source_version"]
                self.db.execute("UPDATE sources SET last_success_at=?,last_error=NULL WHERE source_id=?", (timestamp, source_id))
        return {"source_id": source_id, "status": "changed" if changed else "unchanged",
                "snapshot_id": snapshot_id, "source_version": version}

    def pending_events(self) -> list[dict]:
        rows = self.db.execute("SELECT payload_json FROM outbox WHERE status='pending' ORDER BY created_at,event_id").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def collect_manifest(db_path: str | Path, manifest_path: str | Path,
                     fixture_dir: str | Path | None = None) -> list[dict]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    collector = Collector(db_path)
    try:
        results = []
        for source in manifest["sources"]:
            source_id, url = source["source_id"], source["canonical_url"]
            if fixture_dir:
                def from_fixture(_url, sid=source_id):
                    return (Path(fixture_dir) / f"{sid}.html").read_text(encoding="utf-8")
                fetcher = from_fixture
            else:
                fetcher = fetch_official_html
            results.append(collector.collect(source_id, url, fetcher))
        return results
    finally:
        collector.close()

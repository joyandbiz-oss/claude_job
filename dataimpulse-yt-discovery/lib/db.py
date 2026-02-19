"""
SQLite database layer — schema creation, upserts, and query helpers.
All intermediate storage lives in a single discovery.db file.
"""

import logging
import os
import shutil
import sqlite3
from datetime import datetime

log = logging.getLogger(__name__)

DB_PATH = "discovery.db"
BACKUP_DIR = "backups"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    handle TEXT,
    title TEXT,
    url TEXT,
    subs_approx INTEGER,
    description_snippet TEXT,
    found_via TEXT,
    source_type TEXT,
    discovered_at TEXT,
    enrichment_status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT,
    source_type TEXT,
    channels_found INTEGER,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS url_cache (
    url TEXT PRIMARY KEY,
    response_text TEXT,
    fetched_at TEXT,
    status_code INTEGER
);

CREATE TABLE IF NOT EXISTS channel_enriched (
    channel_id TEXT PRIMARY KEY,
    handle TEXT,
    title TEXT,
    url TEXT,
    description TEXT,
    country TEXT,
    joined_date TEXT,
    subs INTEGER,
    total_views INTEGER,
    email TEXT,
    external_links TEXT,
    language TEXT,
    median_views_20 INTEGER,
    recency_days INTEGER,
    upload_freq_30d INTEGER,
    shorts_share REAL,
    view_sub_ratio REAL,
    relevance_pass BOOLEAN,
    matched_hard_keywords TEXT,
    matched_soft_keywords TEXT,
    negative_hits TEXT,
    classification TEXT,
    score_total INTEGER,
    score_relevance INTEGER,
    score_performance INTEGER,
    score_outreach INTEGER,
    found_via TEXT,
    enriched_at TEXT,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT,
    title TEXT,
    published_text TEXT,
    published_approx DATE,
    views INTEGER,
    is_short BOOLEAN,
    fetched_at TEXT,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);
"""


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open or reuse a SQLite connection. WAL mode for crash-safety."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    log.info("Database schema initialized")


# ── Channel upserts ──────────────────────────────────────────


def upsert_channel(conn: sqlite3.Connection, channel_id: str, handle: str,
                   title: str, url: str, subs_approx: int,
                   description_snippet: str, found_via: str,
                   source_type: str) -> bool:
    """
    Insert or update a discovered channel.
    Returns True if new, False if existing (found_via merged).
    """
    row = conn.execute(
        "SELECT channel_id, found_via FROM channels WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()

    now = datetime.utcnow().isoformat()

    if row is None:
        conn.execute(
            """INSERT INTO channels
               (channel_id, handle, title, url, subs_approx,
                description_snippet, found_via, source_type, discovered_at, enrichment_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (channel_id, handle, title, url, subs_approx,
             description_snippet, found_via, source_type, now),
        )
        conn.commit()
        return True

    # Merge found_via
    existing_via = row["found_via"] or ""
    existing_set = {v.strip() for v in existing_via.split(",") if v.strip()}
    new_set = {v.strip() for v in found_via.split(",") if v.strip()}
    merged = ", ".join(sorted(existing_set | new_set))

    if merged != existing_via:
        conn.execute(
            "UPDATE channels SET found_via = ? WHERE channel_id = ?",
            (merged, channel_id),
        )
        conn.commit()
    return False


def record_discovery_run(conn: sqlite3.Connection, query: str,
                         source_type: str, channels_found: int,
                         started_at: str, finished_at: str) -> None:
    """Record a completed discovery run."""
    conn.execute(
        """INSERT INTO discovery_runs (query, source_type, channels_found, started_at, finished_at)
           VALUES (?, ?, ?, ?, ?)""",
        (query, source_type, channels_found, started_at, finished_at),
    )
    conn.commit()


def is_query_completed(conn: sqlite3.Connection, query: str, source_type: str) -> bool:
    """Check if a query+source_type combination has already been completed."""
    row = conn.execute(
        "SELECT id FROM discovery_runs WHERE query = ? AND source_type = ?",
        (query, source_type),
    ).fetchone()
    return row is not None


# ── URL cache ────────────────────────────────────────────────


def get_cached_response(conn: sqlite3.Connection, url: str,
                        ttl_hours: int = 24) -> str | None:
    """Return cached response_text if exists and not expired."""
    row = conn.execute(
        "SELECT response_text, fetched_at FROM url_cache WHERE url = ?",
        (url,),
    ).fetchone()
    if row is None:
        return None

    fetched_at = datetime.fromisoformat(row["fetched_at"])
    age_hours = (datetime.utcnow() - fetched_at).total_seconds() / 3600
    if age_hours > ttl_hours:
        return None

    return row["response_text"]


def store_cached_response(conn: sqlite3.Connection, url: str,
                          response_text: str, status_code: int) -> None:
    """Store or replace a cached response."""
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO url_cache (url, response_text, fetched_at, status_code)
           VALUES (?, ?, ?, ?)""",
        (url, response_text, now, status_code),
    )
    conn.commit()


# ── Enrichment upserts ───────────────────────────────────────


def upsert_enriched(conn: sqlite3.Connection, data: dict) -> None:
    """Insert or replace enriched channel data."""
    conn.execute(
        """INSERT OR REPLACE INTO channel_enriched
           (channel_id, handle, title, url, description, country,
            joined_date, subs, total_views, email, external_links,
            language, median_views_20, recency_days, upload_freq_30d,
            shorts_share, view_sub_ratio, relevance_pass,
            matched_hard_keywords, matched_soft_keywords, negative_hits,
            classification, score_total, score_relevance, score_performance,
            score_outreach, found_via, enriched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["channel_id"], data.get("handle", ""), data.get("title", ""),
            data.get("url", ""), data.get("description", ""),
            data.get("country", ""), data.get("joined_date", ""),
            data.get("subs", 0), data.get("total_views", 0),
            data.get("email", ""), data.get("external_links", ""),
            data.get("language", ""),
            data.get("median_views_20", 0), data.get("recency_days"),
            data.get("upload_freq_30d", 0), data.get("shorts_share", 0.0),
            data.get("view_sub_ratio"), data.get("relevance_pass", False),
            data.get("matched_hard_keywords", ""),
            data.get("matched_soft_keywords", ""),
            data.get("negative_hits", ""), data.get("classification", ""),
            data.get("score_total", 0), data.get("score_relevance", 0),
            data.get("score_performance", 0), data.get("score_outreach", 0),
            data.get("found_via", ""),
            data.get("enriched_at", datetime.utcnow().isoformat()),
        ),
    )
    conn.commit()


def upsert_video(conn: sqlite3.Connection, video_id: str, channel_id: str,
                 title: str, published_text: str, published_approx: str | None,
                 views: int, is_short: bool) -> None:
    """Insert or replace a video record."""
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO videos
           (video_id, channel_id, title, published_text, published_approx, views, is_short, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, channel_id, title, published_text, published_approx, views, is_short, now),
    )
    conn.commit()


def update_channel_enrichment_status(conn: sqlite3.Connection,
                                     channel_id: str, status: str) -> None:
    """Update enrichment_status in the channels table."""
    conn.execute(
        "UPDATE channels SET enrichment_status = ? WHERE channel_id = ?",
        (status, channel_id),
    )
    conn.commit()


# ── Query helpers ────────────────────────────────────────────


def get_pending_channels(conn: sqlite3.Connection, limit: int = 0) -> list[dict]:
    """Get channels with enrichment_status='pending'."""
    sql = """SELECT channel_id, handle, title, url, subs_approx,
                    description_snippet, found_via, source_type
             FROM channels WHERE enrichment_status = 'pending'
             ORDER BY subs_approx DESC"""
    if limit > 0:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_enriched_by_classification(conn: sqlite3.Connection,
                                   classification: str) -> list[dict]:
    """Get enriched channels by classification."""
    rows = conn.execute(
        """SELECT * FROM channel_enriched
           WHERE classification = ?
           ORDER BY score_total DESC""",
        (classification,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_enriched(conn: sqlite3.Connection) -> list[dict]:
    """Get all enriched channels."""
    rows = conn.execute(
        "SELECT * FROM channel_enriched ORDER BY score_total DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_videos_for_channel(conn: sqlite3.Connection,
                           channel_id: str) -> list[dict]:
    """Get all videos for a channel, newest first."""
    rows = conn.execute(
        """SELECT * FROM videos WHERE channel_id = ?
           ORDER BY published_approx DESC, fetched_at DESC""",
        (channel_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_channel_count(conn: sqlite3.Connection) -> int:
    """Total discovered channels."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM channels").fetchone()
    return row["cnt"]


def get_enriched_count(conn: sqlite3.Connection) -> int:
    """Total enriched channels."""
    row = conn.execute("SELECT COUNT(*) as cnt FROM channel_enriched").fetchone()
    return row["cnt"]


def get_discovery_stats(conn: sqlite3.Connection) -> dict:
    """Summary statistics."""
    total = get_channel_count(conn)
    enriched = get_enriched_count(conn)
    pending = conn.execute(
        "SELECT COUNT(*) as cnt FROM channels WHERE enrichment_status = 'pending'"
    ).fetchone()["cnt"]

    classifications = {}
    rows = conn.execute(
        "SELECT classification, COUNT(*) as cnt FROM channel_enriched GROUP BY classification"
    ).fetchall()
    for r in rows:
        classifications[r["classification"]] = r["cnt"]

    return {
        "total_discovered": total,
        "total_enriched": enriched,
        "pending": pending,
        "classifications": classifications,
    }


# ── Backup / restore ─────────────────────────────────────────


def backup_db(db_path: str | None = None, label: str = "auto") -> str | None:
    """
    Create a timestamped backup copy of the database file.
    Returns the backup path, or None if source db doesn't exist / is empty.
    """
    path = db_path or DB_PATH
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        log.info("No database to back up (missing or empty)")
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    basename = os.path.splitext(os.path.basename(path))[0]
    backup_name = f"{basename}_{label}_{ts}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)

    # Use SQLite's online backup API for a safe, consistent copy
    src = sqlite3.connect(path)
    dst = sqlite3.connect(backup_path)
    src.backup(dst)
    dst.close()
    src.close()

    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    log.info(f"Backup saved: {backup_path} ({size_mb:.1f} MB)")

    # Keep only the last 10 backups to avoid disk bloat
    _prune_old_backups(basename)
    return backup_path


def _prune_old_backups(basename: str, keep: int = 10) -> None:
    """Remove oldest backups beyond the keep limit."""
    if not os.path.isdir(BACKUP_DIR):
        return
    files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith(basename) and f.endswith(".db")],
        key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)),
        reverse=True,
    )
    for old in files[keep:]:
        os.remove(os.path.join(BACKUP_DIR, old))
        log.info(f"Pruned old backup: {old}")


def restore_latest_backup(db_path: str | None = None) -> bool:
    """
    If the main db file is missing or empty, restore from the latest backup.
    Returns True if a restore happened.
    """
    path = db_path or DB_PATH
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return False  # DB is fine, nothing to restore

    if not os.path.isdir(BACKUP_DIR):
        return False

    basename = os.path.splitext(os.path.basename(path))[0]
    files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith(basename) and f.endswith(".db")],
        key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)),
        reverse=True,
    )
    if not files:
        return False

    latest = os.path.join(BACKUP_DIR, files[0])
    if os.path.getsize(latest) == 0:
        return False

    shutil.copy2(latest, path)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    log.warning(f"DATABASE RESTORED from backup: {latest} ({size_mb:.1f} MB)")
    return True

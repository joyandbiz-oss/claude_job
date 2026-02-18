#!/usr/bin/env python3
"""
Stage 3: Export — generate CSV files from SQLite enriched data.

Outputs:
  1. creators_for_outreach.csv     — CREATOR with score >= min_score
  2. companies_for_partnership.csv — COMPANY channels
  3. competitors_monitor.csv       — COMPETITOR channels
  4. rejected_channels_log.csv     — REJECTED or below threshold

Usage:
  python export_lists.py --config config.yaml
  python export_lists.py --config config.yaml --output-dir ./output
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime

from lib.config import load_config
from lib.db import (
    get_connection, init_schema, get_enriched_by_classification,
    get_all_enriched, get_videos_for_channel, get_discovery_stats,
)

log = logging.getLogger("export")

CSV_COLUMNS = [
    "channel_id", "handle", "url", "title", "country", "subs",
    "median_views_20", "upload_freq_30d", "recency_days", "shorts_share",
    "view_sub_ratio", "email", "external_links", "relevance_pass",
    "classification", "score_total", "score_relevance", "score_performance",
    "score_outreach", "found_via", "matched_hard_keywords",
    "matched_soft_keywords", "negative_hits", "recent_video_titles",
    "language",
]


def get_recent_video_titles(db_conn, channel_id: str, limit: int = 5) -> str:
    """Get last N video titles for a channel, pipe-separated."""
    videos = get_videos_for_channel(db_conn, channel_id)
    titles = [v["title"] for v in videos[:limit] if v.get("title")]
    return " | ".join(titles)


def channel_to_row(ch: dict, db_conn) -> dict:
    """Convert enriched channel dict to CSV row dict."""
    channel_id = ch.get("channel_id", "")
    recent_titles = get_recent_video_titles(db_conn, channel_id)

    return {
        "channel_id": channel_id,
        "handle": ch.get("handle", ""),
        "url": ch.get("url", ""),
        "title": ch.get("title", ""),
        "country": ch.get("country", ""),
        "subs": ch.get("subs", 0),
        "median_views_20": ch.get("median_views_20", 0),
        "upload_freq_30d": ch.get("upload_freq_30d", 0),
        "recency_days": ch.get("recency_days", ""),
        "shorts_share": ch.get("shorts_share", 0),
        "view_sub_ratio": ch.get("view_sub_ratio", ""),
        "email": ch.get("email", ""),
        "external_links": ch.get("external_links", ""),
        "relevance_pass": ch.get("relevance_pass", False),
        "classification": ch.get("classification", ""),
        "score_total": ch.get("score_total", 0),
        "score_relevance": ch.get("score_relevance", 0),
        "score_performance": ch.get("score_performance", 0),
        "score_outreach": ch.get("score_outreach", 0),
        "found_via": ch.get("found_via", ""),
        "matched_hard_keywords": ch.get("matched_hard_keywords", ""),
        "matched_soft_keywords": ch.get("matched_soft_keywords", ""),
        "negative_hits": ch.get("negative_hits", ""),
        "recent_video_titles": recent_titles,
        "language": ch.get("language", ""),
    }


def write_csv(filepath: str, rows: list[dict], columns: list[str]) -> int:
    """Write rows to CSV. Returns count of rows written."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Stage 3: Export enriched channels to CSV files"
    )
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (overrides config)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable DEBUG logging")
    parser.add_argument("--db", default="discovery.db",
                        help="SQLite database path")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(args.config)
    db_conn = get_connection(args.db)
    init_schema(db_conn)

    export_cfg = cfg.get("export", {})
    output_dir = args.output_dir or export_cfg.get("output_dir", "./output")
    timestamp_files = export_cfg.get("timestamp_files", True)
    min_score = cfg.get("thresholds", {}).get("min_score_outreach", 30)

    # Create output dir
    os.makedirs(output_dir, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    suffix = f"_{today}" if timestamp_files else ""

    print("=" * 70)
    print("  DataImpulse YouTube Influencer Discovery V3 — Stage 3: Export")
    print(f"  Date: {today}")
    print(f"  Output: {output_dir}")
    print(f"  Min score for outreach: {min_score}")
    print("=" * 70)

    # Get data by classification
    creators = get_enriched_by_classification(db_conn, "CREATOR")
    companies = get_enriched_by_classification(db_conn, "COMPANY")
    competitors = get_enriched_by_classification(db_conn, "COMPETITOR")
    rejected = get_enriched_by_classification(db_conn, "REJECTED")

    # Also add creators with score below threshold to rejected
    creators_outreach = [c for c in creators if c.get("score_total", 0) >= min_score]
    creators_below = [c for c in creators if c.get("score_total", 0) < min_score]

    # File 1: Creators for outreach (sorted by score DESC)
    fname1 = os.path.join(output_dir, f"creators_for_outreach{suffix}.csv")
    rows1 = [channel_to_row(c, db_conn) for c in creators_outreach]
    count1 = write_csv(fname1, rows1, CSV_COLUMNS)
    print(f"\n  {fname1}")
    print(f"    -> {count1} creators (score >= {min_score})")

    # File 2: Companies for partnership
    fname2 = os.path.join(output_dir, f"companies_for_partnership{suffix}.csv")
    rows2 = [channel_to_row(c, db_conn) for c in companies]
    count2 = write_csv(fname2, rows2, CSV_COLUMNS)
    print(f"\n  {fname2}")
    print(f"    -> {count2} companies")

    # File 3: Competitors monitor
    fname3 = os.path.join(output_dir, f"competitors_monitor{suffix}.csv")
    rows3 = [channel_to_row(c, db_conn) for c in competitors]
    count3 = write_csv(fname3, rows3, CSV_COLUMNS)
    print(f"\n  {fname3}")
    print(f"    -> {count3} competitors")

    # File 4: Rejected channels log
    fname4 = os.path.join(output_dir, f"rejected_channels_log{suffix}.csv")
    all_rejected = rejected + creators_below
    rows4 = [channel_to_row(c, db_conn) for c in all_rejected]
    count4 = write_csv(fname4, rows4, CSV_COLUMNS)
    print(f"\n  {fname4}")
    print(f"    -> {count4} rejected ({len(rejected)} relevance-rejected, "
          f"{len(creators_below)} below score threshold)")

    # ── Summary ──────────────────────────────────────────────
    total = count1 + count2 + count3 + count4
    stats = get_discovery_stats(db_conn)

    print(f"\n{'='*70}")
    print("  EXPORT SUMMARY")
    print(f"{'='*70}")
    print(f"  Total channels in DB:        {stats['total_discovered']}")
    print(f"  Total enriched:              {stats['total_enriched']}")
    print(f"  Total exported:              {total}")
    print(f"    Creators for outreach:     {count1}")
    print(f"    Companies for partnership: {count2}")
    print(f"    Competitors to monitor:    {count3}")
    print(f"    Rejected/below threshold:  {count4}")

    # Top 20 creators preview
    if rows1:
        print(f"\n  Top 20 Creators for Outreach:")
        header = (f"  {'#':<3} {'Handle':<25} {'Subs':>10} {'Med.Views':>10} "
                  f"{'Score':>6} {'Lang':<6} {'Email':>5}")
        print(header)
        print(f"  {'─'*3} {'─'*25} {'─'*10} {'─'*10} {'─'*6} {'─'*6} {'─'*5}")
        for i, row in enumerate(rows1[:20]):
            handle = str(row.get("handle", ""))[:25]
            subs = row.get("subs", 0)
            median = row.get("median_views_20", 0)
            score = row.get("score_total", 0)
            lang = str(row.get("language", ""))[:6]
            has_email = "Yes" if row.get("email") else "No"
            print(f"  {i+1:<3} {handle:<25} {subs:>10,} {median:>10,} "
                  f"{score:>6} {lang:<6} {has_email:>5}")

    print(f"\n{'='*70}")
    print("  Export complete!")
    print(f"{'='*70}")

    db_conn.close()


if __name__ == "__main__":
    main()

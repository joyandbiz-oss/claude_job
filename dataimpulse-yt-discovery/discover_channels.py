#!/usr/bin/env python3
"""
Stage 1: Discovery — collect as many candidate channels as possible.

Sources:
  1. YouTube Channel Search (sp=EgIQAg==) with continuation pagination
  2. YouTube Video Search → extract author channel info
  3. Seed channel expansion (related channels + re-search top video titles)

Usage:
  python discover_channels.py --config config.yaml
  python discover_channels.py --config config.yaml --tier tier1_core
  python discover_channels.py --config config.yaml --resume
  python discover_channels.py --self-check
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from urllib.parse import quote_plus

from lib.config import load_config, get_queries_for_tier
from lib.db import (
    get_connection, init_schema, upsert_channel, record_discovery_run,
    is_query_completed, get_channel_count, backup_db, restore_latest_backup,
)
from lib.youtube_fetch import YouTubeFetcher
from lib.youtube_parse import (
    extract_yt_initial_data, extract_innertube_context,
    extract_continuation_token, parse_channel_renderers,
    parse_channel_renderers_continuation, parse_video_renderers,
    parse_video_renderers_continuation, parse_related_channels,
    parse_channel_videos, parse_channel_handle_from_page,
)

log = logging.getLogger("discover")

# ── Self-check ───────────────────────────────────────────────


def run_self_check(cfg: dict) -> bool:
    """Fetch 1 known channel, parse ytInitialData, print OK/FAIL."""
    print("=" * 60)
    print("  Self-check: testing YouTube fetch + parse pipeline")
    print("=" * 60)

    db_conn = get_connection(":memory:")
    init_schema(db_conn)
    fetcher = YouTubeFetcher(cfg, db_conn)

    # Test 1: Fetch a known channel page
    print("\n[1/3] Fetching @Fireship channel page...", end=" ", flush=True)
    html = fetcher.fetch("https://www.youtube.com/@Fireship", use_cache=False)
    if not html:
        print("FAIL — could not fetch page")
        return False
    print(f"OK ({len(html):,} bytes)")

    # Test 2: Parse ytInitialData
    print("[2/3] Parsing ytInitialData...", end=" ", flush=True)
    data = extract_yt_initial_data(html)
    if not data:
        print("FAIL — could not extract ytInitialData")
        return False
    print("OK")

    # Test 3: Extract channel metadata
    print("[3/3] Extracting channel metadata...", end=" ", flush=True)
    metadata = data.get("metadata", {}).get("channelMetadataRenderer", {})
    title = metadata.get("title", "")
    if not title:
        print("FAIL — no title in metadata")
        return False
    print(f"OK — title: '{title}'")

    # Test 4: Search
    print("\n[bonus] Testing channel search for 'web scraping tutorial'...", end=" ", flush=True)
    search_url = "https://www.youtube.com/results?search_query=web+scraping+tutorial&sp=EgIQAg%3D%3D"
    html2 = fetcher.fetch(search_url, use_cache=False)
    if html2:
        data2 = extract_yt_initial_data(html2)
        if data2:
            channels = parse_channel_renderers(data2)
            print(f"OK — found {len(channels)} channels")
        else:
            print("WARN — could not parse search results")
    else:
        print("WARN — could not fetch search page")

    stats = fetcher.get_stats()
    print(f"\nFetcher stats: {stats}")
    print("\n  Self-check PASSED")
    return True


# ── Source 1: Channel search with pagination ─────────────────


def discover_channel_search(fetcher: YouTubeFetcher, db_conn, query: str,
                            pages: int = 4, min_subs: int = 300) -> int:
    """
    Search YouTube for channels (sp=EgIQAg==), with continuation pagination.
    Returns count of new channels inserted.
    """
    encoded = quote_plus(query)
    url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAg%3D%3D"

    html = fetcher.fetch(url)
    if not html:
        return 0

    data = extract_yt_initial_data(html)
    if not data:
        return 0

    # Parse first page
    channels = parse_channel_renderers(data)
    new_count = _store_channels(db_conn, channels, query, "channel_search", min_subs)

    # Extract INNERTUBE context for continuation
    api_key, innertube_ctx = extract_innertube_context(html)
    if not api_key:
        log.debug("No INNERTUBE_API_KEY found, skipping continuation for: %s", query)
        return new_count

    # Continuation pages
    cont_token = extract_continuation_token(data)
    for page in range(2, pages + 1):
        if not cont_token:
            log.debug("No continuation token for page %d of query: %s", page, query)
            break

        payload = {
            "context": innertube_ctx,
            "continuation": cont_token,
        }
        cont_url = f"https://www.youtube.com/youtubei/v1/search?key={api_key}"
        cont_data = fetcher.post_json(cont_url, payload)
        if not cont_data:
            break

        cont_channels = parse_channel_renderers_continuation(cont_data)
        new_count += _store_channels(db_conn, cont_channels, query, "channel_search", min_subs)

        cont_token = extract_continuation_token(cont_data)

    return new_count


# ── Source 2: Video search → extract authors ─────────────────


def discover_video_search(fetcher: YouTubeFetcher, db_conn, query: str,
                          pages: int = 3, min_subs: int = 300) -> int:
    """
    Search YouTube for videos (default), extract author channel info.
    Returns count of new channels inserted.
    """
    encoded = quote_plus(query)
    url = f"https://www.youtube.com/results?search_query={encoded}"

    html = fetcher.fetch(url)
    if not html:
        return 0

    data = extract_yt_initial_data(html)
    if not data:
        return 0

    # Parse first page video results
    channels = parse_video_renderers(data)
    new_count = _store_channels(db_conn, channels, query, "video_search", min_subs)

    # Continuation pages
    api_key, innertube_ctx = extract_innertube_context(html)
    if not api_key:
        return new_count

    cont_token = extract_continuation_token(data)
    for page in range(2, pages + 1):
        if not cont_token:
            break

        payload = {
            "context": innertube_ctx,
            "continuation": cont_token,
        }
        cont_url = f"https://www.youtube.com/youtubei/v1/search?key={api_key}"
        cont_data = fetcher.post_json(cont_url, payload)
        if not cont_data:
            break

        cont_channels = parse_video_renderers_continuation(cont_data)
        new_count += _store_channels(db_conn, cont_channels, query, "video_search", min_subs)

        cont_token = extract_continuation_token(cont_data)

    return new_count


# ── Source 3: Seed channel expansion ─────────────────────────


def discover_seed_expansion(fetcher: YouTubeFetcher, db_conn,
                            seed_handle: str, min_subs: int = 300) -> int:
    """
    For a seed channel:
    1. Visit their page and extract related/featured channels
    2. Extract top video titles to use as search queries
    Returns count of new channels inserted.
    """
    new_count = 0

    # Fetch the seed channel page
    url = f"https://www.youtube.com/{seed_handle}"
    html = fetcher.fetch(url)
    if not html:
        return 0

    data = extract_yt_initial_data(html)
    if not data:
        return 0

    # Extract related/featured channels from sidebar
    related = parse_related_channels(data)
    if related:
        new_count += _store_channels(
            db_conn, related, f"seed:{seed_handle}", "seed_expansion", min_subs
        )
        log.info("Found %d related channels for %s", len(related), seed_handle)

    # Fetch /videos tab for video titles
    vid_url = f"https://www.youtube.com/{seed_handle}/videos"
    vid_html = fetcher.fetch(vid_url)
    if vid_html:
        vid_data = extract_yt_initial_data(vid_html)
        if vid_data:
            videos = parse_channel_videos(vid_data)
            # Use top 3 video titles as search queries
            for vid in videos[:3]:
                title = vid.get("title", "").strip()
                if len(title) > 10:
                    # Quick video search with this title
                    seed_new = discover_video_search(
                        fetcher, db_conn, title, pages=1, min_subs=min_subs
                    )
                    new_count += seed_new

    return new_count


# ── Storage helper ───────────────────────────────────────────


def _store_channels(db_conn, channels: list[dict], query: str,
                    source_type: str, min_subs: int) -> int:
    """Store discovered channels in SQLite. Returns count of new channels."""
    new_count = 0
    for ch in channels:
        channel_id = ch.get("channel_id", "")
        if not channel_id:
            continue

        subs = ch.get("subs_approx", 0)
        # Early filter: skip very low sub counts (but allow 0 = unknown)
        if 0 < subs < min_subs:
            continue

        handle = ch.get("handle", "")
        title = ch.get("title", "")
        url = f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{channel_id}"

        is_new = upsert_channel(
            db_conn,
            channel_id=channel_id,
            handle=handle,
            title=title,
            url=url,
            subs_approx=subs,
            description_snippet=ch.get("description_snippet", ""),
            found_via=query,
            source_type=source_type,
        )
        if is_new:
            new_count += 1

    return new_count


# ── Main ─────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Stage 1: Discover YouTube channels relevant to DataImpulse"
    )
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml (default: config.yaml)")
    parser.add_argument("--tier", default=None,
                        help="Run only a specific query tier (e.g. tier1_core)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume: skip queries that already have results")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable DEBUG logging")
    parser.add_argument("--self-check", action="store_true",
                        help="Run self-check: test fetch + parse on 1 channel")
    parser.add_argument("--db", default="discovery.db",
                        help="SQLite database path (default: discovery.db)")
    args = parser.parse_args()

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(args.config)

    # Self-check mode
    if args.self_check:
        ok = run_self_check(cfg)
        sys.exit(0 if ok else 1)

    # Auto-restore from backup if db is missing/empty
    restore_latest_backup(args.db)

    # Init DB
    db_conn = get_connection(args.db)
    init_schema(db_conn)

    # Backup existing data before starting
    backup_db(args.db, label="pre_discovery")

    fetcher = YouTubeFetcher(cfg, db_conn)

    disc_cfg = cfg.get("discovery", {})
    pages_per_query = disc_cfg.get("pages_per_query", 4)
    min_subs = disc_cfg.get("min_subs_discovery", 300)

    print("=" * 70)
    print("  DataImpulse YouTube Influencer Discovery V3 — Stage 1: Discovery")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Database: {args.db}")
    print(f"  Pages per query: {pages_per_query}")
    print("=" * 70)

    # Get queries
    queries = get_queries_for_tier(cfg, args.tier)
    total_queries = len(queries)
    print(f"\n  Total search queries: {total_queries}")
    if args.tier:
        print(f"  Tier filter: {args.tier}")
    if args.resume:
        print("  Resume mode: ON (skipping completed queries)")

    # ── Source 1 + 2: Search queries ─────────────────────────
    print(f"\n{'='*70}")
    print("  [SOURCE 1+2] Channel Search + Video Search")
    print(f"{'='*70}")

    total_new = 0
    skipped = 0

    for idx, (query, tier_name) in enumerate(queries):
        prefix = f"[{idx+1}/{total_queries}]"

        # Check if already done (resume mode)
        if args.resume:
            if (is_query_completed(db_conn, query, "channel_search") and
                    is_query_completed(db_conn, query, "video_search")):
                skipped += 1
                if skipped <= 5 or skipped % 20 == 0:
                    print(f"  {prefix} SKIP (done): {query}")
                continue

        print(f"  {prefix} [{tier_name}] {query}", end="", flush=True)

        # Source 1: Channel search
        started = datetime.utcnow().isoformat()
        ch_new = 0
        if not (args.resume and is_query_completed(db_conn, query, "channel_search")):
            ch_new = discover_channel_search(
                fetcher, db_conn, query, pages=pages_per_query, min_subs=min_subs
            )
            record_discovery_run(
                db_conn, query, "channel_search", ch_new,
                started, datetime.utcnow().isoformat()
            )

        # Source 2: Video search
        vid_new = 0
        if not (args.resume and is_query_completed(db_conn, query, "video_search")):
            vid_new = discover_video_search(
                fetcher, db_conn, query, pages=3, min_subs=min_subs
            )
            record_discovery_run(
                db_conn, query, "video_search", vid_new,
                started, datetime.utcnow().isoformat()
            )

        query_new = ch_new + vid_new
        total_new += query_new
        total_db = get_channel_count(db_conn)
        print(f"  -> +{query_new} new (ch:{ch_new} vid:{vid_new}) | total: {total_db}")

    if skipped > 0:
        print(f"\n  Skipped {skipped} already-completed queries (resume mode)")
    print(f"  New channels from search: {total_new}")

    # ── Source 3: Seed channel expansion ─────────────────────
    seed_channels = cfg.get("seed_channels", [])
    if seed_channels:
        print(f"\n{'='*70}")
        print(f"  [SOURCE 3] Seed Channel Expansion ({len(seed_channels)} seeds)")
        print(f"{'='*70}")

        seed_new_total = 0
        for idx, handle in enumerate(seed_channels):
            handle = handle.strip()
            if not handle.startswith("@"):
                handle = "@" + handle

            # Skip if already processed (resume mode)
            seed_query = f"seed:{handle}"
            if args.resume and is_query_completed(db_conn, seed_query, "seed_expansion"):
                if idx < 5 or idx % 20 == 0:
                    print(f"  [{idx+1}/{len(seed_channels)}] SKIP (done): {handle}")
                continue

            print(f"  [{idx+1}/{len(seed_channels)}] Expanding: {handle}", end="", flush=True)

            started = datetime.utcnow().isoformat()
            seed_new = discover_seed_expansion(
                fetcher, db_conn, handle, min_subs=min_subs
            )
            record_discovery_run(
                db_conn, seed_query, "seed_expansion", seed_new,
                started, datetime.utcnow().isoformat()
            )
            seed_new_total += seed_new
            print(f"  -> +{seed_new} new")

        print(f"\n  New channels from seed expansion: {seed_new_total}")
        total_new += seed_new_total

    # ── Summary ──────────────────────────────────────────────
    total_db = get_channel_count(db_conn)
    stats = fetcher.get_stats()

    print(f"\n{'='*70}")
    print("  DISCOVERY COMPLETE")
    print(f"{'='*70}")
    print(f"  Total channels in database: {total_db}")
    print(f"  New channels this run:      {total_new}")
    print(f"  HTTP requests made:         {stats['requests']}")
    print(f"  Cache hits:                 {stats['cache_hits']}")
    print(f"  Retries:                    {stats['retries']}")
    print(f"  Proxy switches:             {stats['proxy_switches']}")
    print(f"\n  Next step: python enrich_and_score.py --config {args.config}")
    print(f"{'='*70}")

    # Backup after discovery completes
    backup_db(args.db, label="post_discovery")

    db_conn.close()


if __name__ == "__main__":
    main()

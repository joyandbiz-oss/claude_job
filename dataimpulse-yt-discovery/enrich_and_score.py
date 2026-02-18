#!/usr/bin/env python3
"""
Stage 2: Enrichment + Scoring — enrich each channel with real metrics,
compute robust scores, classify, and store results in SQLite.

For each pending channel:
  1. Fetch /@handle/about → description, country, subs, links, email
  2. Fetch /@handle/videos → last 20 videos with views, dates, Shorts detection
  3. Compute metrics: median_views_20, recency_days, upload_freq_30d, shorts_share
  4. Relevance filtering (HARD + SOFT + NEGATIVE keywords)
  5. Classification: CREATOR / COMPANY / COMPETITOR / REJECTED
  6. Explainable score 0-100

Usage:
  python enrich_and_score.py --config config.yaml
  python enrich_and_score.py --config config.yaml --limit 100
  python enrich_and_score.py --config config.yaml --force-reenrich
"""

import argparse
import logging
import re
import statistics
import sys
from datetime import datetime, timedelta

from lib.config import load_config
from lib.db import (
    get_connection, init_schema, get_pending_channels,
    upsert_enriched, upsert_video, update_channel_enrichment_status,
    get_channel_count, get_enriched_count, get_discovery_stats,
)
from lib.youtube_fetch import YouTubeFetcher
from lib.youtube_parse import (
    extract_yt_initial_data, parse_channel_about,
    parse_channel_videos, detect_language,
)

log = logging.getLogger("enrich")

EMAIL_REGEX = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')


# ── Enrichment: fetch about + videos pages ───────────────────


def enrich_channel(fetcher: YouTubeFetcher, channel: dict) -> dict | None:
    """
    Fetch about page and videos page for a channel.
    Returns enriched data dict or None on failure.
    """
    handle = channel.get("handle", "")
    channel_id = channel.get("channel_id", "")

    if handle and handle.startswith("@"):
        base_url = f"https://www.youtube.com/{handle}"
    elif handle:
        base_url = f"https://www.youtube.com/@{handle}"
    else:
        base_url = f"https://www.youtube.com/channel/{channel_id}"

    result = {
        "channel_id": channel_id,
        "handle": handle,
        "title": channel.get("title", ""),
        "url": channel.get("url", base_url),
        "found_via": channel.get("found_via", ""),
    }

    # Page 1: About page
    about_url = base_url + "/about"
    about_html = fetcher.fetch(about_url)
    if about_html:
        about_data = extract_yt_initial_data(about_html)
        if about_data:
            about_info = parse_channel_about(about_data)
            result.update({
                "description": about_info.get("description", ""),
                "country": about_info.get("country", ""),
                "joined_date": about_info.get("joined_date", ""),
                "subs": about_info.get("subs", 0),
                "total_views": about_info.get("total_views", 0),
                "email": about_info.get("email", ""),
                "external_links": about_info.get("external_links", ""),
            })

            # Update handle if we found a better one
            page_handle = about_data.get("metadata", {}).get(
                "channelMetadataRenderer", {}
            ).get("vanityChannelUrl", "")
            if page_handle:
                m = re.search(r'/@([^/]+)', page_handle)
                if m:
                    result["handle"] = "@" + m.group(1)

            # Update title
            meta_title = about_data.get("metadata", {}).get(
                "channelMetadataRenderer", {}
            ).get("title", "")
            if meta_title:
                result["title"] = meta_title
        else:
            log.warning("Could not parse about page for %s", handle or channel_id)
            result.update({
                "description": "", "country": "", "joined_date": "",
                "subs": channel.get("subs_approx", 0), "total_views": 0,
                "email": "", "external_links": "",
            })
    else:
        log.warning("Could not fetch about page for %s", handle or channel_id)
        result.update({
            "description": "", "country": "", "joined_date": "",
            "subs": channel.get("subs_approx", 0), "total_views": 0,
            "email": "", "external_links": "",
        })

    # Also check description for additional emails
    if not result["email"] and result["description"]:
        emails = EMAIL_REGEX.findall(result["description"])
        filtered = [
            e for e in emails
            if not any(e.lower().endswith(ext) for ext in
                       ['.png', '.jpg', '.gif', '.svg', '.jpeg', '.webp'])
        ]
        if filtered:
            result["email"] = filtered[0]

    # Page 2: Videos page
    videos_url = base_url + "/videos"
    videos_html = fetcher.fetch(videos_url)
    videos = []
    if videos_html:
        vid_data = extract_yt_initial_data(videos_html)
        if vid_data:
            videos = parse_channel_videos(vid_data)

    result["videos"] = videos

    # Detect language
    result["language"] = detect_language(
        result.get("description", ""),
        result.get("country", ""),
    )

    return result


# ── Metrics computation ──────────────────────────────────────


def compute_metrics(enriched: dict) -> dict:
    """
    Compute performance metrics from the last 20 videos.
    Returns dict with: median_views_20, recency_days, upload_freq_30d,
    shorts_share, view_sub_ratio.
    """
    videos = enriched.get("videos", [])

    # View counts (exclude zeros for median)
    view_counts = [v["views"] for v in videos if v.get("views", 0) > 0]
    median_views = int(statistics.median(view_counts)) if view_counts else 0

    # Recency: days since most recent upload
    now = datetime.utcnow()
    recent_dates = []
    for v in videos:
        approx = v.get("published_approx")
        if approx:
            try:
                dt = datetime.strptime(approx, "%Y-%m-%d")
                recent_dates.append(dt)
            except ValueError:
                pass

    if recent_dates:
        most_recent = max(recent_dates)
        recency_days = (now - most_recent).days
    else:
        recency_days = None  # Unknown

    # Upload frequency: videos in last 30 days
    cutoff_30d = now - timedelta(days=30)
    upload_freq_30d = sum(1 for d in recent_dates if d >= cutoff_30d)

    # Shorts share
    total_vids = len(videos)
    shorts_count = sum(1 for v in videos if v.get("is_short"))
    shorts_share = shorts_count / total_vids if total_vids > 0 else 0.0

    # View/sub ratio
    subs = enriched.get("subs", 0)
    if subs and subs > 0 and median_views > 0:
        view_sub_ratio = median_views / subs
    else:
        view_sub_ratio = None

    return {
        "median_views_20": median_views,
        "recency_days": recency_days,
        "upload_freq_30d": upload_freq_30d,
        "shorts_share": round(shorts_share, 3),
        "view_sub_ratio": round(view_sub_ratio, 5) if view_sub_ratio is not None else None,
    }


# ── Relevance filtering ─────────────────────────────────────


def check_relevance(enriched: dict, cfg: dict) -> dict:
    """
    Apply HARD + SOFT + NEGATIVE keyword relevance filtering.
    Returns dict with: relevance_pass, matched_hard_keywords,
    matched_soft_keywords, negative_hits.
    """
    kw_cfg = cfg.get("keywords", {})
    hard_keywords = kw_cfg.get("hard", [])
    soft_keywords = kw_cfg.get("soft", [])
    use_case_hard = kw_cfg.get("use_case_hard", [])
    negative_keywords = kw_cfg.get("negative", [])

    description = (enriched.get("description", "") or "").lower()
    video_titles = " ".join(
        v.get("title", "") for v in enriched.get("videos", [])
    ).lower()
    channel_title = (enriched.get("title", "") or "").lower()

    # Combined text for keyword matching
    all_text = f"{description} {video_titles} {channel_title}"

    # Match hard keywords
    hard_matches = [kw for kw in hard_keywords if kw.lower() in all_text]

    # Match soft keywords
    soft_matches = [kw for kw in soft_keywords if kw.lower() in all_text]

    # Match use_case_hard in video titles specifically
    use_case_matches = [kw for kw in use_case_hard if kw.lower() in video_titles]

    # Match negative keywords
    neg_matches = [kw for kw in negative_keywords if kw.lower() in all_text]

    # Decision logic
    relevance_pass = False

    # PASS if >= 1 HARD keyword found
    if len(hard_matches) >= 1:
        relevance_pass = True

    # PASS if >= 2 SOFT keywords + >= 1 USE_CASE_HARD in video titles
    elif len(soft_matches) >= 2 and len(use_case_matches) >= 1:
        relevance_pass = True

    # REJECT if >= 3 NEGATIVE hits AND zero HARD hits
    if len(neg_matches) >= 3 and len(hard_matches) == 0:
        relevance_pass = False

    return {
        "relevance_pass": relevance_pass,
        "matched_hard_keywords": ", ".join(hard_matches),
        "matched_soft_keywords": ", ".join(soft_matches),
        "negative_hits": ", ".join(neg_matches),
    }


# ── Classification ───────────────────────────────────────────


def classify_channel(enriched: dict, cfg: dict) -> str:
    """
    Classify channel as COMPETITOR, COMPANY, CREATOR, or REJECTED.
    """
    # Check relevance first
    if not enriched.get("relevance_pass", False):
        return "REJECTED"

    name_lower = (enriched.get("title", "") or "").lower()
    handle_lower = (enriched.get("handle", "") or "").lower().lstrip("@")
    desc_lower = (enriched.get("description", "") or "").lower()
    combined = f"{name_lower} {handle_lower} {desc_lower}"

    # COMPETITOR check
    competitor_subs = cfg.get("competitor_substrings", [])
    for sub in competitor_subs:
        if sub.lower() in combined:
            return "COMPETITOR"

    # COMPANY check
    known_companies = cfg.get("known_company_names", [])
    for company in known_companies:
        if company.lower() == name_lower or company.lower() == handle_lower:
            return "COMPANY"

    company_signals = cfg.get("company_description_signals", [])
    threshold = cfg.get("company_signal_threshold", 2)
    signal_count = sum(1 for sig in company_signals if sig.lower() in desc_lower)
    if signal_count >= threshold:
        return "COMPANY"

    return "CREATOR"


# ── Scoring (0-100) ─────────────────────────────────────────


def compute_score(enriched: dict) -> dict:
    """
    Compute explainable score (0-100):
      relevance_score (0-50) + performance_score (0-30) + outreach_readiness (0-20)
    """
    # ── Relevance score (0-50) ───────────────────────────────
    hard_matches = enriched.get("matched_hard_keywords", "")
    soft_matches = enriched.get("matched_soft_keywords", "")
    neg_hits = enriched.get("negative_hits", "")

    hard_count = len([k for k in hard_matches.split(", ") if k.strip()]) if hard_matches else 0
    soft_count = len([k for k in soft_matches.split(", ") if k.strip()]) if soft_matches else 0
    neg_count = len([k for k in neg_hits.split(", ") if k.strip()]) if neg_hits else 0

    relevance = min(hard_count * 8, 40) + min(soft_count * 3, 15) - (neg_count * 5)
    relevance = max(0, min(relevance, 50))

    # ── Performance score (0-30) ─────────────────────────────
    performance = 0
    subs = enriched.get("subs", 0) or 0
    median_views = enriched.get("median_views_20", 0) or 0
    vsr = enriched.get("view_sub_ratio")
    upload_freq = enriched.get("upload_freq_30d", 0) or 0
    recency = enriched.get("recency_days")
    shorts_share = enriched.get("shorts_share", 0) or 0

    # Subscriber sweet spot
    if 10_000 <= subs <= 200_000:
        performance += 10
    elif (5_000 <= subs < 10_000) or (200_000 < subs <= 500_000):
        performance += 6
    elif (1_000 <= subs < 5_000) or (500_000 < subs <= 2_000_000):
        performance += 3

    # Median views
    if median_views >= 5_000:
        performance += 5
    elif median_views >= 1_000:
        performance += 3

    # View/sub ratio (engagement)
    if vsr is not None:
        if vsr >= 0.05:
            performance += 5
        elif vsr >= 0.01:
            performance += 3

    # Upload frequency
    if upload_freq >= 4:
        performance += 5
    elif upload_freq >= 2:
        performance += 3

    # Recency
    if recency is not None:
        if recency <= 14:
            performance += 5
        elif recency <= 30:
            performance += 3

    # Shorts penalty
    if shorts_share > 0.7:
        performance -= 5

    performance = max(0, min(performance, 30))

    # ── Outreach readiness (0-20) ────────────────────────────
    outreach = 0

    if enriched.get("email"):
        outreach += 10

    if enriched.get("external_links"):
        outreach += 3

    language = enriched.get("language", "")
    if language == "English":
        outreach += 5
    elif language in ("Spanish", "Portuguese", "French", "German", "Hindi"):
        outreach += 3

    outreach = min(outreach, 20)

    # ── Total ────────────────────────────────────────────────
    total = relevance + performance + outreach

    return {
        "score_total": total,
        "score_relevance": relevance,
        "score_performance": performance,
        "score_outreach": outreach,
    }


# ── Main ─────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Stage 2: Enrich channels with metrics, score, and classify"
    )
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of channels to enrich (0 = all)")
    parser.add_argument("--force-reenrich", action="store_true",
                        help="Re-enrich already processed channels")
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
    fetcher = YouTubeFetcher(cfg, db_conn)

    thresholds = cfg.get("thresholds", {})
    min_subs = thresholds.get("min_subs", 500)

    print("=" * 70)
    print("  DataImpulse YouTube Influencer Discovery V3 — Stage 2: Enrichment")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Database: {args.db}")
    print("=" * 70)

    # Get channels to enrich
    if args.force_reenrich:
        # Reset all to pending
        db_conn.execute("UPDATE channels SET enrichment_status = 'pending'")
        db_conn.commit()
        print("  Force re-enrich: all channels reset to pending")

    pending = get_pending_channels(db_conn, args.limit)
    total = len(pending)

    if total == 0:
        print("\n  No pending channels to enrich. Use --force-reenrich to reprocess.")
        stats = get_discovery_stats(db_conn)
        print(f"  Total discovered: {stats['total_discovered']}")
        print(f"  Total enriched: {stats['total_enriched']}")
        db_conn.close()
        return

    print(f"\n  Channels to enrich: {total}")
    if args.limit:
        print(f"  Limit: {args.limit}")

    # Counters
    enriched_count = 0
    creator_count = 0
    company_count = 0
    competitor_count = 0
    rejected_count = 0
    error_count = 0

    for idx, channel in enumerate(pending):
        channel_id = channel["channel_id"]
        handle = channel.get("handle", "") or channel_id[:20]
        title = channel.get("title", "")[:35]

        print(f"  [{idx+1}/{total}] Enriching {handle} ({title})", end="", flush=True)

        # Skip very low subs
        subs_approx = channel.get("subs_approx", 0) or 0
        if 0 < subs_approx < min_subs:
            update_channel_enrichment_status(db_conn, channel_id, "rejected")
            print(f"  -> SKIP ({subs_approx} subs < {min_subs})")
            rejected_count += 1
            continue

        # Enrich
        enriched = enrich_channel(fetcher, channel)
        if not enriched:
            update_channel_enrichment_status(db_conn, channel_id, "error")
            print("  -> ERROR (fetch failed)")
            error_count += 1
            continue

        # Re-check subs with real data
        real_subs = enriched.get("subs", 0)
        if 0 < real_subs < min_subs:
            update_channel_enrichment_status(db_conn, channel_id, "rejected")
            print(f"  -> SKIP ({real_subs} real subs < {min_subs})")
            rejected_count += 1
            continue

        # Compute metrics
        metrics = compute_metrics(enriched)
        enriched.update(metrics)

        # Relevance check
        relevance = check_relevance(enriched, cfg)
        enriched.update(relevance)

        # Classification
        classification = classify_channel(enriched, cfg)
        enriched["classification"] = classification

        # Score
        scores = compute_score(enriched)
        enriched.update(scores)

        enriched["enriched_at"] = datetime.utcnow().isoformat()

        # Store enriched data
        upsert_enriched(db_conn, enriched)

        # Store videos
        for v in enriched.get("videos", []):
            if v.get("video_id"):
                upsert_video(
                    db_conn,
                    video_id=v["video_id"],
                    channel_id=channel_id,
                    title=v.get("title", ""),
                    published_text=v.get("published_text", ""),
                    published_approx=v.get("published_approx"),
                    views=v.get("views", 0),
                    is_short=v.get("is_short", False),
                )

        # Update status
        status = "enriched" if classification != "REJECTED" else "rejected"
        update_channel_enrichment_status(db_conn, channel_id, status)

        # Count
        enriched_count += 1
        if classification == "CREATOR":
            creator_count += 1
        elif classification == "COMPANY":
            company_count += 1
        elif classification == "COMPETITOR":
            competitor_count += 1
        elif classification == "REJECTED":
            rejected_count += 1

        subs_display = f"{real_subs:,}" if real_subs else "?"
        score_display = scores["score_total"]
        print(f"  -> {classification} | score:{score_display} subs:{subs_display}")

        # Progress updates
        if (idx + 1) % 25 == 0:
            print(f"\n  --- Progress: {idx+1}/{total} enriched ---")
            print(f"      Creators: {creator_count} | Companies: {company_count} | "
                  f"Competitors: {competitor_count} | Rejected: {rejected_count} | "
                  f"Errors: {error_count}\n")

    # ── Summary ──────────────────────────────────────────────
    stats = fetcher.get_stats()

    print(f"\n{'='*70}")
    print("  ENRICHMENT COMPLETE")
    print(f"{'='*70}")
    print(f"  Channels processed:   {enriched_count}")
    print(f"  Creators:             {creator_count}")
    print(f"  Companies:            {company_count}")
    print(f"  Competitors:          {competitor_count}")
    print(f"  Rejected:             {rejected_count}")
    print(f"  Errors:               {error_count}")
    print(f"\n  HTTP requests:        {stats['requests']}")
    print(f"  Cache hits:           {stats['cache_hits']}")

    # Score distribution for creators
    rows = db_conn.execute(
        "SELECT score_total FROM channel_enriched WHERE classification = 'CREATOR' ORDER BY score_total DESC"
    ).fetchall()
    if rows:
        scores_list = [r["score_total"] for r in rows]
        s70 = sum(1 for s in scores_list if s >= 70)
        s50 = sum(1 for s in scores_list if 50 <= s < 70)
        s30 = sum(1 for s in scores_list if 30 <= s < 50)
        s_low = sum(1 for s in scores_list if s < 30)
        print(f"\n  Creator score distribution:")
        print(f"    Score 70+:  {s70}")
        print(f"    Score 50-69: {s50}")
        print(f"    Score 30-49: {s30}")
        print(f"    Score <30:  {s_low}")

    print(f"\n  Next step: python export_lists.py --config {args.config}")
    print(f"{'='*70}")

    db_conn.close()


if __name__ == "__main__":
    main()

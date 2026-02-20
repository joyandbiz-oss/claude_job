#!/usr/bin/env python3
"""
RSS Fetcher — парсит все фиды из feeds.yaml, фильтрует за N часов,
дедуплицирует, выводит JSON-массив статей.

Usage:
    python rss_fetcher.py [--hours 24] [--output articles.json]
"""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import aiohttp
import feedparser
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rss-fetcher")

SCRIPT_DIR = Path(__file__).resolve().parent
FEEDS_PATH = SCRIPT_DIR / "feeds.yaml"

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "mc_cid", "mc_eid",
    "oly_anon_id", "oly_enc_id", "vero_id", "__s", "ref", "source",
    "ncid", "sr_share",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)
        filtered = {k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS}
        clean_query = urlencode(filtered, doseq=True)
        return urlunparse((
            parsed.scheme, parsed.netloc.lower(),
            parsed.path.rstrip("/"), parsed.params, clean_query, "",
        ))
    except Exception:
        return url


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def parse_entry_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        tp = getattr(entry, attr, None)
        if tp:
            try:
                return datetime(*tp[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None


def extract_google_news_title(title: str) -> str:
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def clean_summary(entry) -> str:
    raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:1500]


def load_feeds() -> list[dict]:
    with open(FEEDS_PATH) as f:
        cfg = yaml.safe_load(f)
    feeds = []
    for tier in ("tier1_must_read", "tier2_industry", "tier3_background", "competitor_watch"):
        if tier not in cfg:
            continue
        for feed in cfg[tier].get("feeds", []):
            feed["tier"] = tier
            feeds.append(feed)
    return feeds


async def fetch_one(session: aiohttp.ClientSession, feed: dict,
                    cutoff: datetime) -> list[dict]:
    name = feed["name"]
    url = feed["url"]
    tier = feed.get("tier", "unknown")
    is_google = "news.google.com" in url

    headers = {"User-Agent": USER_AGENT}
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30),
                               headers=headers) as resp:
            if resp.status != 200:
                log.warning("%-35s HTTP %d", name, resp.status)
                return []
            body = await resp.text()
    except Exception as e:
        log.warning("%-35s FAIL: %s", name, e)
        return []

    parsed = feedparser.parse(body)
    articles = []
    for entry in parsed.entries:
        pub = parse_entry_date(entry)
        # If no date, treat as today (per spec)
        if pub is None:
            pub = datetime.now(timezone.utc)
        if pub < cutoff:
            continue

        link = getattr(entry, "link", None)
        if not link:
            continue

        title = getattr(entry, "title", "Untitled") or "Untitled"
        if is_google:
            title = extract_google_news_title(title)

        articles.append({
            "title": title,
            "url": link,
            "normalized_url": normalize_url(link),
            "url_hash": url_hash(link),
            "published": pub.isoformat(),
            "summary": clean_summary(entry),
            "source_name": name,
            "tier": tier,
            "competitor": feed.get("competitor"),
        })

    log.info("%-35s → %d articles", name, len(articles))
    return articles


async def fetch_all(feeds: list[dict], cutoff: datetime) -> list[dict]:
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_one(session, f, cutoff) for f in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    seen: set[str] = set()
    articles: list[dict] = []
    for result in results:
        if isinstance(result, Exception):
            log.warning("Task error: %s", result)
            continue
        for art in result:
            nurl = art["normalized_url"]
            if nurl not in seen:
                seen.add(nurl)
                articles.append(art)

    log.info("Total unique articles: %d", len(articles))
    return articles


def main():
    parser = argparse.ArgumentParser(description="RSS feed fetcher for LinkedIn Radar")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window (default 24)")
    parser.add_argument("--output", type=str, default="articles.json", help="Output file")
    args = parser.parse_args()

    feeds = load_feeds()
    log.info("Loaded %d feeds from feeds.yaml", len(feeds))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    log.info("Cutoff: %s (--hours %d)", cutoff.isoformat(), args.hours)

    articles = asyncio.run(fetch_all(feeds, cutoff))

    out_path = SCRIPT_DIR / args.output
    out_path.write_text(json.dumps(articles, indent=2, ensure_ascii=False))
    log.info("Saved %d articles to %s", len(articles), out_path)

    # Quick stats
    by_tier = {}
    for a in articles:
        by_tier[a["tier"]] = by_tier.get(a["tier"], 0) + 1
    for t, n in sorted(by_tier.items()):
        log.info("  %s: %d", t, n)

    return articles


if __name__ == "__main__":
    main()

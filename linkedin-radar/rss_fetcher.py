#!/usr/bin/env python3
"""
rss_fetcher.py — LinkedIn Radar v6
Fetches 105 RSS feeds with proxy fallback, ThreadPoolExecutor,
diagnostic output, and 72h window.

Usage:
    export PROXY_URL="http://user:pass@host:port"  # optional
    python rss_fetcher.py [--hours 72] [--output articles.json]
"""

import argparse
import hashlib
import json
import logging
import os
import re
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import ProxyHandler, Request, build_opener

import feedparser
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rss-fetcher")

SCRIPT_DIR = Path(__file__).resolve().parent
FEEDS_PATH = SCRIPT_DIR / "feeds.yaml"

# ── Proxy config ──────────────────────────────────────────────────────────────
PROXY_URL = os.environ.get("PROXY_URL", "")

# Domains that ALWAYS go through proxy
ALWAYS_PROXY = [
    "reddit.com",
]

# ── Mobile User-Agent (iPhone Safari) ─────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "mc_cid", "mc_eid",
    "oly_anon_id", "oly_enc_id", "vero_id", "__s", "ref", "source",
    "ncid", "sr_share",
}


# ── URL utilities ─────────────────────────────────────────────────────────────
def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)
        filtered = {k: v for k, v in params.items()
                    if k.lower() not in TRACKING_PARAMS}
        clean_query = urlencode(filtered, doseq=True)
        return urlunparse((
            parsed.scheme, parsed.netloc.lower(),
            parsed.path.rstrip("/"), parsed.params, clean_query, "",
        ))
    except Exception:
        return url


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


# ── Date parsing ──────────────────────────────────────────────────────────────
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


# ── Google News title cleanup ─────────────────────────────────────────────────
def extract_google_news_title(title: str) -> str:
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def clean_summary(entry) -> str:
    raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:1500]


# ── Proxy logic ───────────────────────────────────────────────────────────────
def should_always_proxy(url: str) -> bool:
    return any(domain in url for domain in ALWAYS_PROXY)


def fetch_feed_with_proxy(url: str, use_proxy: bool = False) -> bytes:
    """Fetch RSS feed content with optional proxy support."""
    if use_proxy and PROXY_URL:
        proxy_handler = ProxyHandler({
            "http": PROXY_URL,
            "https": PROXY_URL,
        })
        opener = build_opener(proxy_handler)
    else:
        opener = build_opener()

    req = Request(url)
    for k, v in HEADERS.items():
        req.add_header(k, v)

    # Create SSL context that doesn't verify (some proxies need this)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    response = opener.open(req, timeout=20)
    return response.read()


def fetch_with_fallback(url: str) -> tuple[bytes, str]:
    """Try direct first, fallback to proxy. Returns (content, method)."""
    if should_always_proxy(url):
        if PROXY_URL:
            content = fetch_feed_with_proxy(url, use_proxy=True)
            return content, "proxy"
        raise Exception("Proxy required but PROXY_URL not set")

    try:
        content = fetch_feed_with_proxy(url, use_proxy=False)
        return content, "direct"
    except Exception as e:
        err_str = str(e).lower()
        if any(code in err_str for code in ("403", "429", "blocked", "forbidden")):
            if PROXY_URL:
                content = fetch_feed_with_proxy(url, use_proxy=True)
                return content, "proxy_fallback"
        raise


# ── Feed loading ──────────────────────────────────────────────────────────────
def load_feeds() -> list[dict]:
    with open(FEEDS_PATH) as f:
        cfg = yaml.safe_load(f)
    feeds = []
    tiers = [
        "tier1_must_read", "tier2_industry", "tier3_background",
        "tier_biohacking", "competitor_watch",
    ]
    for tier in tiers:
        if tier not in cfg:
            continue
        for feed in cfg[tier].get("feeds", []):
            feed["tier"] = tier
            feeds.append(feed)
    return feeds


# ── Single feed fetch + parse ─────────────────────────────────────────────────
def fetch_one(feed: dict, cutoff: datetime) -> dict:
    """Fetch and parse one feed. Returns diagnostic result."""
    name = feed["name"]
    url = feed["url"]
    tier = feed.get("tier", "unknown")
    is_google = "news.google.com" in url

    result = {
        "name": name,
        "url": url,
        "tier": tier,
        "status": "error",
        "http_code": None,
        "method": "direct",
        "total_entries": 0,
        "entries_72h": 0,
        "error": None,
        "articles": [],
    }

    try:
        content, method = fetch_with_fallback(url)
        result["method"] = method
        result["http_code"] = 200
    except Exception as e:
        err = str(e)
        # Extract HTTP code if present
        for code in ("403", "404", "429", "500", "502", "503"):
            if code in err:
                result["http_code"] = int(code)
                break
        result["error"] = err[:200]
        return result

    parsed = feedparser.parse(content)
    result["total_entries"] = len(parsed.entries)

    articles = []
    for entry in parsed.entries:
        pub = parse_entry_date(entry)
        if pub is None:
            pub = datetime.now(timezone.utc)

        link = getattr(entry, "link", None)
        if not link:
            continue

        title = getattr(entry, "title", "Untitled") or "Untitled"
        if is_google:
            title = extract_google_news_title(title)

        if pub >= cutoff:
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

    result["entries_72h"] = len(articles)
    result["articles"] = articles
    result["status"] = "ok"

    return result


# ── Main fetch with ThreadPoolExecutor ────────────────────────────────────────
def fetch_all(feeds: list[dict], cutoff: datetime) -> tuple[list[dict], list[dict]]:
    """Fetch all feeds in parallel. Returns (articles, diagnostics)."""
    diagnostics = []
    all_articles = []

    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_feed = {
            executor.submit(fetch_one, feed, cutoff): feed
            for feed in feeds
        }
        for future in as_completed(future_to_feed):
            feed = future_to_feed[future]
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "name": feed["name"],
                    "url": feed["url"],
                    "tier": feed.get("tier", "unknown"),
                    "status": "error",
                    "http_code": None,
                    "method": "direct",
                    "total_entries": 0,
                    "entries_72h": 0,
                    "error": str(e)[:200],
                    "articles": [],
                }

            diag = {k: v for k, v in result.items() if k != "articles"}
            diagnostics.append(diag)

            status = result["status"]
            method = result["method"]
            n = result["entries_72h"]
            log.info(
                "%-35s %s %-15s → %d articles",
                result["name"], status.upper(), f"({method})", n,
            )

            all_articles.extend(result.get("articles", []))

    # Dedup by normalized URL
    seen = set()
    unique = []
    for art in all_articles:
        nurl = art["normalized_url"]
        if nurl not in seen:
            seen.add(nurl)
            unique.append(art)

    log.info("Total: %d raw → %d unique articles", len(all_articles), len(unique))
    return unique, diagnostics


# ── Diagnostic report ─────────────────────────────────────────────────────────
def write_diagnostic(diagnostics: list[dict], output_path: Path,
                     total_articles: int, unique_articles: int):
    """Write diagnostic markdown table."""
    lines = [
        "# LinkedIn Radar v6 — Feed Diagnostic",
        f"## Date: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Window: 72h",
        "",
        "| # | Feed | Tier | Status | HTTP | Method | Total | 72h | Error |",
        "|---|------|------|--------|------|--------|------:|----:|-------|",
    ]

    # Sort by tier then name
    diagnostics.sort(key=lambda d: (d["tier"], d["name"]))

    ok = proxy_used = errors = 0
    for i, d in enumerate(diagnostics, 1):
        status = d["status"]
        if status == "ok":
            ok += 1
        else:
            errors += 1
        if "proxy" in (d.get("method") or ""):
            proxy_used += 1

        error_short = (d.get("error") or "")[:60]
        lines.append(
            f"| {i} | {d['name']} | {d['tier'][:10]} | {status} "
            f"| {d.get('http_code') or '—'} | {d.get('method', '—')} "
            f"| {d['total_entries']} | {d['entries_72h']} | {error_short} |"
        )

    lines.extend([
        "",
        "## Summary",
        f"- Feeds OK: {ok}/{len(diagnostics)}",
        f"- Feeds errored: {errors}",
        f"- Feeds via proxy: {proxy_used}",
        f"- Total articles (raw): {total_articles}",
        f"- Unique articles: {unique_articles}",
    ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Diagnostic written to %s", output_path)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Radar v6 — RSS feed fetcher with proxy support"
    )
    parser.add_argument("--hours", type=int, default=72,
                        help="Lookback window in hours (default: 72)")
    parser.add_argument("--output", type=str, default="articles.json",
                        help="Output JSON file (default: articles.json)")
    parser.add_argument("--diagnostic", type=str, default="output/diagnostic.md",
                        help="Diagnostic output file")
    args = parser.parse_args()

    # Proxy info
    if PROXY_URL:
        # Mask credentials in log
        masked = re.sub(r"://[^@]+@", "://***:***@", PROXY_URL)
        log.info("Proxy configured: %s", masked)
    else:
        log.info("No proxy configured (set PROXY_URL env var)")

    feeds = load_feeds()
    log.info("Loaded %d feeds from feeds.yaml", len(feeds))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    log.info("Cutoff: %s (--hours %d)", cutoff.isoformat(), args.hours)

    articles, diagnostics = fetch_all(feeds, cutoff)

    # Save articles
    out_path = SCRIPT_DIR / args.output
    out_path.write_text(json.dumps(articles, indent=2, ensure_ascii=False))
    log.info("Saved %d articles to %s", len(articles), out_path)

    # Save diagnostic
    diag_path = SCRIPT_DIR / args.diagnostic
    diag_path.parent.mkdir(parents=True, exist_ok=True)
    write_diagnostic(
        diagnostics, diag_path,
        total_articles=sum(d["entries_72h"] for d in diagnostics),
        unique_articles=len(articles),
    )

    # Stats by tier
    by_tier = {}
    for a in articles:
        by_tier[a["tier"]] = by_tier.get(a["tier"], 0) + 1
    for t, n in sorted(by_tier.items()):
        log.info("  %s: %d", t, n)

    return articles


if __name__ == "__main__":
    main()

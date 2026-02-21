#!/usr/bin/env python3
"""
rss_fetcher.py — LinkedIn Radar v7
Fetches 105 RSS feeds with smart proxy routing, ThreadPoolExecutor,
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
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

# Domains that ALWAYS go through proxy (no direct attempt)
ALWAYS_PROXY_DOMAINS = [
    "reddit.com",
    "www.reddit.com",
]

# Domains that try direct first, but fallback to proxy on error
FALLBACK_PROXY_DOMAINS = [
    "news.google.com",
    "www.producthunt.com",
    "www.statista.com",
    "www.cbinsights.com",
    "www.similarweb.com",
    "www.platformer.news",
    "www.wired.com",
]

# ── Mobile User-Agent (iPhone Safari) ─────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, application/atom+xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
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
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        filtered = {k: v for k, v in params.items()
                    if k.lower() not in TRACKING_PARAMS}
        clean_query = urllib.parse.urlencode(filtered, doseq=True)
        return urllib.parse.urlunparse((
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


# ── Proxy logic (v7: improved with FALLBACK domains + SSL handler) ───────────
def _build_opener(use_proxy=False):
    """Build URL opener with optional proxy and permissive SSL."""
    handlers = []

    # SSL context that doesn't verify (some feeds/proxies have cert issues)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))

    if use_proxy and PROXY_URL:
        proxy_handler = urllib.request.ProxyHandler({
            "http": PROXY_URL,
            "https": PROXY_URL,
        })
        handlers.append(proxy_handler)

    return urllib.request.build_opener(*handlers)


def _domain_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def fetch_feed(url: str, timeout=20) -> tuple[bytes, str]:
    """Fetch RSS feed with smart proxy routing. Returns (content, method)."""
    req = urllib.request.Request(url)
    for k, v in HEADERS.items():
        req.add_header(k, v)

    domain = _domain_of(url)

    # Step 1: Always-proxy domains
    if any(d in domain for d in ALWAYS_PROXY_DOMAINS):
        if PROXY_URL:
            opener = _build_opener(use_proxy=True)
            return opener.open(req, timeout=timeout).read(), "proxy"
        raise Exception(f"Proxy required for {domain} but PROXY_URL not set")

    # Step 2: Try direct first
    try:
        opener = _build_opener(use_proxy=False)
        return opener.open(req, timeout=timeout).read(), "direct"
    except Exception as e:
        error_str = str(e).lower()
        # Step 3: If blocked or known fallback domain, retry with proxy
        should_retry = any(code in error_str for code in
                          ["403", "429", "406", "451", "blocked", "forbidden",
                           "too many", "captcha"])
        if not should_retry:
            should_retry = any(d in domain for d in FALLBACK_PROXY_DOMAINS)
        if should_retry and PROXY_URL:
            req2 = urllib.request.Request(url)
            for k, v in HEADERS.items():
                req2.add_header(k, v)
            opener = _build_opener(use_proxy=True)
            return opener.open(req2, timeout=timeout).read(), "proxy_fallback"
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
        content, method = fetch_feed(url)
        result["method"] = method
        result["http_code"] = 200
    except Exception as e:
        err = str(e)
        for code in ("403", "404", "406", "429", "451", "500", "502", "503"):
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
    """Write diagnostic markdown table with method breakdown."""
    lines = [
        "# LinkedIn Radar v7 — Feed Diagnostic",
        f"## Date: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Window: 72h",
        "",
        "| # | Feed | Tier | Status | HTTP | Method | Total | 72h | Error |",
        "|---|------|------|--------|------|--------|------:|----:|-------|",
    ]

    diagnostics.sort(key=lambda d: (d["tier"], d["name"]))

    ok = direct = proxy = proxy_fb = errors = 0
    for i, d in enumerate(diagnostics, 1):
        status = d["status"]
        method = d.get("method", "direct")
        if status == "ok":
            ok += 1
            if method == "direct":
                direct += 1
            elif method == "proxy":
                proxy += 1
            elif method == "proxy_fallback":
                proxy_fb += 1
        else:
            errors += 1

        error_short = (d.get("error") or "")[:60]
        lines.append(
            f"| {i} | {d['name']} | {d['tier'][:10]} | {status} "
            f"| {d.get('http_code') or '—'} | {method} "
            f"| {d['total_entries']} | {d['entries_72h']} | {error_short} |"
        )

    lines.extend([
        "",
        "## Summary",
        f"- Feeds OK: {ok}/{len(diagnostics)}",
        f"  - Direct: {direct}",
        f"  - Proxy: {proxy}",
        f"  - Proxy fallback: {proxy_fb}",
        f"- Feeds errored: {errors}",
        f"- Total articles (raw): {total_articles}",
        f"- Unique articles: {unique_articles}",
    ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Diagnostic written to %s", output_path)


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    global PROXY_URL

    parser = argparse.ArgumentParser(
        description="LinkedIn Radar v7 — RSS feed fetcher with smart proxy routing"
    )
    parser.add_argument("--hours", type=int, default=72,
                        help="Lookback window in hours (default: 72)")
    parser.add_argument("--output", type=str, default="articles.json",
                        help="Output JSON file (default: articles.json)")
    parser.add_argument("--diagnostic", type=str, default="output/diagnostic_v7.md",
                        help="Diagnostic output file")
    args = parser.parse_args()

    # Proxy prompt
    if not PROXY_URL:
        log.warning("PROXY_URL not set. Reddit and some feeds will fail.")
        log.warning("Set PROXY_URL env var or enter now (empty to skip):")
        try:
            user_input = input("PROXY_URL> ").strip()
            if user_input:
                PROXY_URL = user_input
        except (EOFError, KeyboardInterrupt):
            pass

    if PROXY_URL:
        masked = re.sub(r"://[^@]+@", "://***:***@", PROXY_URL)
        log.info("Proxy configured: %s", masked)
    else:
        log.info("No proxy — Reddit, some Google News feeds will fail")

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

    # Method breakdown
    methods = {}
    for d in diagnostics:
        m = d.get("method", "direct")
        s = d["status"]
        key = m if s == "ok" else "error"
        methods[key] = methods.get(key, 0) + 1
    log.info("Methods: %s", methods)

    return articles


if __name__ == "__main__":
    main()

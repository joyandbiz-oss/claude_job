#!/usr/bin/env python3
"""
LinkedIn Radar v8 — RSS feed monitor, AI scorer, and LinkedIn post generator.

Monitors 105+ RSS feeds, scores articles for LinkedIn post potential using Claude AI,
and generates ready-to-publish posts for a Data Infrastructure CMO.

NEW in v8:
  --fetch-only    Fetch & save articles WITHOUT Claude API (no key needed)
  --proxy URL     Mobile/residential proxy for blocked feeds (Reddit, etc.)
  Smart proxy routing: always-proxy / fallback-proxy / direct
  tier_biohacking included by default
"""

import argparse
import asyncio
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
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser
import yaml

# Conditional import — not needed for --fetch-only
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None  # type: ignore

# Load .env from script directory
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("linkedin-radar")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
FEEDS_PATH = SCRIPT_DIR / "feeds.yaml"
SEEN_URLS_PATH = SCRIPT_DIR / "seen_urls.json"
OUTPUT_DIR = SCRIPT_DIR / "output"

SCORING_MODEL = "claude-sonnet-4-20250514"
GENERATION_MODEL = "claude-sonnet-4-20250514"
SCORE_BATCH_SIZE = 10
MAX_RETRIES = 4
RETRY_BASE_DELAY = 2  # seconds

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "mc_cid", "mc_eid",
    "oly_anon_id", "oly_enc_id", "vero_id", "__s", "ref", "source",
    "ncid", "sr_share",
}

COMPETITORS = [
    "Bright Data", "Oxylabs", "Smartproxy", "Decodo", "NetNut",
    "Zyte", "Apify", "IPRoyal", "Webshare", "SOAX",
    "Nimble", "Rayobyte", "Infatica", "Proxy-Seller",
]

# ---------------------------------------------------------------------------
# Proxy configuration
# ---------------------------------------------------------------------------
PROXY_URL = os.environ.get("PROXY_URL", "")

# Domains that ALWAYS go through proxy (blocked without it)
ALWAYS_PROXY_DOMAINS = [
    "reddit.com",
    "www.reddit.com",
]

# Domains that try direct first, fallback to proxy on 403/429/etc.
FALLBACK_PROXY_DOMAINS = [
    "news.google.com",
    "www.producthunt.com",
    "www.statista.com",
    "www.cbinsights.com",
    "www.similarweb.com",
    "www.platformer.news",
    "www.wired.com",
    "www.lennysnewsletter.com",
]

# Mobile User-Agent (iPhone Safari — best for bypassing bot detection)
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, "
              "application/atom+xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# Scoring prompt
# ---------------------------------------------------------------------------
SCORING_PROMPT = """You are a scoring assistant for a Data Infrastructure company CMO's LinkedIn content radar.

Rate this article on 4 dimensions (0-10 each), then compute weighted total:

ARTICLE:
Title: {title}
Source: {source}
Summary: {summary}
URL: {url}

DIMENSIONS:
1. VIRAL FORMAT MATCH (weight 0.25): Can this become an Image-format LinkedIn post \
with 800+ chars? Does it have natural list structure? Contains quotable numbers/data? \
Posts with specific numbers get +73% more engagement.

2. HOOK STRENGTH (weight 0.25): Can it start with a number/stat (best hook, eng 136)? \
Does it have a contrarian or surprising angle? Can it be framed as personal experience? \
PENALTY: If the only angle is "How to do X" → score 2/10 max (worst performing hook).

3. AUDIENCE RESONANCE (weight 0.30): Does it touch high-engagement topics \
(personal story eng=147, career eng=136, free resources eng=121)? \
Is it relatable to data/tech professionals beyond proxy niche? \
Could it generate debate/comments? Does it connect to these ICP use cases: \
ad verification, SERP tracking, web scraping, price comparison, brand protection, \
website testing, streaming QA, social proxies?

4. TIMELINESS & EXCLUSIVITY (weight 0.20): Is it breaking (<24h)? \
Has anyone in the proxy/data space posted about this on LinkedIn yet? \
Can the CMO be first to comment?

COMPETITOR CONTEXT: Main competitors are Bright Data ($300M rev), Oxylabs ($44M), \
Smartproxy/Decodo, NetNut ($31M), Zyte ($38M), Apify ($13M), IPRoyal, Webshare, SOAX.
If the article mentions any competitor — always score ≥ 6.

Respond ONLY in this JSON format:
{{
  "viral_format": X,
  "hook_strength": X,
  "audience_resonance": X,
  "timeliness": X,
  "total_score": X.X,
  "best_template": "data_point|most_people_think|personal_story|cloudflare_effect|black_mirror|lawsuit_gdpr|free_resource",
  "hook_idea": "First line of the post in ≤15 words",
  "why_relevant": "One sentence on why this matters for DataImpulse CMO"
}}"""

# ---------------------------------------------------------------------------
# Post-generation prompt
# ---------------------------------------------------------------------------
POST_GENERATION_PROMPT = """You are the LinkedIn ghostwriter for the CMO of DataImpulse, a proxy and data \
infrastructure platform.

POSITIONING: "Data Infrastructure Insider" — NOT "proxy company CMO"
VOICE: Data-driven, slightly contrarian, technically informed but accessible.
Never salesy. Bold opinions backed by data. First-person experience when possible.

ARTICLE TO TRANSFORM:
Title: {title}
Source: {source}
URL: {url}
Summary: {summary}
Suggested template: {template}
Hook idea: {hook_idea}

POST RULES (based on analysis of 2,487 viral LinkedIn posts):
- Format: 800-1500 characters
- Hook: MUST start with a NUMBER, BOLD STATEMENT, or BREAKING NEWS
  (Never start with "How to" — worst performing hook type)
- Body: short paragraphs OR bold statement → 3-5 bullet list (use → or ✅) → insight
- Include 1-2 specific numbers/percentages (posts with numbers = +73% engagement)
- End with a QUESTION or BOLD CLOSING STATEMENT
  (Numbers + Question ending = best combo, median engagement 322)
- Use lots of line breaks (14+ in viral posts)
- NO hashtags in body. Max 3 hashtags at the very end
- CRITICAL: Do NOT write about "proxies" directly. Frame through wider angles:
  AI data infrastructure, internet traffic economics, data quality, digital rights,
  web platform changes. Proxy/scraping niche gets engagement 43,
  while "AI + data" gets 79, "personal story" gets 147.
- Do NOT be generic. Be specific, opinionated, and cite the source.

TEMPLATES AVAILABLE:
1. data_point: "[Number]. Let that sink in. [Source] released... → Stats → Insight → Question"
2. most_people_think: "Most people think [X] is for [Y]. But... → List of surprises → Deeper insight"
3. personal_story: "[X] years ago... → Story → What I learned → Reflection → Question"
4. cloudflare_effect: "[Company] announced [X]. What most people miss: → Points → Bold closing"
5. black_mirror: "We're living in [sci-fi]. [What happened]. But it's not about [obvious]. It's about [deeper]."
6. lawsuit_gdpr: "€[X]M fine. I read the filing. 3 things → Legal points → Compliance = advantage"
7. free_resource: "[X] released free. ✅ Features → Why it matters → Link"

Generate:
---EN---
[Full LinkedIn post in English, 800-1500 chars]

---RU---
[Same post adapted to Russian, same length]
"""


# ============================================================================
# URL helpers
# ============================================================================

def normalize_url(url: str) -> str:
    """Strip tracking parameters and normalize a URL for deduplication."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)
        filtered = {k: v for k, v in params.items()
                    if k.lower() not in TRACKING_PARAMS}
        clean_query = urlencode(filtered, doseq=True)
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            parsed.params,
            clean_query,
            "",  # drop fragment
        ))
        return normalized
    except Exception:
        return url


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


# ============================================================================
# Seen-URL cache
# ============================================================================

def load_seen_urls() -> dict:
    """Return {url_hash: iso_date_str} from the cache file."""
    if SEEN_URLS_PATH.exists():
        try:
            return json.loads(SEEN_URLS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Could not read seen_urls.json — starting fresh")
    return {}


def save_seen_urls(seen: dict) -> None:
    """Persist the seen-URL cache, pruning entries older than 7 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_URLS_PATH.write_text(json.dumps(pruned, indent=2))


# ============================================================================
# Feed loading
# ============================================================================

def load_feeds(tiers: list[str] | None = None) -> list[dict]:
    """Load feeds from feeds.yaml, optionally filtered by tier.

    competitor_watch is always included.
    """
    with open(FEEDS_PATH) as f:
        cfg = yaml.safe_load(f)

    all_tiers = [
        "tier1_must_read", "tier2_industry", "tier3_background",
        "tier_biohacking", "competitor_watch",
    ]
    selected = set(tiers) if tiers else set(all_tiers)
    # Always include competitor_watch
    selected.add("competitor_watch")

    articles_feeds: list[dict] = []
    for tier in all_tiers:
        if tier not in selected or tier not in cfg:
            continue
        for feed in cfg[tier].get("feeds", []):
            feed["tier"] = tier
            articles_feeds.append(feed)
    return articles_feeds


# ============================================================================
# Smart Proxy Routing (from rss_fetcher v7 + mobile proxy support)
# ============================================================================

def _build_opener(use_proxy: bool = False) -> urllib.request.OpenerDirector:
    """Build URL opener with optional proxy and permissive SSL."""
    handlers: list = []

    # SSL context — permissive (some feeds/proxies have cert issues)
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


def _fetch_with_proxy_routing(url: str, timeout: int = 25) -> tuple[bytes, str]:
    """Fetch URL with smart proxy routing. Returns (content, method).

    Routing logic:
      1. ALWAYS_PROXY_DOMAINS → proxy only (Reddit, etc.)
      2. Try direct first
      3. On 403/429/blocked OR FALLBACK_PROXY_DOMAINS → retry via proxy
    """
    req = urllib.request.Request(url)
    for k, v in FETCH_HEADERS.items():
        req.add_header(k, v)

    domain = _domain_of(url)

    # Step 1: Always-proxy domains (Reddit, etc.)
    if any(d in domain for d in ALWAYS_PROXY_DOMAINS):
        if PROXY_URL:
            opener = _build_opener(use_proxy=True)
            return opener.open(req, timeout=timeout).read(), "proxy"
        raise Exception(f"Proxy required for {domain} but PROXY_URL not set")

    # Step 2: Try direct
    try:
        opener = _build_opener(use_proxy=False)
        return opener.open(req, timeout=timeout).read(), "direct"
    except Exception as e:
        error_str = str(e).lower()
        # Step 3: Retry with proxy on block / known fallback domain
        should_retry = any(code in error_str for code in
                          ["403", "429", "406", "451", "blocked", "forbidden",
                           "too many", "captcha"])
        if not should_retry:
            should_retry = any(d in domain for d in FALLBACK_PROXY_DOMAINS)
        if should_retry and PROXY_URL:
            req2 = urllib.request.Request(url)
            for k, v in FETCH_HEADERS.items():
                req2.add_header(k, v)
            opener = _build_opener(use_proxy=True)
            return opener.open(req2, timeout=timeout).read(), "proxy_fallback"
        raise


# ============================================================================
# Feed fetching — ThreadPool with proxy routing (v8)
# ============================================================================

def _parse_entry_date(entry) -> datetime | None:
    """Extract a timezone-aware datetime from a feedparser entry."""
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


def _extract_google_news_title(title: str) -> str:
    """Google News wraps titles as 'Article title - Source'. Extract title."""
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def _entry_summary(entry) -> str:
    """Get a clean text summary from a feedparser entry."""
    raw = (getattr(entry, "summary", "") or
           getattr(entry, "description", "") or "")
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:1500]


def fetch_single_feed_sync(feed_cfg: dict, cutoff: datetime,
                           seen: dict) -> dict:
    """Fetch and parse one RSS feed (sync, with proxy routing).

    Returns diagnostic dict with 'articles' key.
    """
    url = feed_cfg["url"]
    name = feed_cfg["name"]
    tier = feed_cfg.get("tier", "unknown")
    is_google_news = "news.google.com" in url

    result = {
        "name": name,
        "url": url,
        "tier": tier,
        "status": "error",
        "http_code": None,
        "method": "direct",
        "total_entries": 0,
        "entries_window": 0,
        "error": None,
        "articles": [],
    }

    # Fetch with smart proxy routing
    try:
        content, method = _fetch_with_proxy_routing(url)
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

    # Parse
    parsed = feedparser.parse(content)
    result["total_entries"] = len(parsed.entries)

    articles = []
    for entry in parsed.entries:
        pub_date = _parse_entry_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        link = getattr(entry, "link", None)
        if not link:
            continue

        h = url_hash(link)
        if h in seen:
            continue

        title = getattr(entry, "title", "Untitled") or "Untitled"
        if is_google_news:
            title = _extract_google_news_title(title)

        articles.append({
            "title": title,
            "url": link,
            "normalized_url": normalize_url(link),
            "url_hash": h,
            "published": pub_date.isoformat() if pub_date else None,
            "summary": _entry_summary(entry),
            "source_name": name,
            "feed_tier": tier,
            "competitor": feed_cfg.get("competitor"),
        })

    result["entries_window"] = len(articles)
    result["articles"] = articles
    result["status"] = "ok"
    return result


def fetch_all_feeds_threaded(feeds: list[dict], cutoff: datetime,
                             seen: dict) -> tuple[list[dict], list[dict]]:
    """Fetch all feeds via ThreadPoolExecutor with proxy routing.

    Returns (unique_articles, diagnostics).
    """
    diagnostics: list[dict] = []
    all_articles: list[dict] = []

    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_feed = {
            executor.submit(fetch_single_feed_sync, f, cutoff, seen): f
            for f in feeds
        }
        for future in as_completed(future_to_feed):
            feed = future_to_feed[future]
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "name": feed["name"], "url": feed["url"],
                    "tier": feed.get("tier", "unknown"),
                    "status": "error", "http_code": None,
                    "method": "direct", "total_entries": 0,
                    "entries_window": 0, "error": str(e)[:200],
                    "articles": [],
                }

            diag = {k: v for k, v in result.items() if k != "articles"}
            diagnostics.append(diag)

            status = result["status"]
            method = result["method"]
            n = result["entries_window"]
            log.info("%-35s %s %-15s → %d articles",
                     result["name"], status.upper(), f"({method})", n)

            all_articles.extend(result.get("articles", []))

    # Deduplicate by normalized URL
    seen_normalized: set[str] = set()
    unique: list[dict] = []
    for art in all_articles:
        nurl = art["normalized_url"]
        if nurl not in seen_normalized:
            seen_normalized.add(nurl)
            unique.append(art)

    log.info("Total: %d raw → %d unique articles",
             len(all_articles), len(unique))
    return unique, diagnostics


# ============================================================================
# Diagnostic report
# ============================================================================

def write_diagnostic(diagnostics: list[dict], output_path: Path,
                     total_articles: int, unique_articles: int) -> None:
    """Write diagnostic markdown table with method breakdown."""
    lines = [
        "# LinkedIn Radar v8 — Feed Diagnostic",
        f"## {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"Proxy: {'✅' if PROXY_URL else '❌'}",
        "",
        "| # | Feed | Tier | Status | HTTP | Method | Total | Window | Error |",
        "|---|------|------|--------|------|--------|------:|-------:|-------|",
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
            f"| {i} | {d['name']} | {d['tier'][:12]} | {status} "
            f"| {d.get('http_code') or '—'} | {method} "
            f"| {d['total_entries']} | {d['entries_window']} "
            f"| {error_short} |"
        )

    lines.extend([
        "",
        "## Summary",
        f"- Feeds OK: **{ok}/{len(diagnostics)}**",
        f"  - Direct: {direct}",
        f"  - Proxy: {proxy}",
        f"  - Proxy fallback: {proxy_fb}",
        f"- Feeds errored: {errors}",
        f"- Total articles (raw): {total_articles}",
        f"- Unique articles: **{unique_articles}**",
    ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Diagnostic written to %s", output_path)


# ============================================================================
# Claude API helpers
# ============================================================================

def _api_call_with_retry(client, *, model: str, max_tokens: int,
                         messages: list[dict], temperature: float = 0.3) -> str:
    """Call the Anthropic API with exponential-backoff retry."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            return resp.content[0].text
        except Exception as exc:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            log.warning("API call failed (attempt %d/%d): %s — retrying in %ds",
                        attempt + 1, MAX_RETRIES, exc, delay)
            time.sleep(delay)
    raise RuntimeError(f"API call failed after {MAX_RETRIES} retries")


def _extract_json(text: str) -> dict:
    """Extract a JSON object from possibly-wrapped text."""
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract JSON from response: {text[:300]}")


# ============================================================================
# Scoring
# ============================================================================

def score_articles(client, articles: list[dict]) -> list[dict]:
    """Score articles using Claude. Mutates and returns the articles list."""
    if not articles:
        return articles

    total = len(articles)
    log.info("Scoring %d articles in batches of %d …", total, SCORE_BATCH_SIZE)

    for i in range(0, total, SCORE_BATCH_SIZE):
        batch = articles[i:i + SCORE_BATCH_SIZE]
        for art in batch:
            prompt = SCORING_PROMPT.format(
                title=art["title"],
                source=art["source_name"],
                summary=art["summary"][:600],
                url=art["url"],
            )
            try:
                raw = _api_call_with_retry(
                    client,
                    model=SCORING_MODEL,
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                score_data = _extract_json(raw)
                art["score"] = score_data
                total_score = float(score_data.get("total_score", 0))
                art["total_score"] = total_score
                log.info("  %.1f/10 — %s", total_score, art["title"][:70])
            except Exception as exc:
                log.warning("Scoring failed for '%s': %s",
                            art["title"][:50], exc)
                art["score"] = None
                art["total_score"] = 0.0

        if i + SCORE_BATCH_SIZE < total:
            time.sleep(1)

    return articles


# ============================================================================
# Post generation
# ============================================================================

def generate_post(client, article: dict) -> str | None:
    """Generate EN + RU LinkedIn posts for a high-scoring article."""
    score = article.get("score", {})
    prompt = POST_GENERATION_PROMPT.format(
        title=article["title"],
        source=article["source_name"],
        url=article["url"],
        summary=article["summary"][:800],
        template=score.get("best_template", "data_point"),
        hook_idea=score.get("hook_idea", article["title"]),
    )
    try:
        text = _api_call_with_retry(
            client,
            model=GENERATION_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return text
    except Exception as exc:
        log.warning("Post generation failed for '%s': %s",
                    article["title"][:50], exc)
        return None


# ============================================================================
# Telegram notification
# ============================================================================

def send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    """Send a message via Telegram Bot API (sync, best-effort)."""
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for chunk_start in range(0, len(text), 4000):
        chunk = text[chunk_start:chunk_start + 4000]
        try:
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }, timeout=15)
        except Exception as exc:
            log.warning("Telegram send failed: %s", exc)


def notify_telegram(instant_posts: list[dict]) -> None:
    """Send Telegram notifications for instant posts (score ≥ 8)."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        log.info("Telegram not configured — skipping notifications")
        return

    if not instant_posts:
        send_telegram(bot_token, chat_id,
                      "📡 LinkedIn Radar: No instant posts today.")
        return

    header = f"🔥 *LinkedIn Radar* — {len(instant_posts)} instant post(s)\n\n"
    lines = []
    for art in instant_posts:
        score = art.get("total_score", 0)
        hook = art.get("score", {}).get("hook_idea", "")
        lines.append(
            f"🔥 {score:.1f}/10 | {art['source_name']}\n{hook}\n{art['url']}")
    send_telegram(bot_token, chat_id, header + "\n\n".join(lines))

    for art in instant_posts:
        if art.get("generated_post"):
            msg = f"📝 *{art['title'][:80]}*\n\n{art['generated_post']}"
            send_telegram(bot_token, chat_id, msg)


# ============================================================================
# Markdown report (works for both fetch-only and full pipeline)
# ============================================================================

def _score_badge(score: float) -> str:
    if score >= 8:
        return "🔥"
    if score >= 6:
        return "⚡"
    if score >= 5:
        return "📌"
    return "·"


def generate_report(articles: list[dict], date_str: str,
                    feeds_count: int, fetch_only: bool = False) -> str:
    """Build the Markdown report."""
    scored = [a for a in articles if a.get("score")]
    instant = [a for a in scored if a["total_score"] >= 8]
    digest = [a for a in scored if 5 <= a["total_score"] < 8]
    competitor_articles = [
        a for a in (scored if scored else articles)
        if a.get("competitor") or a.get("feed_tier") == "competitor_watch"
    ]

    lines: list[str] = []

    if fetch_only:
        # ---- FETCH-ONLY report (no scores) ----
        lines.append(f"# 📡 LinkedIn Radar — {date_str} (fetch-only)\n")
        lines.append(f"**{len(articles)} articles** from {feeds_count} feeds | "
                     f"Proxy: {'✅' if PROXY_URL else '❌'}\n")

        # Group by tier
        by_tier: dict[str, list] = {}
        for art in articles:
            tier = art.get("feed_tier", "unknown")
            by_tier.setdefault(tier, []).append(art)

        for tier_name in ["tier1_must_read", "tier2_industry",
                          "tier3_background", "tier_biohacking",
                          "competitor_watch"]:
            tier_arts = by_tier.get(tier_name, [])
            if not tier_arts:
                continue
            lines.append(f"\n## {tier_name} ({len(tier_arts)} articles)\n")
            for art in tier_arts:
                comp = f" **[{art['competitor']}]**" if art.get("competitor") else ""
                pub = ""
                if art.get("published"):
                    try:
                        dt = datetime.fromisoformat(art["published"])
                        pub = dt.strftime(" | %b %d %H:%M")
                    except Exception:
                        pass
                lines.append(
                    f"- {art['source_name']}{comp}{pub}  \n"
                    f"  **{art['title']}**  \n"
                    f"  {art['url']}\n"
                )

        lines.append(f"\n## Stats\n")
        lines.append(f"- Feeds processed: {feeds_count}")
        lines.append(f"- Articles found: {len(articles)}")
        lines.append(f"- Competitor mentions: {len(competitor_articles)}")
        lines.append("")
        return "\n".join(lines)

    # ---- FULL report (with scores) ----
    instant.sort(key=lambda a: a["total_score"], reverse=True)
    digest.sort(key=lambda a: a["total_score"], reverse=True)

    lines.append(f"# 🔥 LinkedIn Radar — {date_str}\n")

    lines.append("## Instant Posts (score ≥ 8)\n")
    if not instant:
        lines.append("_No instant posts today._\n")
    for art in instant:
        s = art["score"]
        lines.append(
            f"### {_score_badge(art['total_score'])} "
            f"{art['total_score']:.1f}/10 — {art['title']}\n")
        lines.append(
            f"**Source:** {art['source_name']} | "
            f"**Template:** {s.get('best_template', '—')}  ")
        lines.append(f"**Hook:** {s.get('hook_idea', '—')}  ")
        lines.append(f"**Why relevant:** {s.get('why_relevant', '—')}  ")
        lines.append(f"**URL:** {art['url']}\n")
        if art.get("generated_post"):
            lines.append("<details><summary>📝 Generated Post</summary>\n")
            lines.append(f"```\n{art['generated_post']}\n```\n")
            lines.append("</details>\n")

    lines.append("## Daily Digest (score 5–7.9)\n")
    if not digest:
        lines.append("_Nothing in the digest range today._\n")
    for art in digest:
        s = art["score"]
        badge = _score_badge(art["total_score"])
        lines.append(
            f"- {badge} **{art['total_score']:.1f}** | "
            f"{art['source_name']} — _{art['title']}_  ")
        lines.append(
            f"  Hook: {s.get('hook_idea', '—')} | "
            f"Why: {s.get('why_relevant', '—')}  ")
        lines.append(f"  {art['url']}\n")

    lines.append("## Competitor Watch\n")
    comp_unique = {a["url_hash"]: a for a in competitor_articles}
    if not comp_unique:
        lines.append("_No competitor mentions today._\n")
    for art in comp_unique.values():
        comp_label = art.get("competitor", "industry")
        lines.append(
            f"- **[{comp_label}]** {art['total_score']:.1f}/10 — "
            f"{art['title']}  ")
        lines.append(f"  {art['url']}\n")

    lines.append("## Stats\n")
    lines.append(f"- Feeds processed: {feeds_count}")
    lines.append(f"- Articles found: {len(articles)}")
    lines.append(f"- Scored ≥ 8: {len(instant)}")
    lines.append(
        f"- Scored ≥ 5: "
        f"{len([a for a in scored if a['total_score'] >= 5])}")
    lines.append(
        f"- Generated posts: "
        f"{len([a for a in articles if a.get('generated_post')])}")
    lines.append("")

    return "\n".join(lines)


# ============================================================================
# Score a single URL
# ============================================================================

def score_single_url(client, url: str) -> None:
    """Fetch, score, and optionally generate a post for a single URL."""
    log.info("Scoring single URL: %s", url)

    article = {
        "title": url,
        "url": url,
        "normalized_url": normalize_url(url),
        "url_hash": url_hash(url),
        "published": None,
        "summary": "",
        "source_name": urlparse(url).netloc,
        "feed_tier": "manual",
        "competitor": None,
    }

    # Try to fetch page title/summary
    try:
        import requests as req_lib
        resp = req_lib.get(url, timeout=15,
                           headers={"User-Agent": USER_AGENT})
        if resp.ok:
            title_match = re.search(
                r"<title[^>]*>(.*?)</title>",
                resp.text, re.IGNORECASE | re.DOTALL)
            if title_match:
                article["title"] = re.sub(
                    r"\s+", " ", title_match.group(1)).strip()
            desc_match = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+'
                r'content=["\']([^"\']*)["\']',
                resp.text, re.IGNORECASE)
            if desc_match:
                article["summary"] = desc_match.group(1).strip()[:1000]
    except Exception as exc:
        log.warning("Could not fetch URL metadata: %s", exc)

    score_articles(client, [article])

    if article.get("score"):
        s = article["score"]
        print(f"\n{'='*60}")
        print(f"Score: {article['total_score']:.1f}/10")
        print(f"Title: {article['title']}")
        print(f"Template: {s.get('best_template', '—')}")
        print(f"Hook: {s.get('hook_idea', '—')}")
        print(f"Why relevant: {s.get('why_relevant', '—')}")
        print(f"Breakdown: viral={s.get('viral_format')}, "
              f"hook={s.get('hook_strength')}, "
              f"audience={s.get('audience_resonance')}, "
              f"timely={s.get('timeliness')}")
        print(f"{'='*60}")

        if article["total_score"] >= 6:
            log.info("Score ≥ 6 — generating LinkedIn post …")
            post = generate_post(client, article)
            if post:
                print(f"\n{post}")
    else:
        print("Scoring failed for this URL.")


# ============================================================================
# Main pipeline
# ============================================================================

def run_pipeline(args) -> int:
    """Run the LinkedIn Radar pipeline. Returns exit code."""
    global PROXY_URL

    # Handle proxy from CLI
    if args.proxy:
        PROXY_URL = args.proxy
    if PROXY_URL:
        masked = re.sub(r"://[^@]+@", "://***:***@", PROXY_URL)
        log.info("Proxy configured: %s", masked)
    else:
        log.warning("No proxy — Reddit and some feeds will fail. "
                     "Use --proxy or set PROXY_URL in .env")

    # ---- FETCH-ONLY mode: no API key needed ----
    if args.fetch_only:
        log.info("=== FETCH-ONLY MODE (no Claude API needed) ===")

        if not FEEDS_PATH.exists():
            log.error("feeds.yaml not found at %s", FEEDS_PATH)
            return 1

        tiers = args.tiers.split(",") if args.tiers else None
        feeds = load_feeds(tiers)
        log.info("Loaded %d feeds", len(feeds))

        cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
        log.info("Window: %s (--hours %d)", cutoff.isoformat(), args.hours)

        seen = load_seen_urls()

        log.info("Fetching feeds with smart proxy routing …")
        articles, diagnostics = fetch_all_feeds_threaded(feeds, cutoff, seen)

        if not articles:
            log.info("No new articles found.")
            return 0

        # Save seen
        now_iso = datetime.now(timezone.utc).isoformat()
        for art in articles:
            seen[art["url_hash"]] = now_iso
        save_seen_urls(seen)

        # Save articles JSON
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        json_path = OUTPUT_DIR / f"articles_{date_str}.json"
        json_path.write_text(
            json.dumps(articles, indent=2, ensure_ascii=False))
        log.info("Articles saved to %s", json_path)

        # Diagnostic
        diag_path = OUTPUT_DIR / f"diagnostic_{date_str}.md"
        write_diagnostic(
            diagnostics, diag_path,
            total_articles=sum(d["entries_window"] for d in diagnostics),
            unique_articles=len(articles),
        )

        # Markdown report
        report = generate_report(articles, date_str, len(feeds),
                                 fetch_only=True)
        report_path = OUTPUT_DIR / f"radar_{date_str}.md"
        report_path.write_text(report)
        log.info("Report written to %s", report_path)

        # Stats
        by_tier: dict[str, int] = {}
        for a in articles:
            by_tier[a["feed_tier"]] = by_tier.get(a["feed_tier"], 0) + 1

        methods: dict[str, int] = {}
        for d in diagnostics:
            m = d.get("method", "direct")
            s = d["status"]
            key = m if s == "ok" else "error"
            methods[key] = methods.get(key, 0) + 1

        comp_count = len([a for a in articles
                          if a.get("competitor") or
                          a.get("feed_tier") == "competitor_watch"])

        print(f"\n{'='*60}")
        print(f"LinkedIn Radar v8 — FETCH ONLY — {date_str}")
        print(f"{'='*60}")
        print(f"Feeds processed:     {len(feeds)}")
        print(f"Articles found:      {len(articles)}")
        print(f"Competitor mentions:  {comp_count}")
        print(f"Routing:             {methods}")
        for t, n in sorted(by_tier.items()):
            print(f"  {t}: {n}")
        print(f"Output:              {report_path}")
        print(f"JSON:                {json_path}")
        print(f"Diagnostic:          {diag_path}")
        print(f"{'='*60}\n")
        return 0

    # ---- FULL MODE: requires Claude API key ----
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set. Use --fetch-only to run "
                   "without API key, or set ANTHROPIC_API_KEY in .env")
        return 1

    if Anthropic is None:
        log.error("anthropic package not installed. "
                   "Run: pip install anthropic")
        return 1

    client = Anthropic(api_key=api_key)

    # Handle single-URL mode
    if args.url:
        score_single_url(client, args.url)
        return 0

    # Load config
    if not FEEDS_PATH.exists():
        log.error("feeds.yaml not found at %s", FEEDS_PATH)
        return 1

    tiers = args.tiers.split(",") if args.tiers else None
    feeds = load_feeds(tiers)
    log.info("Loaded %d feeds", len(feeds))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    log.info("Window: %s (--hours %d)", cutoff.isoformat(), args.hours)

    seen = load_seen_urls()

    # Fetch feeds (now with proxy routing)
    log.info("Fetching feeds with smart proxy routing …")
    articles, diagnostics = fetch_all_feeds_threaded(feeds, cutoff, seen)

    if not articles:
        log.info("No new articles found.")
        return 0

    # Score
    score_articles(client, articles)

    # Save seen
    now_iso = datetime.now(timezone.utc).isoformat()
    for art in articles:
        seen[art["url_hash"]] = now_iso
    save_seen_urls(seen)

    # Generate posts (unless dry run)
    if not args.dry_run:
        high_scoring = [a for a in articles
                        if a.get("total_score", 0) >= 6 and a.get("score")]
        log.info("Generating posts for %d articles with score ≥ 6 …",
                 len(high_scoring))
        for art in high_scoring:
            post = generate_post(client, art)
            art["generated_post"] = post
    else:
        log.info("Dry run — skipping post generation")

    # Save articles JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    json_path = OUTPUT_DIR / f"articles_{date_str}.json"
    json_path.write_text(
        json.dumps(articles, indent=2, ensure_ascii=False,
                   default=str))

    # Diagnostic
    diag_path = OUTPUT_DIR / f"diagnostic_{date_str}.md"
    write_diagnostic(
        diagnostics, diag_path,
        total_articles=sum(d["entries_window"] for d in diagnostics),
        unique_articles=len(articles),
    )

    # Build report
    report = generate_report(articles, date_str, len(feeds))
    report_path = OUTPUT_DIR / f"radar_{date_str}.md"
    report_path.write_text(report)
    log.info("Report written to %s", report_path)

    # Summary
    scored = [a for a in articles if a.get("score")]
    instant = [a for a in scored if a["total_score"] >= 8]
    print(f"\n{'='*60}")
    print(f"LinkedIn Radar v8 — {date_str}")
    print(f"{'='*60}")
    print(f"Feeds processed: {len(feeds)}")
    print(f"Articles found:  {len(articles)}")
    print(f"Scored ≥ 8:      {len(instant)}")
    print(f"Scored ≥ 5:      "
          f"{len([a for a in scored if a['total_score'] >= 5])}")
    print(f"Report:          {report_path}")
    print(f"JSON:            {json_path}")
    print(f"{'='*60}\n")

    # Telegram
    notify_telegram(instant)

    return 0


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LinkedIn Radar v8 — RSS monitor & AI-powered "
                    "LinkedIn post generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # Fetch only (NO API key needed):
  python linkedin_radar_v8.py --fetch-only --hours 72

  # Fetch only with mobile proxy:
  python linkedin_radar_v8.py --fetch-only --hours 24 \\
      --proxy "http://user:pass@mobile-proxy:port"

  # Full pipeline (score + generate posts):
  python linkedin_radar_v8.py --hours 24

  # Dry run (score only, no post generation):
  python linkedin_radar_v8.py --hours 24 --dry-run

  # Score a single URL:
  python linkedin_radar_v8.py --url "https://example.com/article"

  # Only specific tiers:
  python linkedin_radar_v8.py --fetch-only --hours 48 \\
      --tiers tier1_must_read,competitor_watch

PROXY SETUP (.env file):
  PROXY_URL=http://user:pass@proxy-host:port
  ANTHROPIC_API_KEY=sk-ant-xxxxx
  TELEGRAM_BOT_TOKEN=123456:ABCdef
  TELEGRAM_CHAT_ID=-1001234567890

PROXY FORMATS (all supported):
  http://user:pass@host:port          # HTTP proxy
  http://user:pass@mobile.proxy:port  # Mobile proxy (4G/LTE)
  socks5://user:pass@host:port        # SOCKS5 proxy
        """,
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Look back window in hours (default: 24)",
    )
    parser.add_argument(
        "--tiers", type=str, default=None,
        help="Comma-separated tiers to include "
             "(e.g. tier1_must_read,competitor_watch). "
             "competitor_watch is always included.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and score only — skip post generation",
    )
    parser.add_argument(
        "--fetch-only", action="store_true",
        help="Fetch feeds only — NO scoring, NO API key needed. "
             "Saves articles.json + report.md + diagnostic.md",
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="Score a specific URL instead of processing feeds",
    )
    parser.add_argument(
        "--proxy", type=str, default=None,
        help="Proxy URL for blocked feeds "
             "(e.g. http://user:pass@mobile-proxy:port). "
             "Overrides PROXY_URL from .env",
    )

    args = parser.parse_args()
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()

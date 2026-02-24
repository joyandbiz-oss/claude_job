#!/usr/bin/env python3
"""
LinkedIn Radar — RSS feed monitor, AI scorer, and LinkedIn post generator.

Monitors 76+ RSS feeds, scores articles for LinkedIn post potential using Claude AI,
and generates ready-to-publish posts for a Data Infrastructure CMO.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import aiohttp
import feedparser
import yaml
from anthropic import Anthropic

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
]

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
        filtered = {k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS}
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

    all_tiers = ["tier1_must_read", "tier2_industry", "tier3_background", "competitor_watch"]
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
# Async feed fetching
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
    # Try parsing date strings directly
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
    """Google News wraps titles as 'Article title - Source'. Extract just the title."""
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def _entry_summary(entry) -> str:
    """Get a clean text summary from a feedparser entry."""
    raw = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:1000]  # cap length


async def fetch_single_feed(session: aiohttp.ClientSession, feed_cfg: dict,
                            cutoff: datetime, seen: dict) -> list[dict]:
    """Fetch and parse a single RSS feed. Return list of article dicts."""
    url = feed_cfg["url"]
    name = feed_cfg["name"]
    tier = feed_cfg.get("tier", "unknown")
    is_google_news = "news.google.com" in url

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                log.warning("Feed %s returned HTTP %d", name, resp.status)
                return []
            body = await resp.text()
    except Exception as exc:
        log.warning("Feed %s fetch failed: %s", name, exc)
        return []

    parsed = feedparser.parse(body)
    articles = []
    for entry in parsed.entries:
        pub_date = _parse_entry_date(entry)
        if pub_date and pub_date < cutoff:
            continue  # too old

        link = getattr(entry, "link", None)
        if not link:
            continue

        h = url_hash(link)
        if h in seen:
            continue  # already processed

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

    log.info("Feed %-30s → %d new articles", name, len(articles))
    return articles


async def fetch_all_feeds(feeds: list[dict], cutoff: datetime,
                          seen: dict) -> list[dict]:
    """Fetch all feeds concurrently and return deduplicated articles."""
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [fetch_single_feed(session, f, cutoff, seen) for f in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten + deduplicate by normalized URL
    seen_normalized: set[str] = set()
    articles: list[dict] = []
    for result in results:
        if isinstance(result, Exception):
            log.warning("Feed task failed: %s", result)
            continue
        for art in result:
            nurl = art["normalized_url"]
            if nurl not in seen_normalized:
                seen_normalized.add(nurl)
                articles.append(art)

    log.info("Total unique articles after dedup: %d", len(articles))
    return articles


# ============================================================================
# Claude API helpers
# ============================================================================

def _api_call_with_retry(client: Anthropic, *, model: str, max_tokens: int,
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
    # Try to find JSON block
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

def score_articles(client: Anthropic, articles: list[dict]) -> list[dict]:
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
                log.warning("Scoring failed for '%s': %s", art["title"][:50], exc)
                art["score"] = None
                art["total_score"] = 0.0

        # Small pause between batches to be nice to the API
        if i + SCORE_BATCH_SIZE < total:
            time.sleep(1)

    return articles


# ============================================================================
# Post generation
# ============================================================================

def generate_post(client: Anthropic, article: dict) -> str | None:
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
        log.warning("Post generation failed for '%s': %s", article["title"][:50], exc)
        return None


# ============================================================================
# Telegram notification
# ============================================================================

def send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    """Send a message via Telegram Bot API (sync, best-effort)."""
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # Telegram max message length is 4096
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
        send_telegram(bot_token, chat_id, "📡 LinkedIn Radar: No instant posts today.")
        return

    header = f"🔥 *LinkedIn Radar* — {len(instant_posts)} instant post(s)\n\n"
    lines = []
    for art in instant_posts:
        score = art.get("total_score", 0)
        hook = art.get("score", {}).get("hook_idea", "")
        lines.append(f"🔥 {score:.1f}/10 | {art['source_name']}\n{hook}\n{art['url']}")
    send_telegram(bot_token, chat_id, header + "\n\n".join(lines))

    # Also send full generated posts
    for art in instant_posts:
        if art.get("generated_post"):
            msg = f"📝 *{art['title'][:80]}*\n\n{art['generated_post']}"
            send_telegram(bot_token, chat_id, msg)


# ============================================================================
# Markdown report
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
                    feeds_count: int) -> str:
    """Build the Markdown report."""
    scored = [a for a in articles if a.get("score")]
    instant = [a for a in scored if a["total_score"] >= 8]
    digest = [a for a in scored if 5 <= a["total_score"] < 8]
    competitor_articles = [a for a in scored if a.get("competitor") or a["feed_tier"] == "competitor_watch"]

    instant.sort(key=lambda a: a["total_score"], reverse=True)
    digest.sort(key=lambda a: a["total_score"], reverse=True)

    lines: list[str] = []
    lines.append(f"# 🔥 LinkedIn Radar — {date_str}\n")

    # ------ Instant Posts ------
    lines.append("## Instant Posts (score ≥ 8)\n")
    if not instant:
        lines.append("_No instant posts today._\n")
    for art in instant:
        s = art["score"]
        lines.append(f"### {_score_badge(art['total_score'])} {art['total_score']:.1f}/10 — {art['title']}\n")
        lines.append(f"**Source:** {art['source_name']} | **Template:** {s.get('best_template', '—')}  ")
        lines.append(f"**Hook:** {s.get('hook_idea', '—')}  ")
        lines.append(f"**Why relevant:** {s.get('why_relevant', '—')}  ")
        lines.append(f"**URL:** {art['url']}\n")
        if art.get("generated_post"):
            lines.append("<details><summary>📝 Generated Post</summary>\n")
            lines.append(f"```\n{art['generated_post']}\n```\n")
            lines.append("</details>\n")

    # ------ Daily Digest ------
    lines.append("## Daily Digest (score 5–7.9)\n")
    if not digest:
        lines.append("_Nothing in the digest range today._\n")
    for art in digest:
        s = art["score"]
        badge = _score_badge(art["total_score"])
        lines.append(f"- {badge} **{art['total_score']:.1f}** | {art['source_name']} — _{art['title']}_  ")
        lines.append(f"  Hook: {s.get('hook_idea', '—')} | Why: {s.get('why_relevant', '—')}  ")
        lines.append(f"  {art['url']}\n")

    # ------ Competitor Watch ------
    lines.append("## Competitor Watch\n")
    comp_unique = {a["url_hash"]: a for a in competitor_articles}
    if not comp_unique:
        lines.append("_No competitor mentions today._\n")
    for art in comp_unique.values():
        comp_label = art.get("competitor", "industry")
        lines.append(f"- **[{comp_label}]** {art['total_score']:.1f}/10 — {art['title']}  ")
        lines.append(f"  {art['url']}\n")

    # ------ Stats ------
    lines.append("## Stats\n")
    lines.append(f"- Feeds processed: {feeds_count}")
    lines.append(f"- Articles found: {len(articles)}")
    lines.append(f"- Scored ≥ 8: {len(instant)}")
    lines.append(f"- Scored ≥ 5: {len([a for a in scored if a['total_score'] >= 5])}")
    lines.append(f"- Generated posts: {len([a for a in articles if a.get('generated_post')])}")
    lines.append("")

    return "\n".join(lines)


# ============================================================================
# Score a single URL
# ============================================================================

def score_single_url(client: Anthropic, url: str) -> None:
    """Fetch, score, and optionally generate a post for a single URL."""
    log.info("Scoring single URL: %s", url)

    # Create a minimal article dict
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
        import requests
        resp = requests.get(url, timeout=15, headers={"User-Agent": "LinkedInRadar/1.0"})
        if resp.ok:
            title_match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
            if title_match:
                article["title"] = re.sub(r"\s+", " ", title_match.group(1)).strip()
            # Extract meta description
            desc_match = re.search(
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
                resp.text, re.IGNORECASE,
            )
            if desc_match:
                article["summary"] = desc_match.group(1).strip()[:1000]
    except Exception as exc:
        log.warning("Could not fetch URL metadata: %s", exc)

    # Score
    score_articles(client, [article])

    if article.get("score"):
        s = article["score"]
        print(f"\n{'='*60}")
        print(f"Score: {article['total_score']:.1f}/10")
        print(f"Title: {article['title']}")
        print(f"Template: {s.get('best_template', '—')}")
        print(f"Hook: {s.get('hook_idea', '—')}")
        print(f"Why relevant: {s.get('why_relevant', '—')}")
        print(f"Breakdown: viral={s.get('viral_format')}, hook={s.get('hook_strength')}, "
              f"audience={s.get('audience_resonance')}, timely={s.get('timeliness')}")
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
    """Run the full LinkedIn Radar pipeline. Returns exit code."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY environment variable is not set")
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

    # Time window
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    log.info("Looking for articles since %s (--hours %d)", cutoff.isoformat(), args.hours)

    # Load seen cache
    seen = load_seen_urls()

    # Fetch feeds
    log.info("Fetching feeds …")
    articles = asyncio.run(fetch_all_feeds(feeds, cutoff, seen))
    if not articles:
        log.info("No new articles found.")
        return 0

    # Score
    score_articles(client, articles)

    # Mark all fetched articles as seen
    now_iso = datetime.now(timezone.utc).isoformat()
    for art in articles:
        seen[art["url_hash"]] = now_iso
    save_seen_urls(seen)

    # Generate posts for high-scoring articles (unless dry run)
    if not args.dry_run:
        high_scoring = [a for a in articles if a.get("total_score", 0) >= 6 and a.get("score")]
        log.info("Generating posts for %d articles with score ≥ 6 …", len(high_scoring))
        for art in high_scoring:
            post = generate_post(client, art)
            art["generated_post"] = post
    else:
        log.info("Dry run — skipping post generation")

    # Build report
    date_str = datetime.now().strftime("%Y-%m-%d")
    report = generate_report(articles, date_str, len(feeds))

    # Write report
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"radar_{date_str}.md"
    report_path.write_text(report)
    log.info("Report written to %s", report_path)

    # Print summary to stdout
    scored = [a for a in articles if a.get("score")]
    instant = [a for a in scored if a["total_score"] >= 8]
    print(f"\n{'='*60}")
    print(f"LinkedIn Radar — {date_str}")
    print(f"{'='*60}")
    print(f"Feeds processed: {len(feeds)}")
    print(f"Articles found:  {len(articles)}")
    print(f"Scored ≥ 8:      {len(instant)}")
    print(f"Scored ≥ 5:      {len([a for a in scored if a['total_score'] >= 5])}")
    print(f"Report:          {report_path}")
    print(f"{'='*60}\n")

    # Telegram
    notify_telegram(instant)

    return 0


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LinkedIn Radar — RSS monitor & AI-powered LinkedIn post generator",
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Look back window in hours (default: 24)",
    )
    parser.add_argument(
        "--tiers", type=str, default=None,
        help="Comma-separated tiers to include (e.g. tier1_must_read,competitor_watch). "
             "competitor_watch is always included.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and score only — skip post generation",
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="Score a specific URL instead of processing feeds",
    )

    args = parser.parse_args()
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()

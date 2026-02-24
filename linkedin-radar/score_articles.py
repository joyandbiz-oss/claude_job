#!/usr/bin/env python3
"""
Score articles by 4 criteria for DataImpulse CMO LinkedIn content.
Criteria (matching linkedin_radar_v8.py scoring prompt):
  1. Viral Format (weight 0.25) — list structure, quotable numbers, 800+ char post potential
  2. Hook Strength (weight 0.25) — number/stat hook, contrarian angle, personal experience frame
  3. Audience Resonance (weight 0.30) — data/tech relevance, debate potential, ICP use cases
  4. Timeliness (weight 0.20) — breaking news, first-mover advantage
"""

import json
import re
from datetime import datetime, timezone

# Load articles
with open("/root/linkedin-radar/output/articles_2026-02-24.json") as f:
    articles = json.load(f)

# --- Keyword dictionaries for scoring ---

# High-value topics for DataImpulse CMO
CORE_TOPICS = [
    "proxy", "scraping", "web scraping", "web crawling", "bot detection",
    "captcha", "fingerprint", "anti-bot", "residential proxy", "datacenter",
    "ip rotation", "data collection", "data infrastructure", "data quality",
]

ICP_TOPICS = [
    "ad verification", "serp", "price comparison", "brand protection",
    "website testing", "streaming", "social media monitoring",
    "competitor intelligence", "market research", "seo",
]

AI_DATA_TOPICS = [
    "ai training data", "llm", "ai agent", "machine learning", "deep learning",
    "generative ai", "openai", "anthropic", "claude", "gpt", "deepseek",
    "ai model", "ai infrastructure", "ai safety", "openclaw", "codex",
    "coding agent", "vibe coding",
]

PRIVACY_LEGAL = [
    "gdpr", "ccpa", "data privacy", "data protection", "privacy",
    "lawsuit", "fine", "regulation", "compliance", "consent",
    "surveillance", "tracking", "cookie", "age verification",
]

VIRAL_SIGNALS = [
    "breaking", "just announced", "released", "launched", "new study",
    "report shows", "according to", "research finds", "billion", "million",
    "%", "$", "€",
]

PERSONAL_STORY_SIGNALS = [
    "i built", "i ported", "i made", "my experience", "years ago",
    "lessons learned", "what i learned", "show hn",
]

COMPETITORS = [
    "bright data", "oxylabs", "smartproxy", "decodo", "netnut",
    "zyte", "apify", "iproyal", "webshare", "soax",
    "nimble", "rayobyte", "infatica", "proxy-seller",
]

BIOHACKING = [
    "biohack", "health tracking", "wearable", "sleep", "longevity",
    "quantified self", "supplement", "blood test", "alzheimer",
    "cognitive", "brain", "fasting", "huberman", "attia",
]

CLOUDFLARE_INFRA = [
    "cloudflare", "akamai", "fastly", "cdn", "edge computing",
    "post-quantum", "encryption", "tls", "ssl", "dns",
]


def count_matches(text: str, keywords: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def score_article(art: dict) -> dict:
    title = art.get("title", "")
    summary = art.get("summary", "")
    source = art.get("source_name", "")
    tier = art.get("feed_tier", "")
    competitor = art.get("competitor")
    text = f"{title} {summary}".lower()
    full_text = f"{title} {summary} {source}"

    # === 1. VIRAL FORMAT (0-10) ===
    viral = 3  # base
    # Numbers in title/summary boost virality
    numbers = re.findall(r'\d+[%$€£]|\$\d+|€\d+|\d+\.\d+%|\d{2,}', title + " " + summary)
    viral += min(len(numbers) * 1.5, 3)
    # List structure
    if any(x in text for x in ["things", "ways", "tips", "steps", "reasons", "lessons"]):
        viral += 1
    # Quotable data
    if count_matches(text, VIRAL_SIGNALS) >= 2:
        viral += 1.5
    # Personal story / Show HN = great format
    if count_matches(text, PERSONAL_STORY_SIGNALS) >= 1:
        viral += 1
    # Core/AI topics are more viral on LinkedIn
    if count_matches(text, AI_DATA_TOPICS) >= 2:
        viral += 1
    viral = min(viral, 10)

    # === 2. HOOK STRENGTH (0-10) ===
    hook = 3  # base
    # Starts with number (best hook)
    if re.match(r'^\d', title) or re.match(r'^\$', title) or re.match(r'^€', title):
        hook += 2
    # Contrarian / surprising angle
    contrarian_words = ["but", "actually", "wrong", "myth", "surprisingly", "not what",
                        "destroy", "kill", "dead", "mistake", "trap", "amok", "zero"]
    if count_matches(title, contrarian_words) >= 1:
        hook += 2
    # Stat in title
    if re.search(r'\d+%|\$\d+[MB]?|€\d+[MB]?|\d+ billion|\d+ million', title):
        hook += 1.5
    # "How to" penalty
    if title.lower().startswith("how to"):
        hook = min(hook, 2)
    # Competitor mention = instant interest
    if competitor or count_matches(text, COMPETITORS) >= 1:
        hook += 1.5
    # AI topics are hot right now
    if count_matches(title, AI_DATA_TOPICS) >= 1:
        hook += 1
    # Privacy/legal = strong hooks
    if count_matches(title, PRIVACY_LEGAL) >= 1:
        hook += 1
    hook = min(hook, 10)

    # === 3. AUDIENCE RESONANCE (0-10) ===
    audience = 2  # base
    # Core proxy/scraping topics
    core_hits = count_matches(text, CORE_TOPICS)
    audience += min(core_hits * 2, 4)
    # ICP use cases
    icp_hits = count_matches(text, ICP_TOPICS)
    audience += min(icp_hits * 1.5, 3)
    # AI/data infrastructure (high engagement on LinkedIn)
    ai_hits = count_matches(text, AI_DATA_TOPICS)
    audience += min(ai_hits * 0.8, 2.5)
    # Privacy/legal (generates debate)
    priv_hits = count_matches(text, PRIVACY_LEGAL)
    audience += min(priv_hits * 1, 2)
    # Competitor mention = always relevant
    if competitor or count_matches(text, COMPETITORS) >= 1:
        audience += 2
    # Cloudflare/infra topics
    if count_matches(text, CLOUDFLARE_INFRA) >= 1:
        audience += 1.5
    # Biohacking for personal brand
    if count_matches(text, BIOHACKING) >= 1:
        audience += 1
    # Tier bonus
    if tier == "tier1_must_read":
        audience += 0.5
    if tier == "competitor_watch":
        audience += 1
    audience = min(audience, 10)

    # === 4. TIMELINESS (0-10) ===
    timely = 4  # base
    pub = art.get("published")
    if pub:
        try:
            dt = datetime.fromisoformat(pub)
            hours_ago = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            if hours_ago < 12:
                timely += 3
            elif hours_ago < 24:
                timely += 2
            elif hours_ago < 48:
                timely += 1
        except Exception:
            pass
    # Breaking news signals
    if any(w in text for w in ["breaking", "just announced", "launches", "released today",
                                "announces", "unveiled", "debuts"]):
        timely += 1.5
    # First-mover on proxy/data topics
    if count_matches(text, CORE_TOPICS) >= 1 and count_matches(text, ["new", "launch", "announce", "release"]) >= 1:
        timely += 1
    timely = min(timely, 10)

    # === WEIGHTED TOTAL ===
    total = (viral * 0.25 + hook * 0.25 + audience * 0.30 + timely * 0.20)

    # Competitor override: always score >= 6
    if competitor or count_matches(text, COMPETITORS) >= 1:
        total = max(total, 6.0)

    # Best template selection
    if count_matches(text, PRIVACY_LEGAL) >= 2:
        template = "lawsuit_gdpr"
    elif count_matches(text, PERSONAL_STORY_SIGNALS) >= 1:
        template = "personal_story"
    elif count_matches(text, CLOUDFLARE_INFRA) >= 1:
        template = "cloudflare_effect"
    elif len(numbers) >= 2:
        template = "data_point"
    elif any(w in text for w in ["free", "open source", "open-source", "released free"]):
        template = "free_resource"
    elif count_matches(title, contrarian_words) >= 1:
        template = "most_people_think"
    else:
        template = "data_point"

    # Hook idea
    hook_idea = title[:80]
    if len(numbers) > 0 and re.search(r'\d', title):
        hook_idea = title[:80]
    elif competitor:
        hook_idea = f"{competitor} just made a move. Here's why it matters."

    # Why relevant
    why = []
    if count_matches(text, CORE_TOPICS) >= 1:
        why.append("directly touches proxy/data infrastructure")
    if count_matches(text, AI_DATA_TOPICS) >= 1:
        why.append("AI/data angle for LinkedIn engagement")
    if count_matches(text, PRIVACY_LEGAL) >= 1:
        why.append("privacy/compliance angle")
    if competitor:
        why.append(f"competitor mention: {competitor}")
    if count_matches(text, BIOHACKING) >= 1:
        why.append("personal brand / biohacking content")
    if not why:
        why.append("general tech/industry awareness")

    return {
        "title": title,
        "url": art["url"],
        "source_name": source,
        "feed_tier": tier,
        "competitor": competitor,
        "published": art.get("published"),
        "summary": art.get("summary", "")[:300],
        "scores": {
            "viral_format": round(viral, 1),
            "hook_strength": round(hook, 1),
            "audience_resonance": round(audience, 1),
            "timeliness": round(timely, 1),
        },
        "total_score": round(total, 1),
        "best_template": template,
        "hook_idea": hook_idea,
        "why_relevant": "; ".join(why),
    }


# Score all articles
scored = [score_article(a) for a in articles]
scored.sort(key=lambda x: x["total_score"], reverse=True)

# Save scored articles
with open("/root/linkedin-radar/output/scored_articles.json", "w") as f:
    json.dump(scored, f, indent=2, ensure_ascii=False)

# Print top 30
print(f"\n{'='*80}")
print(f"SCORED {len(scored)} ARTICLES — TOP 30")
print(f"{'='*80}\n")

for i, art in enumerate(scored[:30], 1):
    s = art["scores"]
    badge = "🔥" if art["total_score"] >= 8 else "⚡" if art["total_score"] >= 6 else "📌" if art["total_score"] >= 5 else "·"
    print(f"{badge} #{i:2d} | {art['total_score']:4.1f}/10 | V:{s['viral_format']:3.1f} H:{s['hook_strength']:3.1f} A:{s['audience_resonance']:3.1f} T:{s['timeliness']:3.1f}")
    print(f"       {art['source_name']} | {art['feed_tier']}")
    print(f"       {art['title'][:100]}")
    print(f"       Template: {art['best_template']} | {art['why_relevant'][:80]}")
    print()

# Stats
above8 = [a for a in scored if a["total_score"] >= 8]
above6 = [a for a in scored if a["total_score"] >= 6]
above5 = [a for a in scored if a["total_score"] >= 5]
print(f"\n{'='*60}")
print(f"Score >= 8 (instant post): {len(above8)}")
print(f"Score >= 6 (generate post): {len(above6)}")
print(f"Score >= 5 (digest): {len(above5)}")
print(f"Total scored: {len(scored)}")
print(f"{'='*60}")

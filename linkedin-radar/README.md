# LinkedIn Radar

RSS feed monitor + AI scorer + LinkedIn post generator for a Data Infrastructure CMO.

## How it works

```
76 RSS feeds → Parse & deduplicate → AI Score (0-10) → Generate LinkedIn posts (EN+RU) → Markdown report + Telegram
```

## Setup

```bash
cd linkedin-radar
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."

# Optional: Telegram notifications
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="-100..."
```

## Usage

```bash
# Full daily run (last 24 hours)
python linkedin_radar.py

# Custom time window
python linkedin_radar.py --hours 48

# Only specific tiers (competitor_watch always included)
python linkedin_radar.py --tiers tier1_must_read,competitor_watch

# Dry run — fetch + score, skip post generation
python linkedin_radar.py --dry-run

# Score a single URL
python linkedin_radar.py --url "https://example.com/article"
```

## Output

Reports are saved to `output/radar_YYYY-MM-DD.md` with sections:

- **Instant Posts** (score >= 8) — full generated posts in EN + RU
- **Daily Digest** (score 5-7.9) — hook ideas and relevance notes
- **Competitor Watch** — any competitor mentions
- **Stats** — feed/article/score counts

## Feed tiers

| Tier | Sources | Default |
|------|---------|---------|
| `tier1_must_read` | TechCrunch, Wired, Cloudflare, HN, etc. | Always |
| `tier2_industry` | Data eng, security, VC, marketing | Always |
| `tier3_background` | Strategy blogs, deep AI, legal | Weekends only |
| `competitor_watch` | Bright Data, Oxylabs, Zyte, etc. | Always |

## Cost

~$0.50-1.00/day using Claude Sonnet for both scoring and generation.

## Files

```
linkedin-radar/
├── linkedin_radar.py    # Main script
├── feeds.yaml           # Feed configuration (76 sources)
├── requirements.txt     # Python dependencies
├── seen_urls.json       # Auto-generated URL cache (7-day TTL)
└── output/
    └── radar_YYYY-MM-DD.md
```

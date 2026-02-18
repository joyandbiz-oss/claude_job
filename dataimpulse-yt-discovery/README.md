# DataImpulse YouTube Influencer Discovery V3

Two-stage pipeline for discovering YouTube influencers relevant to DataImpulse (residential proxies, web scraping, browser automation, SERP tracking, ad verification, anti-detect, sneaker bots, social automation, data engineering).

**No Social Blade. No official YouTube Data API key.** Parses HTML + `ytInitialData` / `ytInitialPlayerResponse` and uses continuation tokens (`youtubei/v1/search` internal endpoints) for pagination.

## Architecture

```
Discovery (max recall) → Enrichment + Scoring (max precision) → CSV Export
```

| Stage | Script | Purpose |
|-------|--------|---------|
| 1 | `discover_channels.py` | Collect candidate channels from 3 sources |
| 2 | `enrich_and_score.py` | Fetch metrics, classify, score 0-100 |
| 3 | `export_lists.py` | Export 4 categorized CSVs |

## Project Structure

```
dataimpulse-yt-discovery/
├── config.yaml              # All configuration (queries, keywords, thresholds)
├── discover_channels.py     # Stage 1: Discovery (max recall)
├── enrich_and_score.py      # Stage 2: Enrichment + scoring (max precision)
├── export_lists.py          # Stage 3: Export CSVs from SQLite
├── lib/
│   ├── __init__.py
│   ├── youtube_fetch.py     # HTTP session, proxy, retry/backoff, cache, rate-limit
│   ├── youtube_parse.py     # Parse ytInitialData, INNERTUBE_CONTEXT, continuations
│   ├── db.py                # SQLite schema + upserts
│   └── config.py            # YAML loader + env vars
├── requirements.txt
└── README.md
```

## Quick Start

### 1. Install dependencies

```bash
pip install requests pyyaml tqdm
```

### 2. Set proxy (DataImpulse residential proxy)

```bash
export DI_PROXY_URL="http://c607101cbc744679901d_country-us:71addcef09210b43@gw.dataimpulse.com:823"
```

### 3. Run self-check

```bash
python discover_channels.py --self-check --config config.yaml
```

### 4. Run discovery (Stage 1)

```bash
# All tiers (takes 30-60 min)
python discover_channels.py --config config.yaml

# Specific tier only
python discover_channels.py --config config.yaml --tier tier1_core

# Resume after crash
python discover_channels.py --config config.yaml --resume
```

### 5. Run enrichment + scoring (Stage 2)

```bash
# All pending channels (takes 1-2 hours for 300+ channels)
python enrich_and_score.py --config config.yaml

# Limit to first 100
python enrich_and_score.py --config config.yaml --limit 100

# Force re-enrich already processed channels
python enrich_and_score.py --config config.yaml --force-reenrich
```

### 6. Export CSVs (Stage 3)

```bash
python export_lists.py --config config.yaml --output-dir ./output
```

### Output files

```
./output/creators_for_outreach_YYYY-MM-DD.csv
./output/companies_for_partnership_YYYY-MM-DD.csv
./output/competitors_monitor_YYYY-MM-DD.csv
./output/rejected_channels_log_YYYY-MM-DD.csv
```

## Discovery Sources

| Source | Method | What it catches |
|--------|--------|-----------------|
| Channel Search | `sp=EgIQAg==` + continuation pagination | Channels ranking for target queries |
| Video Search | Default search → extract author | Channels with relevant videos that don't rank in channel search |
| Seed Expansion | Related channels + re-search top video titles | Similar creators in the same niche |

## Scoring System (0-100)

| Component | Max | Factors |
|-----------|-----|---------|
| Relevance | 50 | Hard keyword matches (×8), soft matches (×3), negative penalty (−5) |
| Performance | 30 | Subscriber sweet spot, median views, engagement ratio, upload frequency, recency, shorts penalty |
| Outreach | 20 | Has email (+10), external links (+3), English (+5) |

## Classification

- **CREATOR** — Individual content creators suitable for sponsorship
- **COMPANY** — Official tool/platform channels for partnership
- **COMPETITOR** — Competing proxy/scraping services to monitor
- **REJECTED** — Fails relevance check or below score threshold

## Crash Safety

- All intermediate data stored in SQLite (`discovery.db`)
- Checkpoints after every query/channel
- Resume mode (`--resume`) skips completed queries
- URL response caching with 24h TTL
- WAL mode for concurrent read safety

## Anti-Bot Handling

- CONSENT cookie bypasses EU consent page
- Automatic proxy fallback on 403/429
- Exponential backoff up to 60s on rate limiting
- CAPTCHA page detection → skip channel (don't crash)
- SSL fallback (`verify=False`) only after SSL handshake failure through proxy
- Rate limiting: configurable requests/second (default 1.5)

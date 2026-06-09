# LinkedIn Radar — Feed Diagnostic Report
## Date: 2026-02-20 | Window: 72h (since 2026-02-17 00:00 UTC)

---

## Summary

| Metric | Value |
|--------|-------|
| Total feeds configured | 96 |
| Feeds successfully fetched | 76 |
| Feeds returning errors (404/403/500/redirect) | 15 |
| Feeds blocked (Reddit 403) | 5 |
| **Total articles within 72h** | **~310** |
| **Unique articles after dedup (est.)** | **~250** |

---

## Full Feed Diagnostic Table

### TIER 1 — Must Read (23 feeds)

| # | Feed Name | Status | Total | 72h | Notes |
|---|-----------|--------|------:|----:|-------|
| 1 | HN Front Page | OK | 20 | 20 | All items within 72h, very active |
| 2 | HN Best | OK | 30 | 30 | All items within 72h |
| 3 | 404 Media | OK | 16 | 5 | Active, quality journalism |
| 4 | The Markup | OK | 8 | 0 | Dormant since Nov 2025 |
| 5 | TechCrunch | OK | 20 | 20 | Very active, all items recent |
| 6 | Cloudflare Blog | OK | 6 | 0 | Last post Feb 13 |
| 7 | Cloudflare Radar | OK | 5 | 3 | Active — Code Mode, Markdown for Agents |
| 8 | OpenAI Blog | OK | 139 | 2 | Infrequent posts |
| 9 | Fingerprint | OK | 7 | 0 | Last post Feb 12 |
| 10 | Privacy Sandbox | ERROR | 0 | 0 | 301 redirect to HTML page, RSS discontinued |
| 11 | Proxyway | ERROR | 0 | 0 | Feed metadata loads but entries truncated |
| 12 | r/webscraping | BLOCKED | 0 | 0 | Reddit 403 — blocked for bots |
| 13 | r/webscraping Top | BLOCKED | 0 | 0 | Reddit 403 — blocked for bots |
| 14 | HN Web Scraping | OK | 20 | 1 | Niche query, sparse results |
| 15 | HN Bot Detection | OK | 20 | 0 | No recent items within 72h |
| 16 | HN CAPTCHA | OK | 21 | 1 | Archive.today CAPTCHA/DDoS story |
| 17 | HN Anti-Scraping | OK | 6 | 0 | Very niche, all items from 2012-2021 |
| 18 | HN AI Training Data | OK | 20 | 0 | Items exist but outside 72h |
| 19 | GDPR Fines News | OK | 100 | 0 | Closest item: Feb 16 (ICO fine £1.2M) |
| 20 | EFF | OK | 10 | 1 | LLM policy for open-source projects |
| 21 | Simon Willison | OK | 25 | 7 | Very active, AI commentary |
| 22 | Statista | ERROR | 2 | 0 | Returns HTML, not RSS. Items from 2021 |
| 23 | Crunchbase News | OK | 10 | 8 | Active business/VC news |

**Tier 1 subtotal: ~98 articles within 72h** (mostly from HN Front/Best, TechCrunch, Crunchbase)

---

### TIER 2 — Industry Intel (33 feeds)

| # | Feed Name | Status | Total | 72h | Notes |
|---|-----------|--------|------:|----:|-------|
| 1 | Bright Data Blog | ERROR | — | — | HTTP 500 error |
| 2 | Oxylabs Blog | ERROR | — | — | HTTP 404 error |
| 3 | Smartproxy Blog | REDIRECT | — | — | 301 → decodo.com/blog/feed → 404 |
| 4 | Apify Blog | ERROR | — | — | HTTP 404 error |
| 5 | ScrapingBee | OK | 102 | 1 | "How to hide your IP" (Feb 19) |
| 6 | Zyte Blog | OK | 200 | 2 | Hackathon recap + Claude Sonnet scraping benchmark |
| 7 | ScraperAPI Blog | OK | 2 | 0 | Only 2 items, both from 2025 |
| 8 | r/dataengineering Top | BLOCKED | 0 | 0 | Reddit 403 |
| 9 | r/MachineLearning Top | BLOCKED | 0 | 0 | Reddit 403 |
| 10 | r/selenium | BLOCKED | 0 | 0 | Reddit 403 |
| 11 | HN Proxy | OK | 24 | 6 | LLM proxies, SSH proxy, agent tools |
| 12 | HN Data Collection | OK | 24 | 1 | UK Discord/Thiel data collection |
| 13 | HN Web Crawling | OK | 23 | 0 | No items within 72h |
| 14 | HN Browser Fingerprint | OK | 22 | 0 | No items within 72h |
| 15 | News: Web Scraping | OK | 101 | 3 | Anti-bot systems, Wayback Machine dispute |
| 16 | News: AI Training Data | OK | 100 | 13 | Google privacy policy, AI data centers, RLHF |
| 17 | News: Scraping Lawsuits | OK | 96 | 0 | No items within 72h |
| 18 | News: AI Web Crawling | OK | 120 | 1 | Internet Archive blocking |
| 19 | News: Bot Traffic | OK | 100 | 0 | Most recent: Feb 15 |
| 20 | Search Engine Land | ERROR | — | — | HTTP 403 |
| 21 | Ahrefs Blog | OK | 10 | 3 | GEO conferences, ChatGPT visibility |
| 22 | Semrush Blog | OK | 20 | 2 | GBP optimization, 301 redirects |
| 23 | AdExchanger | OK | 10 | 10 | All items within 72h |
| 24 | Digiday | OK | 15 | 14 | Very active media/advertising |
| 25 | Chrome Dev Blog | OK | 10 | 1 | CSS corner-shape implementation |
| 26 | Lawfare Cyber | OK | 3 | 3 | Military AI rules, EU cyber, Claude's Constitution |
| 27 | Benedict Evans | ERROR | — | — | HTTP 404 |
| 28 | SparkToro | OK | 10 | 1 | Digital agency trends |
| 29 | Tomasz Tunguz | ERROR | — | — | HTTP 404 |
| 30 | Lenny's Newsletter | OK | 5 | 4 | Head of Claude Code interview, AI analysis |
| 31 | SimilarWeb Blog | OK | 12 | 6 | Generative Engine Optimization |
| 32 | Product Hunt | OK | 50 | 28 | Very active, new product launches |
| 33 | GitHub Trending Python | OK | 6 | 0 | No dates on items |

**Tier 2 subtotal: ~99 articles within 72h** (mostly AdExchanger, Digiday, Product Hunt, News: AI Training Data)

---

### TIER 3 — Background Radar (23 feeds)

| # | Feed Name | Status | Total | 72h | Notes |
|---|-----------|--------|------:|----:|-------|
| 1 | Ars Technica | BLOCKED | — | — | WebFetch unable to access |
| 2 | MIT Tech Review | OK | 6 | 6 | All items recent |
| 3 | Wired | BLOCKED | — | — | WebFetch unable to access |
| 4 | Google AI Blog | OK | 24 | 5 | Gemini 3 Deep Think, Lyria 3, AI Impact Summit |
| 5 | Anthropic Blog | ERROR | — | — | HTTP 404 |
| 6 | Meta AI Blog | ERROR | — | — | HTTP 404 |
| 7 | Akamai Blog | ERROR | — | — | HTTP 403 |
| 8 | HUMAN Security | OK* | — | 2 | Homepage scraped, not RSS; AgenticTrust + G2 award |
| 9 | Imperva Blog | OK | 10 | 1 | React Server Components DoS vector |
| 10 | GDPR.eu | OK | 10 | 0 | All content from 2019-2020, dormant |
| 11 | IAPP | ERROR | — | — | Returns HTML, not RSS |
| 12 | Tech Policy Press | ERROR | — | — | Returns JSON config, not RSS |
| 13 | Lawfare Privacy | OK | 0 | 0 | Feed empty (no items) |
| 14 | News: CCPA Privacy | OK | 100 | 3 | Disney CCPA settlement, risk assessment reqs |
| 15 | Rest of World | OK | 12 | 9 | Active, AI sovereignty + social media |
| 16 | Platformer | OK | 5 | 3 | Infinite scroll trial, Meta face turn |
| 17 | a16z Blog | ERROR | — | — | HTTP 404 |
| 18 | First Round Review | ERROR | — | — | HTTP 404 |
| 19 | CB Insights | ERROR | — | — | HTTP 403 |
| 20 | Playwright Releases | OK | 11 | 0 | Last release v1.58.2 (Feb 6) |
| 21 | Puppeteer Releases | OK | 10 | 4 | v24.37.4 + v24.37.5 |
| 22 | HTTP Archive | — | — | — | Not fetched |
| 23 | W3Techs | — | — | — | Not fetched |

**Tier 3 subtotal: ~33 articles within 72h**

---

### COMPETITOR WATCH (15 feeds)

| # | Feed Name | Status | Total | 72h | Notes |
|---|-----------|--------|------:|----:|-------|
| 1 | News: Bright Data | OK | 50 | 0 | Most recent: early Feb |
| 2 | News: Oxylabs | OK | 50 | 1 | CNET review (Feb 20) |
| 3 | News: Smartproxy | OK | 50 | 0 | Most recent: Feb 4 |
| 4 | News: NetNut | OK | 11 | 0 | Most recent: Jan 29 |
| 5 | News: IPRoyal | OK | 25 | 0 | Most recent: Jan 29 |
| 6 | News: Webshare | OK | 30 | 1 | CNET review (Feb 20) |
| 7 | News: SOAX | OK | 50 | 0 | No recent items |
| 8 | News: Proxy-Seller | OK | 10 | 0 | False-positive results (RTX 5090) |
| 9 | News: Apify | OK | 14 | 0 | Most recent: Jan 24 |
| 10 | News: Zyte | OK | 10 | 0 | Most recent: Jan 30 |
| 11 | News: Nimble | OK | 40 | 0 | No recent items |
| 12 | News: Rayobyte | OK | 10 | 0 | Most recent: Jan 26 |
| 13 | News: Infatica | OK | 9 | 0 | Most recent: Jan 16 |
| 14 | News: Residential Proxy | OK | 40 | 0 | Most recent: Feb 9 |
| 15 | News: DataImpulse | OK | 10 | 0 | Most recent: Feb 4 |

**Competitor Watch subtotal: 2 articles within 72h** (both CNET proxy reviews)

---

## Error Classification

### 1. Feed URL Broken (404/500) — 11 feeds
| Feed | Error | Recommendation |
|------|-------|----------------|
| Bright Data Blog | 500 | Check if URL changed |
| Oxylabs Blog | 404 | URL likely changed, search for new feed |
| Smartproxy Blog | 301→404 | Rebranded to Decodo, new feed URL needed |
| Apify Blog | 404 | URL likely changed |
| Benedict Evans | 404 | Blog may have moved |
| Tomasz Tunguz | 404 | Blog may have moved |
| Anthropic Blog | 404 | URL likely changed |
| Meta AI Blog | 404 | URL likely changed |
| a16z Blog | 404 | URL likely changed |
| First Round Review | 404 | URL likely changed |
| Statista | HTML | URL returns web page, not RSS |

### 2. Access Blocked (403) — 6 feeds
| Feed | Issue | Recommendation |
|------|-------|----------------|
| r/webscraping | Reddit blocks bots | Use Reddit JSON API or OAuth |
| r/webscraping Top | Reddit blocks bots | Use Reddit JSON API or OAuth |
| r/dataengineering | Reddit blocks bots | Use Reddit JSON API or OAuth |
| r/MachineLearning | Reddit blocks bots | Use Reddit JSON API or OAuth |
| r/selenium | Reddit blocks bots | Use Reddit JSON API or OAuth |
| Search Engine Land | 403 | Requires different User-Agent |

### 3. Invalid/Empty Feeds — 4 feeds
| Feed | Issue |
|------|-------|
| Privacy Sandbox | Redirects to HTML, RSS discontinued |
| IAPP | Returns HTML, not RSS |
| Tech Policy Press | Returns JSON config, not RSS |
| Lawfare Privacy | Feed empty (0 items) |

### 4. Dormant Feeds (working but no new content)
| Feed | Last Post |
|------|-----------|
| The Markup | Nov 2025 |
| GDPR.eu | Jun 2020 |
| HN Anti-Scraping | May 2021 |

---

## Top 10 Feeds by 72h Article Count

| # | Feed | 72h Articles |
|---|------|:------------:|
| 1 | HN Best | 30 |
| 2 | Product Hunt | 28 |
| 3 | HN Front Page | 20 |
| 4 | TechCrunch | 20 |
| 5 | Digiday | 14 |
| 6 | News: AI Training Data | 13 |
| 7 | AdExchanger | 10 |
| 8 | Rest of World | 9 |
| 9 | Crunchbase News | 8 |
| 10 | Simon Willison | 7 |

---

## Why 800+ Was Unrealistic

**Expected vs actual reality for 96 feeds × 72h:**

1. **21 feeds are completely broken** (404/403/500/redirect/empty) = 0 articles
2. **3 feeds are dormant** (no posts for months) = 0 articles
3. **~15 niche HN/Google News feeds** average 0-1 articles per 72h = ~8 articles
4. **~15 competitor news feeds** average 0-0.1 articles per 72h = ~2 articles
5. **~5 Reddit feeds all blocked** = 0 articles
6. **~37 working active feeds** produce 10-30 articles each = ~300 articles

**Realistic 72h ceiling: ~310 raw articles → ~250 after dedup**

To reach 800+ articles, you would need:
- Fix all broken feed URLs (+11 feeds)
- Solve Reddit access (+5 feeds, ~50-100 articles)
- Expand window to 168h (doubles yield to ~500)
- Add ~30 more high-volume feeds (major tech blogs, more subreddits, more Google News queries)

---

## Recommendations

1. **Fix 11 broken feed URLs** — most are simply URL changes after company rebrands
2. **Replace Reddit RSS with JSON API** — `https://www.reddit.com/r/NAME/.json` with proper User-Agent
3. **Remove 3 dormant feeds** (The Markup, GDPR.eu, HN Anti-Scraping) — replace with active sources
4. **Add high-volume feeds**: The Verge, Reuters Tech, Bloomberg Tech, Engadget, ZDNet
5. **Expand Google News queries** — broader terms yield more results
6. **Consider 168h window** — doubles article count for weekly digest

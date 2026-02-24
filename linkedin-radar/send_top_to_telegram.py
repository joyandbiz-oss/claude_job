#!/usr/bin/env python3
"""Send top-scored articles (>= 8) to Telegram."""

import os
import requests
from pathlib import Path

# Load .env
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for chunk_start in range(0, len(text), 4000):
        chunk = text[chunk_start:chunk_start + 4000]
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }, timeout=15)
        print(f"  Status: {resp.status_code}, OK: {resp.json().get('ok')}")
        if not resp.json().get("ok"):
            print(f"  Error: {resp.json().get('description')}")
            # Retry without Markdown
            resp2 = requests.post(url, json={
                "chat_id": CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            }, timeout=15)
            print(f"  Retry (no MD): {resp2.status_code}, OK: {resp2.json().get('ok')}")

# Header
header = """🔥 *LinkedIn Radar* — 3 Instant Posts (score ≥ 8)
📅 2026-02-24 | 256 articles scanned | 105 feeds

"""

print("Sending header...")
send_message(header)

# Article 1: SerpApi vs Google (8.5)
art1 = """🔥 *8.5/10* | SerpApi vs Google Scraping Lawsuit

*SerpApi says Google doesn't own the internet, files motion to dismiss web scraping lawsuit*

Source: News: Scraping Lawsuits
V:7 H:9 A:9 T:8

💡 Hook: "Google doesn't own the internet." — SerpApi just filed to dismiss Google's scraping lawsuit. Sets precedent for entire data industry.

🔗 Why: Landmark case — defines who can access public web data. Directly impacts proxy/scraping industry.

📝 Post template: lawsuit\\_gdpr
"""

print("Sending article 1 (SerpApi)...")
send_message(art1)

# Article 2: Anthropic vs Chinese AI Labs (8.0)
art2 = """🔥 *8.0/10* | Anthropic: 24K Fake Accounts Mining Claude

*Anthropic accuses Chinese AI labs of mining Claude as US debates AI chip exports*

Source: TechCrunch
V:8 H:8 A:8 T:8

💡 Hook: 24,000 fake accounts used by DeepSeek, Moonshot, MiniMax to distill Claude. Industrial-scale scraping meets AI security.

🔗 Why: Scraping/proxy rotation + identity management at AI scale. Anti-bot tech now needed for AI APIs.

📝 Post template: cloudflare\\_effect
URL: https://techcrunch.com/2026/02/23/anthropic-accuses-chinese-ai-labs-of-mining-claude-as-us-debates-ai-chip-exports/
"""

print("Sending article 2 (Anthropic)...")
send_message(art2)

# Article 3: Bright Data Patent (8.0)
art3 = """🔥 *8.0/10* | Supreme Court vs Bright Data Patent

*Supreme Court Leaves Bright Data Patent Invalidation Ruling Intact*

Source: News: Bright Data (competitor\\_watch)
V:6 H:8 A:9 T:7

💡 Hook: Supreme Court declined Bright Data's patent appeal. Patent invalidation stands. Competition opens up for $300M+ industry.

🔗 Why: Direct competitor news. Bright Data ($300M rev) loses IP moat. Changes M&A dynamics.

📝 Post template: lawsuit\\_gdpr
"""

print("Sending article 3 (Bright Data)...")
send_message(art3)

# Summary
summary = """📊 *Full Radar Summary*:
• 256 articles from 105 feeds (72h window)
• Score ≥ 8: 3 articles (instant posts)
• Score ≥ 6: 10 articles (posts generated EN+RU)
• Score ≥ 5: 27 articles (digest)
• Competitor mentions: 3 (Bright Data, SOAX, Zyte)

Top themes: Web scraping legality, AI model protection, proxy infrastructure for AI, privacy regulation.
"""

print("Sending summary...")
send_message(summary)

print("\nDone! All messages sent to Telegram.")

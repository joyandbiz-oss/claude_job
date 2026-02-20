#!/usr/bin/env python3
"""
send_telegram.py — Sends LinkedIn Radar results to Telegram.
Token and Chat ID from env vars or command-line args.
NEVER hardcodes secrets.
"""

import html
import os
import sys
import time

import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def escape_html(text: str) -> str:
    """Escape HTML special chars for Telegram HTML mode."""
    return html.escape(text, quote=False)


def send_message(token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    """Send a message, splitting if >4096 chars."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = []
    while len(text) > 4000:
        split_at = text.rfind("\n", 0, 4000)
        if split_at == -1:
            split_at = 4000
        chunks.append(text[:split_at])
        text = text[split_at:]
    chunks.append(text)

    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }, timeout=15)
            if resp.status_code != 200:
                # Retry without parse_mode
                resp2 = requests.post(url, json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                }, timeout=15)
                if resp2.status_code != 200:
                    print(f"  ERROR: {resp2.status_code} {resp2.text[:200]}")
                    return False
            time.sleep(1)
        except Exception as e:
            print(f"  SEND ERROR: {e}")
            return False
    return True


def main():
    token = BOT_TOKEN
    chat_id = CHAT_ID

    if not token:
        token = input("Enter TELEGRAM_BOT_TOKEN: ").strip()
    if not chat_id:
        chat_id = input("Enter TELEGRAM_CHAT_ID: ").strip()

    if not token or not chat_id:
        print("ERROR: token and chat_id are required")
        sys.exit(1)

    # Read posts from command line args or stdin
    if len(sys.argv) > 1:
        # File mode: read messages from file, one per double-newline
        with open(sys.argv[1]) as f:
            content = f.read()
        messages = content.split("\n===NEXT===\n")
        for i, msg in enumerate(messages):
            msg = msg.strip()
            if not msg:
                continue
            print(f"Sending message {i+1}/{len(messages)}...")
            send_message(token, chat_id, msg, parse_mode="")
        print("Done!")
    else:
        print("Usage: python send_telegram.py <messages_file>")
        print("  Messages file: plain text, separated by ===NEXT===")


if __name__ == "__main__":
    main()

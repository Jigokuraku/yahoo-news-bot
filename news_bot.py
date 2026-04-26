import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

import requests
import yfinance as yf

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TICKERS_FILE = Path("tickers.txt")
SEEN_FILE = Path("seen.json")
MAX_SEEN = 2000  # 무한 증식 방지


def load_tickers():
    if not TICKERS_FILE.exists():
        print(f"Missing {TICKERS_FILE}", file=sys.stderr)
        return []
    tickers = []
    for line in TICKERS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line.upper())
    return tickers


def load_seen():
    if not SEEN_FILE.exists():
        return []
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_seen(seen_list):
    trimmed = seen_list[-MAX_SEEN:]
    SEEN_FILE.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")


def normalize(item):
    """yfinance의 신/구 뉴스 포맷 모두 처리."""
    # 신 포맷 (yfinance >= 0.2.40)
    if isinstance(item.get("content"), dict):
        c = item["content"]
        url = ""
        for key in ("canonicalUrl", "clickThroughUrl"):
            obj = c.get(key) or {}
            if isinstance(obj, dict) and obj.get("url"):
                url = obj["url"]
                break
        provider = c.get("provider") or {}
        publisher = provider.get("displayName", "") if isinstance(provider, dict) else ""
        return {
            "id": item.get("id") or c.get("id") or url,
            "title": c.get("title", "(no title)"),
            "url": url,
            "publisher": publisher,
            "summary": c.get("summary") or c.get("description") or "",
            "pub_date": c.get("pubDate") or c.get("displayTime") or "",
        }
    # 구 포맷
    pub = ""
    if item.get("providerPublishTime"):
        pub = datetime.fromtimestamp(
            item["providerPublishTime"], tz=timezone.utc
        ).isoformat()
    return {
        "id": item.get("uuid") or item.get("link") or item.get("title", ""),
        "title": item.get("title", "(no title)"),
        "url": item.get("link", ""),
        "publisher": item.get("publisher", ""),
        "summary": "",
        "pub_date": pub,
    }


def fetch_news(ticker):
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception as e:
        print(f"[{ticker}] fetch failed: {e}", file=sys.stderr)
        return []
    return [normalize(x) for x in raw]


def build_embed(ticker, news):
    embed = {
        "title": (news["title"] or "(no title)")[:256],
        "author": {"name": f"${ticker}"},
        "color": 0x1F8B4C,
        "footer": {"text": news["publisher"] or "Yahoo Finance"},
    }
    if news["url"]:
        embed["url"] = news["url"]
    if news["summary"]:
        embed["description"] = news["summary"][:400]
    if news["pub_date"] and "T" in news["pub_date"]:
        embed["timestamp"] = news["pub_date"]
    return embed


def send_to_discord(embeds):
    if not WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL not set", file=sys.stderr)
        return
    # Discord는 메시지당 최대 10 embed
    for i in range(0, len(embeds), 10):
        batch = embeds[i:i + 10]
        resp = requests.post(WEBHOOK_URL, json={"embeds": batch}, timeout=15)
        if resp.status_code >= 300:
            print(f"Discord error {resp.status_code}: {resp.text}", file=sys.stderr)


def main():
    tickers = load_tickers()
    if not tickers:
        print("No tickers configured.")
        return

    first_run = not SEEN_FILE.exists()
    seen = set(load_seen())
    new_embeds = []
    new_ids = []

    for ticker in tickers:
        for news in fetch_news(ticker):
            nid = news["id"]
            if not nid or nid in seen:
                continue
            seen.add(nid)
            new_ids.append(nid)
            if not first_run:
                new_embeds.append(build_embed(ticker, news))

    if first_run:
        print(f"First run: {len(new_ids)} existing items marked as seen (not sent).")
    else:
        print(f"Found {len(new_embeds)} new items across {len(tickers)} tickers.")
        if new_embeds:
            send_to_discord(new_embeds)

    existing = load_seen()
    existing.extend(new_ids)
    save_seen(existing)


if __name__ == "__main__":
    main()

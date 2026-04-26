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
MAX_SEEN = 2000

# 종목별 색깔 (Discord embed 좌측 세로 바)
# 등록 안 된 종목은 DEFAULT_COLOR로 나오되 자동 색상 할당됨
TICKER_COLORS = {
    "AAPL": 0xA2AAAD,   # Apple - silver
    "MSFT": 0x00A4EF,   # Microsoft - blue
    "NVDA": 0x76B900,   # NVIDIA - green
    "TSLA": 0xCC0000,   # Tesla - red
    "GOOGL": 0x4285F4,  # Google - blue
    "AMZN": 0xFF9900,   # Amazon - orange
    "META": 0x0668E1,   # Meta - blue
    "AMD":  0xED1C24,   # AMD - red
    "NFLX": 0xE50914,   # Netflix - red
}
DEFAULT_COLOR = 0x95A5A6


def auto_color(ticker):
    """TICKER_COLORS에 없는 종목도 항상 같은 색으로 나오게 해시 기반 자동 할당."""
    if ticker in TICKER_COLORS:
        return TICKER_COLORS[ticker]
    h = 0
    for ch in ticker:
        h = (h * 31 + ord(ch)) & 0xFFFFFF
    # 너무 어둡거나 흐릿한 색 회피 (최소 채도/명도 확보)
    r = 0x40 + (h & 0xBF)
    g = 0x40 + ((h >> 8) & 0xBF)
    b = 0x40 + ((h >> 16) & 0xBF)
    return (r << 16) | (g << 8) | b


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
        "color": auto_color(ticker),
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
    for i in range(0, len(embeds), 10):
        batch = embeds[i:i + 10]
        try:
            resp = requests.post(WEBHOOK_URL, json={"embeds": batch}, timeout=15)
            if resp.status_code >= 300:
                print(f"Discord error {resp.status_code}: {resp.text}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"Discord request failed: {e}", file=sys.stderr)


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

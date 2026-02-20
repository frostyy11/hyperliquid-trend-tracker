#!/usr/bin/env python3
"""
Hyperliquid Perps Trend Tracker
Tracks 24h, 7d, and 14d price % changes for all perps on Hyperliquid.
"""

import json
import time
import sys
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Optional

# ── ANSI colors ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"
BLUE   = "\033[94m"
MAGENTA = "\033[95m"

HL_API = "https://api.hyperliquid.xyz/info"
CG_API = "https://api.coingecko.com/api/v3"
CG_API_KEY = ""  # optional – set your CoinGecko API key here for higher rate limits


def hl_post(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        HL_API,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def cg_get(path: str, params: dict) -> any:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{CG_API}/{path}?{qs}"
    headers = {"accept": "application/json"}
    if CG_API_KEY:
        headers["x-cg-demo-api-key"] = CG_API_KEY
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ── Hyperliquid ───────────────────────────────────────────────────────────────

def fetch_all_assets() -> list[str]:
    """Return list of all perpetual asset names from Hyperliquid."""
    meta = hl_post({"type": "meta"})
    return [asset["name"] for asset in meta["universe"]]


def fetch_current_prices() -> dict[str, float]:
    """Fetch current mark prices for all perps via allMids."""
    mids = hl_post({"type": "allMids"})
    return {coin: float(price) for coin, price in mids.items()}


# ── CoinGecko ─────────────────────────────────────────────────────────────────

# Some HL tickers differ from CoinGecko IDs — add overrides here as needed
CG_ID_OVERRIDES: dict[str, str] = {
    "HYPE":  "hyperliquid",
    "kBONK": "bonk",
    "kPEPE": "pepe",
    "kSHIB": "shiba-inu",
    "kFLOKI":"floki",
    "kLUNC": "terra-luna",
    "kDOGE": "dogecoin",
    "WBTC":  "wrapped-bitcoin",
    "WETH":  "weth",
    "stETH": "staked-ether",
}

_CG_MARKET_CACHE: dict[str, dict] = {}


def _build_cg_cache(symbols: list[str]) -> None:
    """
    Fetch CoinGecko /coins/markets in batches of 250.
    Populates _CG_MARKET_CACHE keyed by uppercase symbol.
    """
    global _CG_MARKET_CACHE
    _CG_MARKET_CACHE = {}

    # First pass: collect by symbol (CoinGecko returns top coin per symbol)
    per_page = 250
    page = 1
    seen = 0
    # We fetch pages until we have covered enough of the market to match all HL assets
    # (most HL perps are top-500 coins by market cap)
    for page in range(1, 4):  # up to 750 coins
        try:
            rows = cg_get("coins/markets", {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": page,
                "price_change_percentage": "24h,7d,14d",
                "sparkline": "false",
            })
        except Exception as e:
            print(f"\n  {YELLOW}CoinGecko page {page} error: {e}{RESET}")
            break
        if not rows:
            break
        for row in rows:
            sym = row.get("symbol", "").upper()
            if sym not in _CG_MARKET_CACHE:
                _CG_MARKET_CACHE[sym] = row
        seen += len(rows)
        if len(rows) < per_page:
            break
        time.sleep(0.4)  # respect free-tier rate limit between pages

    # Second pass: apply ID overrides for known mismatches
    for hl_sym, cg_id in CG_ID_OVERRIDES.items():
        try:
            rows = cg_get("coins/markets", {
                "vs_currency": "usd",
                "ids": cg_id,
                "price_change_percentage": "24h,7d,14d",
                "sparkline": "false",
            })
            if rows:
                _CG_MARKET_CACHE[hl_sym.upper()] = rows[0]
        except Exception:
            pass


def fetch_cg_changes(symbols: list[str]) -> dict[str, dict]:
    """
    Return {SYMBOL: {24h, 7d, 14d}} for each symbol using the cache.
    """
    result: dict[str, dict] = {}
    for sym in symbols:
        key = sym.upper()
        row = _CG_MARKET_CACHE.get(key)
        if row is None:
            result[sym] = {"24h": None, "7d": None, "14d": None}
            continue
        result[sym] = {
            "24h": row.get("price_change_percentage_24h"),
            "7d":  row.get("price_change_percentage_7d_in_currency"),
            "14d": row.get("price_change_percentage_14d_in_currency"),
        }
    return result


def color_pct(val: Optional[float]) -> str:
    if val is None:
        return f"{DIM}  N/A  {RESET}"
    bar = "▲" if val >= 0 else "▼"
    col = GREEN if val >= 0 else RED
    if abs(val) >= 20:
        col = MAGENTA if val >= 0 else RED
    return f"{col}{bar}{val:+.2f}%{RESET}"



def clear_screen():
    print("\033[2J\033[H", end="")


def print_header(count: int, last_update: str, filter_str: str = ""):
    width = 90
    print(f"\n{BOLD}{CYAN}{'━' * width}{RESET}")
    title = "  🔥  HYPERLIQUID PERPS TREND TRACKER"
    if filter_str:
        title += f"  [filter: {filter_str.upper()}]"
    print(f"{BOLD}{CYAN}{title}{RESET}")
    print(f"{DIM}  {count} assets  •  updated {last_update}  •  Ctrl+C to quit{RESET}")
    print(f"{BOLD}{CYAN}{'━' * width}{RESET}")
    print(
        f"  {BOLD}{'ASSET':<10} {'24h':>10} {'7d':>10} {'14d':>10}{RESET}"
    )
    print(f"  {'─' * 44}")


def print_row(rank: int, coin: str, price: float, p24: Optional[float],
              p7: Optional[float], p14: Optional[float]):
    print(
        f"  {DIM}{rank:>3}.{RESET} {BOLD}{WHITE}{coin:<9}{RESET}"
        f" {color_pct(p24):>10}  {color_pct(p7):>10}  {color_pct(p14):>10}"
    )


def print_footer(sort_key: str, ascending: bool):
    print(f"\n  {DIM}Sort: {sort_key} {'↑' if ascending else '↓'}  "
          f"│  Keys: [24h] [7d] [14d] [coin]  │  Refresh: 60s{RESET}\n")


def collect_data(assets: list[str], current_prices: dict[str, float],
                 verbose: bool = True) -> list[dict]:
    if verbose:
        print(f"  {DIM}Fetching % changes from CoinGecko...{RESET}", flush=True)
    _build_cg_cache(assets)
    changes = fetch_cg_changes(assets)

    results = []
    for coin in assets:
        price = current_prices.get(coin)
        if price is None:
            continue
        c = changes.get(coin, {})
        results.append({
            "coin": coin,
            "price": price,
            "24h": c.get("24h"),
            "7d":  c.get("7d"),
            "14d": c.get("14d"),
        })
    return results


def sort_data(data: list[dict], key: str, ascending: bool) -> list[dict]:
    def sort_val(row):
        v = row.get(key)
        if v is None:
            return float("-inf") if not ascending else float("inf")
        return v
    return sorted(data, key=sort_val, reverse=not ascending)


def display(data: list[dict], sort_key: str, ascending: bool,
            filter_str: str = "", top_n: int = 0):
    clear_screen()
    rows = data
    if filter_str:
        rows = [r for r in rows if filter_str.upper() in r["coin"].upper()]
    if top_n:
        rows = rows[:top_n]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print_header(len(rows), ts, filter_str)
    for i, row in enumerate(rows, 1):
        print_row(i, row["coin"], row["price"],
                  row["24h"], row["7d"], row["14d"])
    print_footer(sort_key, ascending)


def run_once(args):
    """Single-shot mode: fetch, print, exit."""
    print(f"\n{BOLD}{CYAN}  Hyperliquid Perps Trend Tracker{RESET}")
    print(f"  {DIM}Fetching asset list...{RESET}")
    assets = fetch_all_assets()
    print(f"  {DIM}Found {len(assets)} perps. Fetching prices & candles...{RESET}\n")
    current = fetch_current_prices()
    data = collect_data(assets, current, verbose=True)
    data = sort_data(data, args.sort, args.ascending)
    display(data, args.sort, args.ascending, args.filter, args.top)


def run_live(args):
    """Live refresh mode."""
    refresh_interval = args.interval
    sort_key = args.sort
    ascending = args.ascending

    print(f"\n{BOLD}{CYAN}  Hyperliquid Perps Trend Tracker – Live Mode{RESET}")
    print(f"  {DIM}Fetching asset list...{RESET}")
    assets = fetch_all_assets()
    print(f"  {DIM}Found {len(assets)} perps. Starting data collection...{RESET}\n")

    while True:
        try:
            current = fetch_current_prices()
            data = collect_data(assets, current, verbose=True)
            data = sort_data(data, sort_key, ascending)
            display(data, sort_key, ascending, args.filter, args.top)
            for remaining in range(refresh_interval, 0, -1):
                print(f"\r  {DIM}Next refresh in {remaining:>3}s  (Ctrl+C to quit){RESET}   ", end="", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n\n  {YELLOW}Goodbye!{RESET}\n")
            break
        except urllib.error.URLError as e:
            print(f"\n  {RED}Network error: {e}. Retrying in 10s...{RESET}")
            time.sleep(10)


def main():
    parser = argparse.ArgumentParser(
        description="Hyperliquid Perps CLI Trend Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python hl_trend_tracker.py                        # one-shot, sort by 24h
  python hl_trend_tracker.py --live                 # auto-refresh every 60s
  python hl_trend_tracker.py --sort 7d --top 20     # top 20 by 7-day change
  python hl_trend_tracker.py --sort 14d --asc       # worst 14d performers first
  python hl_trend_tracker.py --filter BTC           # show only BTC
  python hl_trend_tracker.py --live --interval 120  # refresh every 2 minutes

Note: % changes come from CoinGecko (fast, 3 API calls total).
      Current mark prices come from Hyperliquid directly.
      Set CG_API_KEY in the script for higher CoinGecko rate limits.
        """
    )
    parser.add_argument("--live", action="store_true",
                        help="Auto-refresh mode (default: single-shot)")
    parser.add_argument("--interval", type=int, default=60,
                        help="Refresh interval in seconds (live mode, default: 60)")
    parser.add_argument("--sort", choices=["24h", "7d", "14d", "coin"],
                        default="24h",
                        help="Column to sort by (default: 24h)")
    parser.add_argument("--asc", dest="ascending", action="store_true",
                        help="Sort ascending (default: descending)")
    parser.add_argument("--filter", default="",
                        help="Filter assets by name substring (e.g. BTC, ETH, SOL)")
    parser.add_argument("--top", type=int, default=0,
                        help="Show only top N results (0 = all)")

    args = parser.parse_args()

    # map sort key for dict lookup
    if args.sort == "coin":
        args.sort = "coin"

    try:
        if args.live:
            run_live(args)
        else:
            run_once(args)
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Goodbye!{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()

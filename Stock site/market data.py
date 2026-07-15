import os
import time
import requests
from datetime import datetime, date, timedelta
from functools import lru_cache

POLYGON_BASE = "https://api.polygon.io"
API_KEY = os.environ.get("POLYGON_API_KEY")

# Simple in-memory price cache to avoid burning rate limits
_price_cache = {}
CACHE_TTL = 300  # 5 minutes


def _get(path: str, params: dict = None) -> dict:
    params = params or {}
    params["apiKey"] = API_KEY
    resp = requests.get(f"{POLYGON_BASE}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_current_price(ticker: str) -> float | None:
    """Get latest price for a ticker, with in-memory cache."""
    now = time.time()
    cached = _price_cache.get(ticker)
    if cached and now - cached["ts"] < CACHE_TTL:
        return cached["price"]

    try:
        # Use previous close as "current" price (free tier friendly)
        data = _get(f"/v2/aggs/ticker/{ticker}/prev")
        results = data.get("results")
        if results:
            price = results[0]["c"]  # closing price
            _price_cache[ticker] = {"price": price, "ts": now}
            return price
    except Exception as e:
        print(f"[Polygon] Price fetch failed for {ticker}: {e}")
    return None


def get_prices_bulk(tickers: list[str]) -> dict[str, float]:
    """Fetch prices for multiple tickers. Returns {ticker: price}."""
    result = {}
    for ticker in tickers:
        price = get_current_price(ticker)
        if price is not None:
            result[ticker] = price
    return result


def get_historical_prices(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """
    Get daily closing prices for a date range.
    from_date / to_date: 'YYYY-MM-DD'
    Returns list of {date, close} dicts sorted ascending.
    """
    try:
        data = _get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}",
            params={"adjusted": "true", "sort": "asc", "limit": 365}
        )
        results = data.get("results", [])
        return [
            {
                "date": datetime.utcfromtimestamp(r["t"] / 1000).strftime("%Y-%m-%d"),
                "close": r["c"]
            }
            for r in results
        ]
    except Exception as e:
        print(f"[Polygon] Historical fetch failed for {ticker}: {e}")
        return []


def get_dividends(ticker: str) -> list[dict]:
    """
    Get dividend history for a ticker.
    Returns list of {ex_dividend_date, cash_amount, pay_date} dicts.
    """
    try:
        data = _get(
            "/v3/reference/dividends",
            params={"ticker": ticker, "limit": 20, "sort": "ex_dividend_date", "order": "desc"}
        )
        results = data.get("results", [])
        return [
            {
                "ex_date": r.get("ex_dividend_date"),
                "pay_date": r.get("pay_date"),
                "amount": r.get("cash_amount"),
            }
            for r in results
        ]
    except Exception as e:
        print(f"[Polygon] Dividend fetch failed for {ticker}: {e}")
        return []


def get_ticker_details(ticker: str) -> dict:
    """Get company name and basic info."""
    try:
        data = _get(f"/v3/reference/tickers/{ticker}")
        r = data.get("results", {})
        return {
            "name": r.get("name", ticker),
            "sector": r.get("sic_description", ""),
            "market_cap": r.get("market_cap"),
        }
    except Exception as e:
        print(f"[Polygon] Details fetch failed for {ticker}: {e}")
        return {"name": ticker, "sector": "", "market_cap": None}
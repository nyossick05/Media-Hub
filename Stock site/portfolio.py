from flask import Blueprint, render_template, request, jsonify, session
from datetime import date, timedelta
import os
from supabase import create_client

from services.market_data import get_prices_bulk
from services.calculations import (
    calc_unrealized_pnl,
    calc_portfolio_totals,
    calc_allocation,
    calc_benchmark_comparison,
)

portfolio_bp = Blueprint("portfolio", __name__)

def get_supabase():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def get_or_create_portfolio(sb, user_id: str) -> dict:
    result = sb.table("portfolios").select("*").eq("user_id", user_id).limit(1).execute()
    if result.data:
        return result.data[0]
    new = sb.table("portfolios").insert({"user_id": user_id, "name": "My Portfolio", "benchmark": "SPY"}).execute()
    return new.data[0]


@portfolio_bp.route("/")
def dashboard():
    # For dev: use a hardcoded user_id. In production, use Supabase Auth.
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))

    sb = get_supabase()
    portfolio = get_or_create_portfolio(sb, user_id)
    portfolio_id = portfolio["id"]

    # Fetch holdings
    holdings_rows = sb.table("holdings").select("*").eq("portfolio_id", portfolio_id).execute().data or []

    # Fetch live prices
    tickers = [h["ticker"] for h in holdings_rows]
    prices = get_prices_bulk(tickers) if tickers else {}

    # Enrich holdings with live prices and P&L
    enriched = []
    for h in holdings_rows:
        cp = prices.get(h["ticker"])
        pnl = calc_unrealized_pnl(h["shares"], h.get("cost_basis_per_share"), cp)
        enriched.append({**h, "current_price": cp, **pnl})

    totals = calc_portfolio_totals(enriched)
    allocation = calc_allocation(enriched)

    # Dividends
    dividends = sb.table("dividends").select("*").eq("portfolio_id", portfolio_id).order("ex_date", desc=True).execute().data or []

    # Benchmark comparison (1 year)
    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=365)).isoformat()
    comparison = calc_benchmark_comparison(enriched, portfolio["benchmark"], from_date, to_date)

    return render_template(
        "dashboard.html",
        portfolio=portfolio,
        holdings=enriched,
        totals=totals,
        allocation=allocation,
        dividends=dividends,
        comparison=comparison,
    )


@portfolio_bp.route("/api/portfolio/summary")
def api_summary():
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))
    sb = get_supabase()
    portfolio = get_or_create_portfolio(sb, user_id)
    holdings_rows = sb.table("holdings").select("*").eq("portfolio_id", portfolio["id"]).execute().data or []
    tickers = [h["ticker"] for h in holdings_rows]
    prices = get_prices_bulk(tickers) if tickers else {}
    enriched = []
    for h in holdings_rows:
        cp = prices.get(h["ticker"])
        pnl = calc_unrealized_pnl(h["shares"], h.get("cost_basis_per_share"), cp)
        enriched.append({**h, "current_price": cp, **pnl})
    return jsonify({
        "totals": calc_portfolio_totals(enriched),
        "allocation": calc_allocation(enriched),
    })
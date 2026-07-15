from services.market_data import get_historical_prices


def calc_unrealized_pnl(shares: float, cost_basis: float | None, current_price: float | None) -> dict:
    """Calculate unrealized P&L for a single position."""
    if current_price is None:
        return {"current_value": None, "gain_loss": None, "gain_loss_pct": None}

    current_value = shares * current_price

    if cost_basis is not None:
        total_cost = shares * cost_basis
        gain_loss = current_value - total_cost
        gain_loss_pct = (gain_loss / total_cost) * 100 if total_cost else None
    else:
        gain_loss = None
        gain_loss_pct = None

    return {
        "current_value": round(current_value, 2),
        "gain_loss": round(gain_loss, 2) if gain_loss is not None else None,
        "gain_loss_pct": round(gain_loss_pct, 2) if gain_loss_pct is not None else None,
    }


def calc_portfolio_totals(holdings: list[dict]) -> dict:
    """
    Summarize total portfolio value, cost, and gain/loss.
    Each holding dict should have: shares, cost_basis_per_share, current_price
    """
    total_value = 0
    total_cost = 0
    has_cost = True

    for h in holdings:
        cp = h.get("current_price")
        cb = h.get("cost_basis_per_share")
        shares = h.get("shares", 0)

        if cp is not None:
            total_value += shares * cp
        if cb is not None:
            total_cost += shares * cb
        else:
            has_cost = False

    gain_loss = (total_value - total_cost) if has_cost else None
    gain_loss_pct = ((gain_loss / total_cost) * 100) if (has_cost and total_cost) else None

    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2) if has_cost else None,
        "total_gain_loss": round(gain_loss, 2) if gain_loss is not None else None,
        "total_gain_loss_pct": round(gain_loss_pct, 2) if gain_loss_pct is not None else None,
    }


def calc_allocation(holdings: list[dict]) -> list[dict]:
    """
    Return allocation breakdown by ticker (% of total portfolio value).
    """
    total_value = sum(
        (h.get("shares", 0) * h.get("current_price", 0))
        for h in holdings
        if h.get("current_price") is not None
    )

    if total_value == 0:
        return []

    allocations = []
    for h in holdings:
        cp = h.get("current_price")
        if cp is None:
            continue
        value = h["shares"] * cp
        allocations.append({
            "ticker": h["ticker"],
            "value": round(value, 2),
            "pct": round((value / total_value) * 100, 2),
        })

    return sorted(allocations, key=lambda x: x["pct"], reverse=True)


def calc_benchmark_comparison(
    holdings: list[dict],
    benchmark_ticker: str,
    from_date: str,
    to_date: str,
) -> dict:
    """
    Compare portfolio performance vs a benchmark over a date range.

    Returns:
      portfolio_pct_change: weighted average return of holdings
      benchmark_pct_change: benchmark return over same period
    """
    # Get benchmark performance
    bench_prices = get_historical_prices(benchmark_ticker, from_date, to_date)
    if len(bench_prices) < 2:
        return {"portfolio_pct_change": None, "benchmark_pct_change": None, "series": []}

    bench_start = bench_prices[0]["close"]
    bench_end = bench_prices[-1]["close"]
    benchmark_pct = ((bench_end - bench_start) / bench_start) * 100

    # Get portfolio weighted return
    total_cost = sum(
        h["shares"] * h["cost_basis_per_share"]
        for h in holdings
        if h.get("cost_basis_per_share") and h.get("current_price")
    )

    if total_cost == 0:
        return {
            "benchmark_pct_change": round(benchmark_pct, 2),
            "portfolio_pct_change": None,
            "benchmark_series": [{"date": p["date"], "value": ((p["close"] - bench_start) / bench_start) * 100} for p in bench_prices],
        }

    weighted_return = 0
    for h in holdings:
        if not (h.get("cost_basis_per_share") and h.get("current_price")):
            continue
        position_cost = h["shares"] * h["cost_basis_per_share"]
        position_return = (h["current_price"] - h["cost_basis_per_share"]) / h["cost_basis_per_share"]
        weight = position_cost / total_cost
        weighted_return += weight * position_return

    portfolio_pct = weighted_return * 100

    return {
        "portfolio_pct_change": round(portfolio_pct, 2),
        "benchmark_pct_change": round(benchmark_pct, 2),
        "benchmark_series": [
            {"date": p["date"], "value": round(((p["close"] - bench_start) / bench_start) * 100, 2)}
            for p in bench_prices
        ],
    }


def calc_dividend_income(dividends: list[dict]) -> dict:
    """Summarize dividend income: total received, projected annual."""
    paid = [d for d in dividends if d.get("paid")]
    pending = [d for d in dividends if not d.get("paid")]

    total_received = sum(d["amount_per_share"] * d["shares_held"] for d in paid)
    projected_pending = sum(d["amount_per_share"] * d["shares_held"] for d in pending)

    return {
        "total_received": round(total_received, 2),
        "projected_pending": round(projected_pending, 2),
    }
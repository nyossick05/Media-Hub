import csv
import io
from dataclasses import dataclass


@dataclass
class ParsedHolding:
    ticker: str
    shares: float
    cost_basis_per_share: float | None


def parse_fidelity_positions(file_content: str) -> list[ParsedHolding]:
    """
    Parse a Fidelity positions CSV export into a list of holdings.

    Fidelity's CSV has a header section before the actual data rows.
    We scan until we find the real column header row, then parse from there.

    Expected columns (Fidelity format):
      Account Name, Account Number, Symbol, Description, Quantity,
      Last Price, Last Price Change, Current Value, Today's Gain/Loss Dollar,
      Today's Gain/Loss Percent, Total Gain/Loss Dollar, Total Gain/Loss Percent,
      Cost Basis Per Share, Cost Basis Total, Type
    """
    holdings = []
    lines = file_content.splitlines()

    # Find the header row (contains "Symbol" or "Ticker")
    header_idx = None
    for i, line in enumerate(lines):
        if "Symbol" in line or "Ticker" in line:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find column headers in CSV. Make sure this is a Fidelity positions export.")

    reader = csv.DictReader(lines[header_idx:])

    for row in reader:
        ticker = (row.get("Symbol") or row.get("Ticker") or "").strip()

        # Skip empty rows, cash, money market, headers
        if not ticker or ticker in ("--", "Pending Activity") or ticker.startswith("**"):
            continue
        if any(x in ticker.upper() for x in ["SPAXX", "FDRXX", "FZFXX", "FMPXX"]):
            # Skip Fidelity money market funds
            continue

        try:
            shares_raw = row.get("Quantity", "").replace(",", "").strip()
            shares = float(shares_raw) if shares_raw and shares_raw != "--" else None
        except ValueError:
            shares = None

        try:
            cb_raw = row.get("Cost Basis Per Share", "").replace(",", "").replace("$", "").strip()
            cost_basis = float(cb_raw) if cb_raw and cb_raw != "--" else None
        except ValueError:
            cost_basis = None

        if ticker and shares and shares > 0:
            holdings.append(ParsedHolding(
                ticker=ticker,
                shares=shares,
                cost_basis_per_share=cost_basis,
            ))

    if not holdings:
        raise ValueError("No holdings found. Make sure this is a Fidelity positions CSV export.")

    return holdings
from flask import Blueprint, request, jsonify, session
import os
from supabase import create_client
from services.csv_parser import parse_fidelity_positions
from routes.portfolio import get_or_create_portfolio

holdings_bp = Blueprint("holdings", __name__)


def get_supabase():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


@holdings_bp.route("/import", methods=["POST"])
def import_csv():
    """
    POST /holdings/import
    Accepts a Fidelity positions CSV file upload.
    Replaces all existing holdings for the portfolio.
    """
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    content = file.read().decode("utf-8", errors="replace")

    try:
        parsed = parse_fidelity_positions(content)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    sb = get_supabase()
    portfolio = get_or_create_portfolio(sb, user_id)
    portfolio_id = portfolio["id"]

    # Replace all holdings
    sb.table("holdings").delete().eq("portfolio_id", portfolio_id).execute()

    rows = [
        {
            "portfolio_id": portfolio_id,
            "ticker": h.ticker,
            "shares": h.shares,
            "cost_basis_per_share": h.cost_basis_per_share,
        }
        for h in parsed
    ]
    sb.table("holdings").insert(rows).execute()

    return jsonify({"imported": len(rows), "tickers": [h.ticker for h in parsed]})


@holdings_bp.route("/", methods=["GET"])
def list_holdings():
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))
    sb = get_supabase()
    portfolio = get_or_create_portfolio(sb, user_id)
    data = sb.table("holdings").select("*").eq("portfolio_id", portfolio["id"]).execute().data
    return jsonify(data)


@holdings_bp.route("/", methods=["POST"])
def add_holding():
    """Manually add a single holding."""
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))
    body = request.get_json()
    sb = get_supabase()
    portfolio = get_or_create_portfolio(sb, user_id)
    row = {
        "portfolio_id": portfolio["id"],
        "ticker": body["ticker"].upper(),
        "shares": float(body["shares"]),
        "cost_basis_per_share": float(body["cost_basis_per_share"]) if body.get("cost_basis_per_share") else None,
    }
    result = sb.table("holdings").insert(row).execute()
    return jsonify(result.data[0]), 201


@holdings_bp.route("/<holding_id>", methods=["DELETE"])
def delete_holding(holding_id):
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))
    sb = get_supabase()
    sb.table("holdings").delete().eq("id", holding_id).execute()
    return jsonify({"deleted": holding_id})
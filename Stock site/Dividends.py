from flask import Blueprint, request, jsonify, session
import os
from supabase import create_client
from routes.portfolio import get_or_create_portfolio
from services.market_data import get_dividends as fetch_polygon_dividends

dividends_bp = Blueprint("dividends", __name__)


def get_supabase():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


@dividends_bp.route("/", methods=["GET"])
def list_dividends():
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))
    sb = get_supabase()
    portfolio = get_or_create_portfolio(sb, user_id)
    data = sb.table("dividends").select("*").eq("portfolio_id", portfolio["id"]).order("ex_date", desc=True).execute().data
    return jsonify(data)


@dividends_bp.route("/", methods=["POST"])
def add_dividend():
    """Manually log a dividend."""
    user_id = session.get("user_id", os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"))
    body = request.get_json()
    sb = get_supabase()
    portfolio = get_or_create_portfolio(sb, user_id)
    row = {
        "portfolio_id": portfolio["id"],
        "ticker": body["ticker"].upper(),
        "amount_per_share": float(body["amount_per_share"]),
        "shares_held": float(body["shares_held"]),
        "ex_date": body["ex_date"],
        "pay_date": body.get("pay_date"),
        "paid": body.get("paid", False),
    }
    result = sb.table("dividends").insert(row).execute()
    return jsonify(result.data[0]), 201


@dividends_bp.route("/<div_id>/mark-paid", methods=["PATCH"])
def mark_paid(div_id):
    sb = get_supabase()
    result = sb.table("dividends").update({"paid": True}).eq("id", div_id).execute()
    return jsonify(result.data[0])


@dividends_bp.route("/<div_id>", methods=["DELETE"])
def delete_dividend(div_id):
    sb = get_supabase()
    sb.table("dividends").delete().eq("id", div_id).execute()
    return jsonify({"deleted": div_id})


@dividends_bp.route("/fetch/<ticker>", methods=["GET"])
def fetch_from_polygon(ticker):
    """Fetch recent dividend history from Polygon for a ticker."""
    data = fetch_polygon_dividends(ticker.upper())
    return jsonify(data)
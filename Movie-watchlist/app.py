from flask import Flask, render_template, request, jsonify
import sqlite3
import os
import requests
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "watchlist.db")
load_dotenv()


app = Flask(__name__)
API_KEY = os.getenv("TMDB_API_KEY")

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None

def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    else:
        conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
    if USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    if USE_POSTGRES:
        c.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id SERIAL PRIMARY KEY,
                tmdb_id INTEGER,
                title TEXT,
                poster_path TEXT,
                status TEXT DEFAULT 'plan_to_watch',
                rating INTEGER,
                review TEXT,
                media_type TEXT DEFAULT 'movie'
            )
        ''')
    else:
        c.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY,
                tmdb_id INTEGER,
                title TEXT,
                poster_path TEXT,
                status TEXT DEFAULT 'plan_to_watch',
                rating INTEGER,
                review TEXT,
                media_type TEXT DEFAULT 'movie'
            )
        ''')
    conn.commit()
    conn.close()

@app.route("/search")
def search():
    query = request.args.get("q")
    media_type = request.args.get("type", "movie")

    if media_type == "anime":
        response = requests.get(
            "https://api.jikan.moe/v4/anime",
            params={"q": query, "limit": 20}
        )
        results = response.json().get("data", [])
        media = [
            {
                "tmdb_id": m["mal_id"],
                "title": m["title"],
                "poster": m["images"]["jpg"]["image_url"] if m.get("images") else None,
                "year": str(m.get("year") or ""),
                "media_type": "anime"
            }
            for m in results
        ]
    else:
        endpoint = "movie" if media_type == "movie" else "tv"
        response = requests.get(
            f"https://api.themoviedb.org/3/search/{endpoint}",
            params={"api_key": API_KEY, "query": query}
        )
        results = response.json().get("results", [])
        media = [
            {
                "tmdb_id": m["id"],
                "title": m.get("title") or m.get("name"),
                "poster": f"https://image.tmdb.org/t/p/w200{m['poster_path']}" if m.get("poster_path") else None,
                "year": (m.get("release_date") or m.get("first_air_date") or "")[:4],
                "media_type": media_type
            }
            for m in results[:20]
        ]
    return jsonify(media)
    
@app.route("/add", methods=["POST"])
def add_movie():
    data = request.get_json()
    conn = get_db()
    if USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    try:
        if USE_POSTGRES:
            c.execute('''
                INSERT INTO movies (tmdb_id, title, poster_path, status, media_type)
                VALUES (%s, %s, %s, 'plan_to_watch', %s)
            ''', (data["tmdb_id"], data["title"], data["poster"], data["media_type"]))
        else:
            c.execute('''
                INSERT INTO movies (tmdb_id, title, poster_path, status, media_type)
                VALUES (?, ?, ?, 'plan_to_watch', ?)
            ''', (data["tmdb_id"], data["title"], data["poster"], data["media_type"]))
        conn.commit()
        result = {"success": True, "message": f"{data['title']} added!"}
    except Exception as e:
        conn.rollback()
        result = {"success": False, "message": "Already in your watchlist!"}
    conn.close()
    return jsonify(result)

@app.route("/watchlist")
def watchlist():
    conn = get_db()
    if USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    c.execute("SELECT * FROM movies")
    rows = c.fetchall()
    conn.close()
    print(f"DEBUG: Found {len(rows)} rows")
    if rows:
        print(f"DEBUG: First row: {rows[0]}")
    movies = [
        {
            "id": r["id"],
            "tmdb_id": r["tmdb_id"],
            "title": r["title"],
            "poster": r["poster_path"],
            "status": r["status"],
            "rating": r["rating"],
            "review": r["review"],
            "media_type": r["media_type"]
        }
        for r in rows
    ]
    return jsonify(movies)

@app.route("/watchlist-page")
def watchlist_page():
    return render_template("watchlist.html")

@app.route("/update", methods=["POST"])
def update_movie():
    data = request.get_json()
    conn = get_db()
    if USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            UPDATE movies
            SET status = %s, rating = %s, review = %s
            WHERE id = %s
        ''', (data["status"], data["rating"], data["review"], data["id"]))
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            UPDATE movies
            SET status = ?, rating = ?, review = ?
            WHERE id = ?
        ''', (data["status"], data["rating"], data["review"], data["id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Updated!"})

@app.route("/delete", methods=["POST"])
def delete_movie():
    data = request.get_json()
    conn = get_db()
    if USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("DELETE FROM movies WHERE id = %s", (data["id"],))
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("DELETE FROM movies WHERE id = ?", (data["id"],))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Removed from watchlist!"})

@app.route("/details")
def details():
    tmdb_id = request.args.get("id")
    media_type = request.args.get("type")
    return render_template("details.html", tmdb_id=tmdb_id, media_type=media_type)

@app.route("/api/details/<media_type>/<int:tmdb_id>")
def api_details(media_type, tmdb_id):
    if media_type == "anime":
        response = requests.get(f"https://api.jikan.moe/v4/anime/{tmdb_id}/full")
        data = response.json().get("data", {})
        return jsonify({
            "title": data.get("title"),
            "poster": data.get("images", {}).get("jpg", {}).get("large_image_url"),
            "backdrop": None,
            "overview": data.get("synopsis"),
            "genres": [g["name"] for g in data.get("genres", [])],
            "rating": data.get("score"),
            "runtime": None,
            "episodes": data.get("episodes"),
            "status": data.get("status"),
            "year": str(data.get("year") or ""),
            "media_type": "anime"
        })
    else:
        endpoint = "movie" if media_type == "movie" else "tv"
        response = requests.get(
            f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}",
            params={"api_key": API_KEY}
        )
        data = response.json()
        return jsonify({
            "title": data.get("title") or data.get("name"),
            "poster": f"https://image.tmdb.org/t/p/w400{data['poster_path']}" if data.get("poster_path") else None,
            "backdrop": f"https://image.tmdb.org/t/p/w1280{data['backdrop_path']}" if data.get("backdrop_path") else None,
            "overview": data.get("overview"),
            "genres": [g["name"] for g in data.get("genres", [])],
            "rating": round(data.get("vote_average", 0), 1),
            "runtime": data.get("runtime"),
            "episodes": data.get("number_of_episodes"),
            "status": data.get("status"),
            "year": (data.get("release_date") or data.get("first_air_date") or "")[:4],
            "media_type": media_type
        })
@app.route("/stats")
def stats():
    return render_template("stats.html")

@app.route("/api/stats")
def api_stats():
    conn = get_db()
    if USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    c.execute("SELECT * FROM movies")
    rows = c.fetchall()
    conn.close()

    movies = [
    {
        "tmdb_id": r["tmdb_id"],
        "media_type": r["media_type"],
        "rating": r["rating"]
    }
    for r in rows
]

    total = len(movies)
    status_counts = {}
    for m in movies:
        status_counts[m["status"]] = status_counts.get(m["status"], 0) + 1

    type_counts = {"movie": 0, "tv": 0, "anime": 0}
    for m in movies:
        if m["media_type"] in type_counts:
            type_counts[m["media_type"]] += 1

    ratings = [m["rating"] for m in movies if m["rating"]]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    # fetch genres for rated items
    genre_counts = {}
    for m in movies:
        if m["media_type"] == "anime":
            try:
                r = requests.get(f"https://api.jikan.moe/v4/anime/{m['tmdb_id']}")
                genres = [g["name"] for g in r.json().get("data", {}).get("genres", [])]
            except:
                genres = []
        else:
            endpoint = "movie" if m["media_type"] == "movie" else "tv"
            try:
                r = requests.get(
                    f"https://api.themoviedb.org/3/{endpoint}/{m['tmdb_id']}",
                    params={"api_key": API_KEY}
                )
                genres = [g["name"] for g in r.json().get("genres", [])]
            except:
                genres = []
        for g in genres:
            genre_counts[g] = genre_counts.get(g, 0) + 1

    top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    return jsonify({
        "total": total,
        "status_counts": status_counts,
        "type_counts": type_counts,
        "avg_rating": avg_rating,
        "top_genres": top_genres
    })
@app.route("/")
def home():
    return render_template("home.html", api_key=API_KEY)

@app.route("/discover")
def search_page():
    return render_template("index.html")
@app.route("/api/trending/<media_type>")
def trending(media_type):
    if media_type == "anime":
        response = requests.get(
            "https://api.jikan.moe/v4/top/anime",
            params={"limit": 20}
        )
        results = response.json().get("data", [])
        media = [
            {
                "tmdb_id": m["mal_id"],
                "title": m["title"],
                "poster": m["images"]["jpg"]["image_url"] if m.get("images") else None,
                "year": str(m.get("year") or ""),
                "rating": m.get("score"),
                "media_type": "anime"
            }
            for m in results
        ]
    else:
        endpoint = "movie" if media_type == "movie" else "tv"
        response = requests.get(
            f"https://api.themoviedb.org/3/trending/{endpoint}/week",
            params={"api_key": API_KEY}
        )
        results = response.json().get("results", [])
        media = [
            {
                "tmdb_id": m["id"],
                "title": m.get("title") or m.get("name"),
                "poster": f"https://image.tmdb.org/t/p/w300{m['poster_path']}" if m.get("poster_path") else None,
                "year": (m.get("release_date") or m.get("first_air_date") or "")[:4],
                "rating": round(m.get("vote_average", 0), 1),
                "media_type": media_type
            }
            for m in results[:20]
        ]
    return jsonify(media)
@app.route("/api/recommendations")
def recommendations():
    conn = get_db()
    if USE_POSTGRES:
        from psycopg2.extras import RealDictCursor
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    c.execute("SELECT tmdb_id, media_type, rating FROM movies ORDER BY rating DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    if not rows:
        return jsonify([])

    watched_ids = set(str(r[0]) for r in rows)
    results = []
    seen_ids = set()

    for tmdb_id, media_type, rating in rows:
        if media_type == "anime":
            try:
                r = requests.get(f"https://api.jikan.moe/v4/anime/{tmdb_id}/recommendations")
                items = r.json().get("data", [])[:5]
                for item in items:
                    entry = item.get("entry", {})
                    mid = str(entry.get("mal_id"))
                    if mid in watched_ids or mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    results.append({
                        "tmdb_id": entry.get("mal_id"),
                        "title": entry.get("title"),
                        "poster": entry.get("images", {}).get("jpg", {}).get("image_url"),
                        "media_type": "anime",
                        "year": "",
                        "rating": None
                    })
            except:
                pass
        else:
            endpoint = "movie" if media_type == "movie" else "tv"
            try:
                r = requests.get(
                    f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}/recommendations",
                    params={"api_key": API_KEY}
                )
                items = r.json().get("results", [])[:5]
                for item in items:
                    mid = str(item.get("id"))
                    if mid in watched_ids or mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    results.append({
                        "tmdb_id": item.get("id"),
                        "title": item.get("title") or item.get("name"),
                        "poster": f"https://image.tmdb.org/t/p/w300{item['poster_path']}" if item.get("poster_path") else None,
                        "year": (item.get("release_date") or item.get("first_air_date") or "")[:4],
                        "rating": round(item.get("vote_average", 0), 1),
                        "media_type": media_type
                    })
            except:
                pass

    return jsonify(results[:40])
    
    

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
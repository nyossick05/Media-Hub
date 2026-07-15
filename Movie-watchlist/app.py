from flask import Flask, render_template, request, jsonify
import sqlite3
import os
import random
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

ANILIST_URL = "https://graphql.anilist.co"

def anilist_query(query, variables=None):
    try:
        resp = requests.post(ANILIST_URL, json={"query": query, "variables": variables or {}}, timeout=10)
        return resp.json().get("data", {})
    except:
        return {}

def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    else:
        conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
    if USE_POSTGRES:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id SERIAL PRIMARY KEY,
                tmdb_id INTEGER,
                title TEXT,
                poster_path TEXT,
                status TEXT DEFAULT 'plan_to_watch',
                rating INTEGER,
                review TEXT,
                media_type TEXT DEFAULT 'movie',
                genres TEXT
            )
        ''')
        c.execute('ALTER TABLE movies ADD COLUMN IF NOT EXISTS genres TEXT')
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY,
                tmdb_id INTEGER,
                title TEXT,
                poster_path TEXT,
                status TEXT DEFAULT 'plan_to_watch',
                rating INTEGER,
                review TEXT,
                media_type TEXT DEFAULT 'movie',
                genres TEXT
            )
        ''')
    conn.commit()
    conn.close()

def fetch_genres(tmdb_id, media_type):
    try:
        if media_type == "anime":
            query = """
            query ($id: Int) {
                Media(id: $id, type: ANIME) {
                    genres
                }
            }
            """
            data = anilist_query(query, {"id": tmdb_id})
            return ",".join(data.get("Media", {}).get("genres", []))
        else:
            endpoint = "movie" if media_type == "movie" else "tv"
            r = requests.get(
                f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}",
                params={"api_key": API_KEY},
                timeout=5
            )
            genres = [g["name"] for g in r.json().get("genres", [])]
            return ",".join(genres)
    except:
        return ""

@app.route("/search")
def search():
    query = request.args.get("q")
    media_type = request.args.get("type", "movie")

    if media_type == "anime":
        gql = """
        query ($search: String) {
            Page(perPage: 20) {
                media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
                    id
                    title { romaji english }
                    coverImage { medium }
                    startDate { year }
                    averageScore
                }
            }
        }
        """
        data = anilist_query(gql, {"search": query})
        results = data.get("Page", {}).get("media", [])
        media = [
            {
                "tmdb_id": m["id"],
                "title": m["title"].get("english") or m["title"].get("romaji"),
                "poster": m.get("coverImage", {}).get("medium"),
                "year": str(m.get("startDate", {}).get("year") or ""),
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
    genres = fetch_genres(data["tmdb_id"], data["media_type"])

    conn = get_db()
    if USE_POSTGRES:
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    try:
        if USE_POSTGRES:
            c.execute('''
                INSERT INTO movies (tmdb_id, title, poster_path, status, media_type, genres)
                VALUES (%s, %s, %s, 'plan_to_watch', %s, %s)
            ''', (data["tmdb_id"], data["title"], data["poster"], data["media_type"], genres))
        else:
            c.execute('''
                INSERT INTO movies (tmdb_id, title, poster_path, status, media_type, genres)
                VALUES (?, ?, ?, 'plan_to_watch', ?, ?)
            ''', (data["tmdb_id"], data["title"], data["poster"], data["media_type"], genres))
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
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    c.execute("SELECT * FROM movies")
    rows = c.fetchall()
    conn.close()
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
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            UPDATE movies SET status = %s, rating = %s, review = %s WHERE id = %s
        ''', (data["status"], data["rating"], data["review"], data["id"]))
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            UPDATE movies SET status = ?, rating = ?, review = ? WHERE id = ?
        ''', (data["status"], data["rating"], data["review"], data["id"]))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Updated!"})

@app.route("/delete", methods=["POST"])
def delete_movie():
    data = request.get_json()
    conn = get_db()
    if USE_POSTGRES:
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
        gql = """
        query ($id: Int) {
            Media(id: $id, type: ANIME) {
                title { romaji english }
                coverImage { large }
                bannerImage
                description(asHtml: false)
                genres
                averageScore
                episodes
                status
                startDate { year }
            }
        }
        """
        data = anilist_query(gql, {"id": tmdb_id}).get("Media", {})
        return jsonify({
            "title": data.get("title", {}).get("english") or data.get("title", {}).get("romaji"),
            "poster": data.get("coverImage", {}).get("large"),
            "backdrop": data.get("bannerImage"),
            "overview": data.get("description"),
            "genres": data.get("genres", []),
            "rating": round(data["averageScore"] / 10, 1) if data.get("averageScore") else None,
            "runtime": None,
            "episodes": data.get("episodes"),
            "status": data.get("status"),
            "year": str(data.get("startDate", {}).get("year") or ""),
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
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    c.execute("SELECT media_type, rating, status, genres FROM movies")
    rows = c.fetchall()
    conn.close()

    total = len(rows)
    status_counts = {}
    type_counts = {"movie": 0, "tv": 0, "anime": 0}
    ratings = []
    genre_counts = {}

    for r in rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        if r["media_type"] in type_counts:
            type_counts[r["media_type"]] += 1
        if r["rating"]:
            ratings.append(r["rating"])
        if r["genres"]:
            for g in r["genres"].split(","):
                g = g.strip()
                if g:
                    genre_counts[g] = genre_counts.get(g, 0) + 1

    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
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
        gql = """
        query {
            Page(perPage: 20) {
                media(type: ANIME, sort: TRENDING_DESC) {
                    id
                    title { romaji english }
                    coverImage { medium }
                    startDate { year }
                    averageScore
                }
            }
        }
        """
        data = anilist_query(gql)
        results = data.get("Page", {}).get("media", [])
        media = [
            {
                "tmdb_id": m["id"],
                "title": m["title"].get("english") or m["title"].get("romaji"),
                "poster": m.get("coverImage", {}).get("medium"),
                "year": str(m.get("startDate", {}).get("year") or ""),
                "rating": round(m["averageScore"] / 10, 1) if m.get("averageScore") else None,
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
        c = conn.cursor(cursor_factory=RealDictCursor)
    else:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

    c.execute("SELECT tmdb_id FROM movies")
    all_rows = c.fetchall()
    watched_ids = set(str(r["tmdb_id"]) for r in all_rows)

    c.execute("SELECT tmdb_id, media_type, rating FROM movies WHERE rating IS NOT NULL ORDER BY rating DESC")
    rows = c.fetchall()
    conn.close()

    if not rows:
        return jsonify([])

    weighted_seeds = []
    for r in rows:
        weight = r["rating"] if r["rating"] else 1
        weighted_seeds.extend([r] * weight)
    random.shuffle(weighted_seeds)

    seen_seeds = set()
    seeds = []
    for r in weighted_seeds:
        if r["tmdb_id"] not in seen_seeds:
            seen_seeds.add(r["tmdb_id"])
            seeds.append(r)

    results = []
    seen_ids = set()

    for r in seeds:
        tmdb_id = r["tmdb_id"]
        media_type = r["media_type"]

        if media_type == "anime":
            gql = """
            query ($id: Int) {
                Media(id: $id, type: ANIME) {
                    recommendations(perPage: 8) {
                        nodes {
                            mediaRecommendation {
                                id
                                title { romaji english }
                                coverImage { medium }
                                startDate { year }
                                averageScore
                            }
                        }
                    }
                }
            }
            """
            try:
                data = anilist_query(gql, {"id": tmdb_id})
                nodes = data.get("Media", {}).get("recommendations", {}).get("nodes", [])
                random.shuffle(nodes)
                for node in nodes:
                    m = node.get("mediaRecommendation")
                    if not m:
                        continue
                    mid = str(m["id"])
                    if mid in watched_ids or mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    results.append({
                        "tmdb_id": m["id"],
                        "title": m["title"].get("english") or m["title"].get("romaji"),
                        "poster": m.get("coverImage", {}).get("medium"),
                        "year": str(m.get("startDate", {}).get("year") or ""),
                        "rating": round(m["averageScore"] / 10, 1) if m.get("averageScore") else None,
                        "media_type": "anime"
                    })
            except:
                pass
        else:
            endpoint = "movie" if media_type == "movie" else "tv"
            for api_path in ["recommendations", "similar"]:
                try:
                    resp = requests.get(
                        f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}/{api_path}",
                        params={"api_key": API_KEY},
                        timeout=5
                    )
                    items = resp.json().get("results", [])
                    random.shuffle(items)
                    for item in items[:6]:
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

        if len(results) >= 80:
            break

    random.shuffle(results)
    return jsonify(results[:40])

with app.app_context():
    init_db()

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
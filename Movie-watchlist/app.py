from flask import Flask, render_template, request, jsonify
import sqlite3
import os
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
API_KEY = os.getenv("TMDB_API_KEY")

def init_db():
    conn = sqlite3.connect("watchlist.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY,
            tmdb_id INTEGER,
            title TEXT,
            poster_path TEXT,
            status TEXT DEFAULT 'want_to_watch',
            rating INTEGER,
            review TEXT,
            media_type TEXT DEFAULT 'movie'
        )
    ''')
    conn.commit()
    conn.close()

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/search")
def search():
    query = request.args.get("q")
    media_type = request.args.get("type", "movie")
    
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
        for m in results[:8]
    ]
    return jsonify(media)
    
@app.route("/add", methods=["POST"])
def add_movie():
    data = request.get_json()
    conn = sqlite3.connect("watchlist.db")
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO movies (tmdb_id, title, poster_path, status, media_type)
            VALUES (?, ?, ?, 'want_to_watch', ?)
        ''', (data["tmdb_id"], data["title"], data["poster"], data["media_type"]))
        conn.commit()
        result = {"success": True, "message": f"{data['title']} added to watchlist!"}
    except sqlite3.IntegrityError:
        result = {"success": False, "message": "Already in your watchlist!"}
    conn.close()
    return jsonify(result)

@app.route("/watchlist")
def watchlist():
    conn = sqlite3.connect("watchlist.db")
    c = conn.cursor()
    c.execute("SELECT * FROM movies")
    rows = c.fetchall()
    conn.close()
    movies = [
        {
            "id": r[0],
            "tmdb_id": r[1],
            "title": r[2],
            "poster": r[3],
            "status": r[4],
            "rating": r[5],
            "review": r[6]
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
    conn = sqlite3.connect("watchlist.db")
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
    conn = sqlite3.connect("watchlist.db")
    c = conn.cursor()
    c.execute("DELETE FROM movies WHERE id = ?", (data["id"],))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Removed from watchlist!"})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
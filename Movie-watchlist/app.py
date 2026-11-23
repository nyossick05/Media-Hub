"""Media Hub: track movies, TV shows and anime.

Layout of this file:
  1. config + HTTP helpers (shared session, TTL cache, parallel fetching)
  2. database layer (connection pool, migrations, unique constraint)
  3. TMDB / AniList fetchers that return one common item shape
  4. page routes
  5. JSON API routes
"""
import os
import re
import random
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import requests
from requests.adapters import HTTPAdapter
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(BASE_DIR, "watchlist.db"))
TMDB_KEY = os.getenv("TMDB_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

app = Flask(__name__)

try:  # optional: gzip/brotli responses. Works without it, just a bit slower.
    from flask_compress import Compress
    Compress(app)
except ImportError:
    pass

MEDIA_TYPES = ("movie", "tv", "anime")
STATUSES = ("plan_to_watch", "watching", "completed", "dropped")


# ---------------------------------------------------------------------------
# 1. HTTP helpers
# ---------------------------------------------------------------------------

# One shared session keeps TCP/TLS connections open between requests, which is
# a big part of why the old version felt slow (a fresh handshake every call).
http = requests.Session()
http.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=24))

# Worker threads for running several API calls at the same time.
executor = ThreadPoolExecutor(max_workers=16)

_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn):
    """Return fn() but remember it for `ttl` seconds.

    fn returning None means "the upstream call failed", and failures are never
    cached so the next request retries.
    """
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = fn()
    if value is not None:
        with _cache_lock:
            if len(_cache) > 1500:  # crude size cap, plenty for a personal app
                _cache.clear()
            _cache[key] = (now + ttl, value)
    return value


def tmdb(path, **params):
    if not TMDB_KEY:
        app.logger.error("TMDB_API_KEY is not set")
        return None
    try:
        r = http.get(
            f"https://api.themoviedb.org/3/{path}",
            params={"api_key": TMDB_KEY, **params},
            timeout=6,
        )
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def anilist(query, variables=None):
    try:
        r = http.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": variables or {}},
            timeout=8,
        )
        body = r.json()
        if r.status_code != 200 or body.get("errors"):
            return None
        return body.get("data") or {}
    except (requests.RequestException, ValueError):
        return None


# ---------------------------------------------------------------------------
# 2. Database
# ---------------------------------------------------------------------------

DB_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError) if USE_PG else ()
_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                1, 8, DATABASE_URL, sslmode="require",
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
            )
        return _pool


@contextmanager
def db():
    """Yield a connection; commit on success, roll back on error."""
    if USE_PG:
        pool = _get_pool()
        conn = pool.getconn()
        discard = False
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            discard = isinstance(exc, DB_ERRORS)
            try:
                conn.rollback()
            except Exception:
                discard = True
            raise
        finally:
            pool.putconn(conn, close=discard or bool(conn.closed))
    else:
        conn = sqlite3.connect(SQLITE_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def run(sql, params=(), fetch=None):
    """Run one statement. Write SQL with ? placeholders; they become %s on Postgres.

    fetch: None -> returns rowcount, "one" -> dict or None, "all" -> list of dicts.
    A dropped pooled connection (Supabase closes idle ones) is retried once.
    """
    if USE_PG:
        sql = sql.replace("?", "%s")
    for attempt in (1, 2):
        try:
            with db() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_PG else conn.cursor()
                cur.execute(sql, params)
                if fetch == "all":
                    return [dict(r) for r in cur.fetchall()]
                if fetch == "one":
                    row = cur.fetchone()
                    return dict(row) if row else None
                return cur.rowcount
        except DB_ERRORS:
            if attempt == 2:
                raise


def hq_poster(url):
    """Upgrade poster URLs saved by older versions to sharper sizes.

    AniList "medium" covers are ~100px wide, and the old code saved those into
    the database, which is why anime looked blurry even on the watchlist page.
    """
    if not url or url == "None":
        return None
    url = re.sub(r"/cover/(?:small|medium)/", "/cover/large/", url)
    url = re.sub(r"(image\.tmdb\.org/t/p/)w\d+/", r"\1w342/", url)
    return url


def init_db():
    id_col = "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY"
    run(f"""
        CREATE TABLE IF NOT EXISTS movies (
            id {id_col},
            tmdb_id INTEGER,
            title TEXT,
            poster_path TEXT,
            status TEXT DEFAULT 'plan_to_watch',
            rating INTEGER,
            review TEXT,
            media_type TEXT DEFAULT 'movie',
            genres TEXT
        )
    """)
    if USE_PG:
        run("ALTER TABLE movies ADD COLUMN IF NOT EXISTS genres TEXT")

    # Old versions stored "watched" for movies and "completed" for everything else.
    run("UPDATE movies SET status = 'completed' WHERE status = 'watched'")

    rows = run("SELECT id, tmdb_id, media_type, status, rating, review, poster_path FROM movies", fetch="all")

    # One-time cleanup of duplicates so the unique index below can be created.
    # Keep the entry with the most user data (rating, review, progress).
    groups = {}
    for r in rows:
        groups.setdefault((r["tmdb_id"], r["media_type"]), []).append(r)
    for (tmdb_id, _), items in groups.items():
        if tmdb_id is None or len(items) < 2:
            continue
        items.sort(key=lambda r: (
            -((r["rating"] is not None) + bool(r["review"]) + (r["status"] != "plan_to_watch")), r["id"]))
        for extra in items[1:]:
            run("DELETE FROM movies WHERE id = ?", (extra["id"],))

    # Rewrite blurry stored poster URLs once.
    for r in rows:
        better = hq_poster(r["poster_path"])
        if better != r["poster_path"]:
            run("UPDATE movies SET poster_path = ? WHERE id = ?", (better, r["id"]))

    # TMDB and AniList ids overlap, so uniqueness is on the pair, not the id alone.
    run("CREATE UNIQUE INDEX IF NOT EXISTS movies_ext_unique ON movies (tmdb_id, media_type)")


def row_to_item(r):
    return {
        "id": r["id"],
        "tmdb_id": r["tmdb_id"],
        "title": r["title"],
        "poster": hq_poster(r["poster_path"]),
        "status": r["status"],
        "rating": r["rating"],
        "review": r["review"] or "",
        "media_type": r["media_type"],
    }


def get_row(media_type, ext_id):
    return run("SELECT * FROM movies WHERE media_type = ? AND tmdb_id = ?", (media_type, ext_id), fetch="one")


# ---------------------------------------------------------------------------
# 3. TMDB / AniList -> one common item shape
#    {tmdb_id, title, poster, year, rating, media_type}
# ---------------------------------------------------------------------------

def tmdb_img(path, size):
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else None


def tmdb_item(m, kind):
    return {
        "tmdb_id": m["id"],
        "title": m.get("title") or m.get("name") or "Untitled",
        "poster": tmdb_img(m.get("poster_path"), "w342"),
        "year": (m.get("release_date") or m.get("first_air_date") or "")[:4],
        "rating": round(m["vote_average"], 1) if m.get("vote_average") else None,
        "media_type": kind,
    }


def anime_item(m):
    title = m.get("title") or {}
    cover = m.get("coverImage") or {}
    return {
        "tmdb_id": m["id"],
        "title": title.get("english") or title.get("romaji") or "Untitled",
        "poster": cover.get("large"),  # "large" (~230px). "medium" was the blurry one.
        "year": str((m.get("startDate") or {}).get("year") or ""),
        "rating": round(m["averageScore"] / 10, 1) if m.get("averageScore") else None,
        "media_type": "anime",
    }


ANIME_FIELDS = "id title { romaji english } coverImage { large } startDate { year } averageScore"


def _poster_first(items):
    return sorted(items, key=lambda i: i["poster"] is None)


def search_source(kind, q):
    if kind == "anime":
        data = anilist(
            f"query ($s: String) {{ Page(perPage: 12) {{ media(search: $s, type: ANIME, isAdult: false, "
            f"sort: SEARCH_MATCH) {{ {ANIME_FIELDS} }} }} }}",
            {"s": q},
        )
        if data is None:
            return None
        return _poster_first([anime_item(m) for m in data["Page"]["media"]])
    data = tmdb(f"search/{kind}", query=q, include_adult="false")
    if data is None:
        return None
    return _poster_first([tmdb_item(m, kind) for m in data.get("results", [])[:12]])


def trending_source(kind):
    if kind == "anime":
        data = anilist(
            f"query {{ Page(perPage: 18) {{ media(type: ANIME, isAdult: false, sort: TRENDING_DESC) "
            f"{{ {ANIME_FIELDS} }} }} }}"
        )
        return None if data is None else [anime_item(m) for m in data["Page"]["media"]]
    data = tmdb(f"trending/{kind}/week")
    if data is None:
        return None
    return [tmdb_item(m, kind) for m in data.get("results", [])[:18]]


def recs_source(kind, ext_id):
    if kind == "anime":
        data = anilist(
            f"query ($id: Int) {{ Media(id: $id, type: ANIME) {{ recommendations(perPage: 10, sort: RATING_DESC) "
            f"{{ nodes {{ mediaRecommendation {{ {ANIME_FIELDS} }} }} }} }} }}",
            {"id": ext_id},
        )
        if data is None:
            return None
        nodes = ((data.get("Media") or {}).get("recommendations") or {}).get("nodes") or []
        return [anime_item(n["mediaRecommendation"]) for n in nodes if n.get("mediaRecommendation")]
    data = tmdb(f"{kind}/{ext_id}/recommendations")
    if data is None:
        return None
    return [tmdb_item(m, kind) for m in data.get("results", [])[:10]]


ANIME_STATUS = {
    "FINISHED": "Finished", "RELEASING": "Airing", "NOT_YET_RELEASED": "Upcoming",
    "CANCELLED": "Cancelled", "HIATUS": "On hiatus",
}


def _fetch_details(kind, ext_id):
    if kind == "anime":
        data = anilist(
            """query ($id: Int) { Media(id: $id, type: ANIME) {
                title { romaji english } coverImage { extraLarge large } bannerImage
                description(asHtml: false) genres averageScore episodes duration status startDate { year }
            } }""",
            {"id": ext_id},
        )
        m = (data or {}).get("Media")
        if not m:
            return None
        title = m.get("title") or {}
        cover = m.get("coverImage") or {}
        overview = re.sub(r"<[^>]+>", " ", m.get("description") or "").strip()
        return {
            "tmdb_id": ext_id, "media_type": "anime",
            "title": title.get("english") or title.get("romaji"),
            "poster": cover.get("extraLarge") or cover.get("large"),
            "backdrop": m.get("bannerImage"),
            "overview": overview,
            "genres": m.get("genres") or [],
            "rating": round(m["averageScore"] / 10, 1) if m.get("averageScore") else None,
            "runtime": m.get("duration"), "episodes": m.get("episodes"), "seasons": None,
            "status": ANIME_STATUS.get(m.get("status"), m.get("status")),
            "year": str((m.get("startDate") or {}).get("year") or ""),
        }
    m = tmdb(f"{kind}/{ext_id}")
    if not m:
        return None
    runtime = m.get("runtime") or (m.get("episode_run_time") or [None])[0]
    return {
        "tmdb_id": ext_id, "media_type": kind,
        "title": m.get("title") or m.get("name"),
        "poster": tmdb_img(m.get("poster_path"), "w500"),
        "backdrop": tmdb_img(m.get("backdrop_path"), "w1280"),
        "overview": m.get("overview") or "",
        "genres": [g["name"] for g in m.get("genres", [])],
        "rating": round(m["vote_average"], 1) if m.get("vote_average") else None,
        "runtime": runtime, "episodes": m.get("number_of_episodes"), "seasons": m.get("number_of_seasons"),
        "status": m.get("status"),
        "year": (m.get("release_date") or m.get("first_air_date") or "")[:4],
    }


def get_details(kind, ext_id):
    return cached(("details", kind, ext_id), 3600, lambda: _fetch_details(kind, ext_id))


# --- genres are filled in after an add, so adding never waits on an API call ---

_backfill_lock = threading.Lock()
_backfill_running = False


def _store_genres(row_id, kind, ext_id):
    d = get_details(kind, ext_id)
    if d is not None:
        run("UPDATE movies SET genres = ? WHERE id = ?", (",".join(d["genres"]), row_id))


def backfill_genres():
    """Fill genres for rows that don't have them yet (new adds and old rows)."""
    global _backfill_running
    with _backfill_lock:
        if _backfill_running:
            return
        _backfill_running = True

    def work():
        global _backfill_running
        try:
            rows = run("SELECT id, tmdb_id, media_type FROM movies WHERE genres IS NULL LIMIT 30", fetch="all")
            list(executor.map(lambda r: _store_genres(r["id"], r["media_type"], r["tmdb_id"]), rows))
        except Exception:
            app.logger.exception("genre backfill failed")
        finally:
            _backfill_running = False

    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------------------
# 4. Pages
# ---------------------------------------------------------------------------

@app.context_processor
def helpers():
    def v(filename):
        """Cache-busting version for static files: changes when the file does."""
        try:
            return int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            return 0
    return {"v": v}


@app.route("/")
def discover_page():
    return render_template("discover.html")


@app.route("/watchlist")
def watchlist_page():
    return render_template("watchlist.html")


@app.route("/stats")
def stats_page():
    return render_template("stats.html")


@app.route("/details/<media_type>/<int:ext_id>")
def details_page(media_type, ext_id):
    if media_type not in MEDIA_TYPES:
        return redirect("/")
    return render_template("details.html", media_type=media_type, ext_id=ext_id)


# Old URLs keep working (bookmarks, links from before the redesign).
@app.route("/discover")
def old_discover():
    return redirect("/", code=301)


@app.route("/watchlist-page")
def old_watchlist():
    return redirect("/watchlist", code=301)


@app.route("/details")
def old_details():
    media_type, ext_id = request.args.get("type", ""), request.args.get("id", "")
    if media_type in MEDIA_TYPES and ext_id.isdigit():
        return redirect(f"/details/{media_type}/{ext_id}", code=301)
    return redirect("/")


# ---------------------------------------------------------------------------
# 5. JSON API
# ---------------------------------------------------------------------------

@app.after_request
def cache_headers(resp):
    if request.method == "GET" and request.path.startswith("/api/"):
        personal = request.path.startswith(("/api/watchlist", "/api/stats", "/api/recommendations"))
        resp.headers["Cache-Control"] = "no-store" if personal else "public, max-age=120"
    return resp


def error(message, status=400):
    return jsonify({"error": message}), status


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()[:100]
    if len(q) < 2:
        return jsonify({"movie": [], "tv": [], "anime": [], "failed": []})
    key = q.lower()
    # All three sources are asked at once; total time = the slowest one, not the sum.
    futures = {
        kind: executor.submit(cached, ("search", kind, key), 600, lambda k=kind: search_source(k, q))
        for kind in MEDIA_TYPES
    }
    out, failed = {}, []
    for kind, fut in futures.items():
        result = fut.result()
        if result is None:
            failed.append(kind)
            result = []
        out[kind] = result
    out["failed"] = failed
    return jsonify(out)


@app.route("/api/trending/<media_type>")
def api_trending(media_type):
    if media_type not in MEDIA_TYPES:
        return error("Unknown media type", 404)
    items = cached(("trending", media_type), 1800, lambda: trending_source(media_type))
    if items is None:
        return error("Couldn't load trending titles right now.", 502)
    return jsonify(items)


@app.route("/api/details/<media_type>/<int:ext_id>")
def api_details(media_type, ext_id):
    if media_type not in MEDIA_TYPES:
        return error("Unknown media type", 404)
    data = get_details(media_type, ext_id)
    if data is None:
        return error("Couldn't load this title right now.", 502)
    return jsonify(data)


@app.route("/api/recommendations")
def api_recommendations():
    rows = run("SELECT tmdb_id, media_type, title, rating FROM movies", fetch="all")
    owned = {(r["media_type"], r["tmdb_id"]) for r in rows}
    rated = [r for r in rows if r["rating"]]
    if not rated:
        return jsonify({"items": [], "reason": "no_ratings"})

    # Favour high ratings but add jitter so each refresh draws from different titles.
    seeds = sorted(rated, key=lambda r: -(r["rating"] + random.random() * 3))[:8]

    # One request per seed, all in parallel (the old code did them one by one).
    def fetch(seed):
        return cached(("recs", seed["media_type"], seed["tmdb_id"]), 6 * 3600,
                      lambda: recs_source(seed["media_type"], seed["tmdb_id"]))

    results = list(executor.map(fetch, seeds))

    # Interleave seeds so one favourite doesn't take over the whole page.
    items, seen = [], set()
    for rank in range(10):
        for seed, recs in zip(seeds, results):
            if not recs or rank >= len(recs):
                continue
            rec = recs[rank]
            key = (rec["media_type"], rec["tmdb_id"])
            if key in owned or key in seen:
                continue
            seen.add(key)
            items.append({**rec, "because": seed["title"]})
    return jsonify({"items": items[:36]})


@app.route("/api/watchlist", methods=["GET"])
def api_watchlist():
    rows = run("SELECT * FROM movies ORDER BY id DESC", fetch="all")
    return jsonify([row_to_item(r) for r in rows])


@app.route("/api/watchlist", methods=["POST"])
def api_add():
    data = request.get_json(silent=True) or {}
    try:
        ext_id = int(data.get("tmdb_id"))
    except (TypeError, ValueError):
        return error("Missing title id")
    media_type = data.get("media_type")
    title = (data.get("title") or "").strip()
    if media_type not in MEDIA_TYPES or not title:
        return error("Missing title or type")

    status = data.get("status") if data.get("status") in STATUSES else "plan_to_watch"
    rating = data.get("rating")
    rating = rating if isinstance(rating, int) and 1 <= rating <= 10 else None
    review = (data.get("review") or "")[:4000] or None

    # ON CONFLICT DO NOTHING + the unique index = duplicates are impossible,
    # even if two requests arrive at the same moment.
    inserted = run(
        """INSERT INTO movies (tmdb_id, title, poster_path, status, rating, review, media_type)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (tmdb_id, media_type) DO NOTHING""",
        (ext_id, title, hq_poster(data.get("poster")), status, rating, review, media_type),
    )
    row = get_row(media_type, ext_id)
    if inserted:
        threading.Thread(target=_store_genres, args=(row["id"], media_type, ext_id), daemon=True).start()
    return jsonify({"added": bool(inserted), "item": row_to_item(row)}), (201 if inserted else 200)


@app.route("/api/watchlist/<int:row_id>", methods=["PATCH"])
def api_update(row_id):
    data = request.get_json(silent=True) or {}
    fields, params = [], []
    if "status" in data:
        if data["status"] not in STATUSES:
            return error("Invalid status")
        fields.append("status = ?")
        params.append(data["status"])
    if "rating" in data:
        rating = data["rating"]
        if rating is not None and not (isinstance(rating, int) and 1 <= rating <= 10):
            return error("Rating must be 1 to 10")
        fields.append("rating = ?")
        params.append(rating)
    if "review" in data:
        fields.append("review = ?")
        params.append((data["review"] or "")[:4000] or None)
    if not fields:
        return error("Nothing to update")
    changed = run(f"UPDATE movies SET {', '.join(fields)} WHERE id = ?", (*params, row_id))
    row = run("SELECT * FROM movies WHERE id = ?", (row_id,), fetch="one")
    if row is None:
        return error("Not found", 404)
    return jsonify(row_to_item(row))


@app.route("/api/watchlist/<int:row_id>", methods=["DELETE"])
def api_delete(row_id):
    run("DELETE FROM movies WHERE id = ?", (row_id,))
    return jsonify({"ok": True})


@app.route("/api/stats")
def api_stats():
    rows = run("SELECT media_type, rating, status, genres FROM movies", fetch="all")
    status_counts = {s: 0 for s in STATUSES}
    type_counts = {t: 0 for t in MEDIA_TYPES}
    histogram = {str(n): 0 for n in range(1, 11)}
    genre_counts, ratings, missing_genres = {}, [], False

    for r in rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        if r["media_type"] in type_counts:
            type_counts[r["media_type"]] += 1
        if r["rating"]:
            ratings.append(r["rating"])
            if str(r["rating"]) in histogram:
                histogram[str(r["rating"])] += 1
        if r["genres"] is None:
            missing_genres = True
        for g in (r["genres"] or "").split(","):
            if g.strip():
                genre_counts[g.strip()] = genre_counts.get(g.strip(), 0) + 1

    if missing_genres:
        backfill_genres()

    return jsonify({
        "total": len(rows),
        "status_counts": status_counts,
        "type_counts": type_counts,
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "rated": len(ratings),
        "histogram": histogram,
        "top_genres": sorted(genre_counts.items(), key=lambda kv: -kv[1])[:8],
        "genres_pending": missing_genres,
    })


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return error("Not found", 404)
    return redirect("/")


try:
    init_db()
except Exception:  # keep the app booting so the error is visible in the logs
    app.logger.exception("init_db failed")

if __name__ == "__main__":
    app.run(debug=True)

import csv
import io
import json
import math
import os
import re
import sqlite3
import time
from collections import defaultdict
from functools import lru_cache
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rapidfuzz import fuzz
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth

app = FastAPI()

# Built frontend (Vite → frontend/dist). Run `npm run build` in frontend/ to
# (re)generate it. Falls back to the legacy inline static/index.html if unbuilt.
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
_dist_assets = os.path.join(FRONTEND_DIST, "assets")
if os.path.isdir(_dist_assets):
    app.mount("/assets", StaticFiles(directory=_dist_assets), name="assets")

DB_PATH = os.environ.get("DB_PATH", "book_rec.db")  # on Fly: /data/book_rec.db (volume)
CATALOG_PATH = "bookCatalog.json"
USER_ID = "test_user"        # legacy demo/dev account (existing data)
DEMO_USER = "test_user"

# --- auth / OAuth config (from env) -----------------------------------------
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-secret-change-me")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# Real Google login is enabled only when both credentials are present; otherwise
# the app runs in DEV mode and everyone is the demo account, so it stays usable
# and testable without external setup.
OAUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# Cookie policy. Single-origin dev keeps the defaults (Lax, plain HTTP). For a
# split deploy (frontend on Vercel, backend elsewhere) the session cookie must be
# SameSite=None; Secure to survive cross-site XHR — set COOKIE_SAMESITE=none and
# COOKIE_SECURE=1 in that environment (both require HTTPS).
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET,
                   same_site=COOKIE_SAMESITE, https_only=COOKIE_SECURE)

# When the frontend is served from a different origin, list its URL(s) here
# (comma-separated) so cross-origin credentialed requests are allowed.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if CORS_ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

oauth = OAuth()
if OAUTH_ENABLED:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

# Spec §4: 5★ → +2, 4★ → +1, 3★ → 0, 2★ → -1, 1★ → -2
RATING_WEIGHTS = {5: 2.0, 4: 1.0, 3: 0.0, 2: -1.0, 1: -2.0}
UNRATED_WEIGHT = 0.5          # finished but unrated: mild positive signal
AMBIGUOUS_FACTOR = 0.5        # medium-confidence matches count at half weight
WINDOW_DAYS = {"6m": 183, "1y": 365}

# Non-descriptive shelf/list names that leaked into catalog tags — excluded from
# profile display and reason strings (kept in DB untouched)
JUNK_TAGS = {"all reviews & lists", "books fiction", "kindle unlimited",
             "audiobook", "kindle", "ebook"}
JUNK_SUBSTRINGS = ("favourite", "favorite", "best of", "recommended", "review",
                   "to buy", "tbr", "wish list", "wishlist")
# Mood tags sit on nearly every book, so they carry almost no discriminative
# signal for "why this book" — they're deprioritised (but not removed) when
# choosing the traits shown on a recommendation card.
MOODS = {"dark", "emotional", "tense", "mysterious", "adventurous", "reflective",
         "funny", "sad", "challenging", "relaxing", "inspiring", "hopeful",
         "lighthearted"}


@lru_cache(maxsize=None)
def is_junk_tag(tag):
    t = tag.lower()
    return t in JUNK_TAGS or any(s in t for s in JUNK_SUBSTRINGS)


@lru_cache(maxsize=None)
def humanize(name):
    """Display form: 'enemiesToLovers' -> 'enemies to lovers' (data unchanged)."""
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r" \1", name).lower()


# Synonym merging: SPELLING/PHRASING variants only, applied at aggregation/scoring
# time, DB data unchanged. Never merge conceptually distinct tags (e.g. "guarded
# character" is NOT "ice queen") — these carry precise meanings to readers.
TAG_ALIASES = {
    "slow burn romance": "slow burn",
    "bisexual or pansexual": "bisexual",
    "sapphic romance": "sapphic",
    "mlm romance": "mlm",
    "grumpy / sunshine": "grumpy sunshine",
}


@lru_cache(maxsize=None)
def canonical_tag(tag):
    # normalize hyphens between words only ("slow-burn" -> "slow burn"),
    # keep numeric ranges intact ("25-39 lead")
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", tag.lower()).replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return TAG_ALIASES.get(t, t)


@lru_cache(maxsize=None)
def canonical_spice(raw):
    if not raw:
        return "N/A"
    r = raw.lower()
    if any(k in r for k in ("explicit", "hot", "spicy", "high")):
        return "Explicit"
    if any(k in r for k in ("medium", "average", "moderate")):
        return "Medium Spice"
    if any(k in r for k in ("tame", "euphemistic", "low", "mild", "fade", "closed door")):
        return "Tame"
    if "no spice" in r:
        return "No Spice"
    return "N/A"

# Additive tag derivation — original tropes are NEVER modified (iceQueen stays
# iceQueen), and derived tags must be the SAME concept spelled differently,
# never a renamed synonym (no inventing "guarded-character" from iceQueen)
TROPE_TAG_MAP = {
    "enemiesToLovers": "enemies-to-lovers",
    "fakeDating": "fake-dating",
    "slowBurn": "slow-burn",
    "forcedProximity": "forced-proximity",
    "grumpySunshine": "grumpy-sunshine",
    "competenceKink": "competence-kink",
    "iceQueen": "ice-queen",
    "touchStarved": "touch-starved",
    "foundFamily": "found-family",
    "cinnamonRoll": "cinnamon-roll",
}


def get_db():
    # busy_timeout lets the app wait out a lock held by a concurrent writer
    # (e.g. the overnight enrichment run) instead of failing with "database is
    # locked"; WAL lets reads proceed while that writer holds the lock.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass                                   # locked right now — WAL can wait
    return conn


# ---------------------------------------------------------------------------
# Authentication (Google OAuth). Every data endpoint resolves the current user
# via the `current_user` dependency instead of a hardcoded id.
# ---------------------------------------------------------------------------
def current_user(request: Request) -> str:
    """The signed-in user's id. In DEV mode (no Google creds) everyone is the
    demo account so the app stays usable; in production, no session -> 401."""
    uid = request.session.get("user_id")
    if uid:
        return uid
    if not OAUTH_ENABLED:
        request.session["user_id"] = DEMO_USER
        return DEMO_USER
    raise HTTPException(status_code=401, detail="Not authenticated")


def _find_or_create_oauth_user(conn, provider, sub, email, name, avatar):
    row = conn.execute("SELECT id FROM users WHERE oauth_provider=? AND oauth_sub=?",
                       (provider, sub)).fetchone()
    if row:
        conn.execute("UPDATE users SET display_name=?, email=?, avatar_url=? WHERE id=?",
                     (name, email, avatar, row["id"]))
        conn.commit()
        return row["id"]
    if email:                                  # link a pre-existing account by email
        row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row:
            conn.execute("UPDATE users SET oauth_provider=?, oauth_sub=?, display_name=?, "
                         "avatar_url=? WHERE id=?", (provider, sub, name, avatar, row["id"]))
            conn.commit()
            return row["id"]
    uid = f"{provider}:{sub}"
    conn.execute("INSERT INTO users (id, display_name, email, oauth_provider, oauth_sub, avatar_url) "
                 "VALUES (?,?,?,?,?,?)", (uid, name, email, provider, sub, avatar))
    conn.commit()
    return uid


@app.get("/auth/login")
async def auth_login(request: Request):
    if not OAUTH_ENABLED:                       # dev: log straight in as demo
        request.session["user_id"] = DEMO_USER
        return RedirectResponse("/")
    return await oauth.google.authorize_redirect(request, request.url_for("auth_callback"))


@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse("/?auth=failed")
    info = token.get("userinfo") or {}
    if not info.get("sub"):
        return RedirectResponse("/?auth=failed")
    conn = get_db()
    uid = _find_or_create_oauth_user(
        conn, "google", info["sub"], info.get("email"),
        info.get("name") or info.get("email") or "Reader", info.get("picture"))
    conn.close()
    request.session["user_id"] = uid
    return RedirectResponse("/")


@app.post("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return {"status": "ok"}


@app.get("/api/me")
def api_me(request: Request):
    uid = request.session.get("user_id")
    if not uid and not OAUTH_ENABLED:
        uid = DEMO_USER
        request.session["user_id"] = uid
    if not uid:
        return {"authenticated": False, "oauth_enabled": OAUTH_ENABLED}
    conn = get_db()
    u = conn.execute("SELECT id, display_name, email, avatar_url FROM users WHERE id=?",
                     (uid,)).fetchone()
    conn.close()
    return {"authenticated": True, "oauth_enabled": OAUTH_ENABLED,
            "demo": (uid == DEMO_USER), "user": (dict(u) if u else {"id": uid})}


def normalize_title(title):
    t = (title or "").lower().strip()
    t = re.sub(r"\(.*?\)", " ", t)        # strip series info: "(Feminine Pursuits, #1)"
    t = t.split(":")[0]                    # strip subtitle
    t = t.replace(" a novel", "")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t.startswith("the "):
        t = t[4:]
    return t


def normalize_author(author):
    a = (author or "").lower().strip()
    a = re.sub(r"[^a-z\s]", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def normalize_isbn(s):
    """Clean an ISBN for exact comparison. Goodreads exports them Excel-wrapped
    like `="9780439023481"`, so strip the wrapper, hyphens and spaces. Returns
    "" when there's nothing usable (so blanks never match each other)."""
    s = (s or "").strip()
    if s.startswith('="') and s.endswith('"'):
        s = s[2:-1]
    s = re.sub(r"[^0-9Xx]", "", s).upper()
    return s if len(s) in (10, 13) else ""


def derive_tags(tropes, tags, spice, pacing):
    # spice is its own dimension (spice_level field), never a tag
    extra = [TROPE_TAG_MAP[t] for t in tropes if t in TROPE_TAG_MAP]
    if pacing == "Slow":
        extra.append("slow-paced")
    elif pacing == "Fast":
        extra.append("fast-paced")
    merged = list(tags)
    for tag in extra:
        if tag not in merged and tag not in tropes:
            merged.append(tag)
    return merged


def init_db():
    if Path(DB_PATH).exists() and Path(DB_PATH).stat().st_size > 1000:
        return
    if Path(DB_PATH).exists():
        Path(DB_PATH).unlink()

    conn = get_db()
    with open("schema.sql", encoding="utf-8") as f:
        conn.executescript(f.read())

    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)

    rows = []
    for book in catalog:
        genre = book.get("genre", "")
        genres = genre if isinstance(genre, list) else ([genre] if genre else [])
        tropes = book.get("tropes", [])
        tags = derive_tags(tropes, book.get("tags", []), book.get("spiceLevel"), book.get("pacing"))
        rows.append((
            book.get("id"), book.get("title"), book.get("author"),
            normalize_title(book.get("title")), normalize_author(book.get("author")),
            json.dumps(genres), json.dumps(tropes), json.dumps(tags),
            book.get("pacing"), book.get("spiceLevel"), book.get("focus"),
            json.dumps(book.get("contentWarnings", [])),
        ))

    conn.executemany("""
        INSERT INTO books (id, title, author, norm_title, norm_author, genres, tropes, tags,
                           pacing, spice_level, focus, content_warnings)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.execute("INSERT INTO users (id, display_name) VALUES (?, ?)", (USER_ID, "Test User"))
    conn.commit()
    conn.close()
    print(f"Database initialized with {len(rows)} books")


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def fuzzy_match(title, author, books):
    """Returns (status, book_id). Tiers per spec §2."""
    nt, na = normalize_title(title), normalize_author(author)
    best_id, best_title, best_author, best_combined = None, 0, 0, 0
    for b in books:
        ts = fuzz.token_sort_ratio(nt, b["norm_title"])
        if ts < 50:
            continue
        au = fuzz.token_sort_ratio(na, b["norm_author"])
        combined = ts * 0.7 + au * 0.3
        if combined > best_combined:
            best_id, best_title, best_author, best_combined = b["id"], ts, au, combined
    if best_id and best_title >= 88 and best_author >= 75:
        return "matched", best_id
    if best_id and best_combined >= 65:
        return "ambiguous", best_id
    return "unmatched", None


class UploadResponse(BaseModel):
    total_read: int
    matched: int
    ambiguous: int
    unmatched: int


@app.post("/api/upload-csv")
async def upload_csv(file: UploadFile = File(...),
                     user_id: str = Depends(current_user)) -> UploadResponse:
    init_db()
    conn = get_db()

    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")))

    # Re-upload replaces the previous import instead of stacking duplicates
    conn.execute("DELETE FROM user_books WHERE user_id = ?", (user_id,))

    catalog_books = conn.execute("SELECT id, norm_title, norm_author FROM books").fetchall()

    # ISBN -> book_id lookup for exact matching before the fuzzy fallback. ~82%
    # of the catalog carries an ISBN-13, so this catches most books precisely and
    # avoids fuzzy false positives like "The Many" -> "Mandy".
    isbn_index = {}
    for r in conn.execute("SELECT id, isbn FROM books WHERE isbn IS NOT NULL AND TRIM(isbn) <> ''"):
        key = normalize_isbn(r["isbn"])
        if key:
            isbn_index.setdefault(key, r["id"])

    counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    total_read = 0

    for row in reader:
        shelf = (row.get("Exclusive Shelf") or "").lower().strip()
        if shelf != "read":
            continue
        total_read += 1

        title = row.get("Title", "")
        author = row.get("Author", "")
        try:
            rating = float(row.get("My Rating") or 0) or None
        except ValueError:
            rating = None
        date_read = parse_date(row.get("Date Read")) or parse_date(row.get("Date Added"))

        # Exact ISBN match first (ISBN13 then ISBN10 from the Goodreads row);
        # fall back to fuzzy title/author only when no ISBN hit.
        book_id = None
        for col in ("ISBN13", "ISBN"):
            key = normalize_isbn(row.get(col))
            if key and key in isbn_index:
                book_id = isbn_index[key]
                break
        status = "matched" if book_id else None
        if not book_id:
            status, book_id = fuzzy_match(title, author, catalog_books)
        counts[status] += 1

        if status == "unmatched":
            existing = conn.execute(
                "SELECT id FROM pending_books WHERE raw_title = ? AND raw_author = ? AND user_id = ?",
                (title, author, user_id)).fetchone()
            if existing:
                conn.execute("UPDATE pending_books SET seen_count = seen_count + 1 WHERE id = ?",
                             (existing["id"],))
            else:
                conn.execute("INSERT INTO pending_books (user_id, raw_title, raw_author) VALUES (?, ?, ?)",
                             (user_id, title, author))

        # Store every read book (book_id NULL when unmatched) so profile stats cover full history
        conn.execute("""
            INSERT INTO user_books (user_id, book_id, raw_title, raw_author, shelf,
                                    user_rating, date_read, match_status)
            VALUES (?, ?, ?, ?, 'read', ?, ?, ?)
        """, (user_id, book_id, title, author, rating, date_read, status))

    conn.commit()
    invalidate_user_recs(conn, user_id)     # new reads -> stale cached recs
    conn.commit()
    conn.close()
    return UploadResponse(total_read=total_read, **counts)


def compute_profile(conn, user_id, window="all"):
    cutoff = None
    if window in WINDOW_DAYS:
        cutoff = (datetime.now() - timedelta(days=WINDOW_DAYS[window])).date().isoformat()

    rows = conn.execute("""
        SELECT ub.user_rating, ub.match_status, ub.date_read,
               b.genres, b.tropes, b.tags, b.pacing, b.spice_level, b.focus
        FROM user_books ub LEFT JOIN books b ON ub.book_id = b.id
        WHERE ub.user_id = ? AND ub.shelf = 'read'
    """, (user_id,)).fetchall()

    total = rated = matched = 0
    rating_sum = 0.0
    gw, tw, tagw = defaultdict(float), defaultdict(float), defaultdict(float)
    gc, tc, tagc = defaultdict(int), defaultdict(int), defaultdict(int)
    pacing_d, spice_d, focus_d = defaultdict(int), defaultdict(int), defaultdict(int)

    for r in rows:
        if cutoff and (not r["date_read"] or r["date_read"] < cutoff):
            continue
        total += 1
        rating = r["user_rating"]
        if rating:
            rated += 1
            rating_sum += rating
        if r["genres"] is None:  # unmatched — counts toward stats, not taste
            continue
        matched += 1

        w = RATING_WEIGHTS.get(int(rating), 0.0) if rating else UNRATED_WEIGHT
        if r["match_status"] == "ambiguous":
            w *= AMBIGUOUS_FACTOR

        for g in json.loads(r["genres"] or "[]"):
            gw[g] += w; gc[g] += 1
        for t in json.loads(r["tropes"] or "[]"):
            tw[t] += w; tc[t] += 1
        # canonicalize + dedupe per book so synonym tags don't double-count
        for t in {canonical_tag(t) for t in json.loads(r["tags"] or "[]")
                  if not is_junk_tag(t)}:
            tagw[t] += w; tagc[t] += 1

        # Distributions from books rated highly (spec: distribution, not average)
        if rating and rating >= 4:
            if r["pacing"]: pacing_d[r["pacing"]] += 1
            spice_d[canonical_spice(r["spice_level"])] += 1
            if r["focus"]: focus_d[r["focus"]] += 1

    def top(weights, counts, n=10):
        items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
        # `slug` is the raw taxonomy slug (used for filtering recs); `name` is the
        # human-readable display label.
        return [{"name": k, "slug": k, "weight": round(v, 2), "count": counts[k]}
                for k, v in items if v > 0 and not is_junk_tag(k)][:n]

    return {
        "window": window,
        "total_books": total,
        "matched_books": matched,
        "rated_books": rated,
        "avg_rating": round(rating_sum / rated, 2) if rated else None,
        "top_genres": top(gw, gc),
        "top_tropes": [{**i, "name": humanize(i["slug"])} for i in top(tw, tc)],
        "top_tags": [{**i, "name": humanize(i["slug"])} for i in top(tagw, tagc, n=15)],
        "pacing": dict(pacing_d),
        "spice": dict(spice_d),
        "focus": dict(focus_d),
        "_raw": {"gw": dict(gw), "tw": dict(tw), "tagw": dict(tagw),
                 "pacing": dict(pacing_d), "spice": dict(spice_d), "focus": dict(focus_d)},
    }


@app.get("/api/profile")
def get_profile(window: str = "all", user_id: str = Depends(current_user)):
    init_db()
    conn = get_db()
    profile = compute_profile(conn, user_id, window)
    profile["catalog_total"] = conn.execute(
        "SELECT COUNT(*) FROM books").fetchone()[0]
    conn.close()
    profile.pop("_raw")
    return profile


@app.get("/api/matched-books")
def get_matched_books(window: str = "all", user_id: str = Depends(current_user)):
    """The user's Read-shelf books that matched a catalog entry."""
    init_db()
    conn = get_db()
    cutoff = None
    if window in WINDOW_DAYS:
        cutoff = (datetime.now() - timedelta(days=WINDOW_DAYS[window])).date().isoformat()
    rows = conn.execute("""
        SELECT ub.id, ub.raw_title, ub.user_rating, ub.date_read, ub.match_status,
               b.title, b.author, b.genres
        FROM user_books ub JOIN books b ON ub.book_id = b.id
        WHERE ub.user_id = ? AND ub.shelf = 'read'
        ORDER BY ub.date_read DESC
    """, (user_id,)).fetchall()
    conn.close()
    books = []
    for r in rows:
        if cutoff and (not r["date_read"] or r["date_read"] < cutoff):
            continue
        books.append({
            "id": r["id"],
            "title": r["title"], "author": r["author"],
            "rating": r["user_rating"], "date_read": r["date_read"],
            "match_status": r["match_status"],
            "genres": json.loads(r["genres"] or "[]"),
        })
    return {"window": window, "count": len(books), "books": books}


@app.post("/api/matched-books/{ub_id}/flag")
def flag_mismatch(ub_id: int, user_id: str = Depends(current_user)):
    """User reports this catalog match is wrong. Detach it — set the entry back
    to 'unmatched' so the wrong book stops skewing the taste profile — and add it
    to the per-user pending ('not in catalog') list."""
    conn = get_db()
    row = conn.execute(
        "SELECT raw_title, raw_author, book_id FROM user_books WHERE id = ? AND user_id = ?",
        (ub_id, user_id)).fetchone()
    if not row or row["book_id"] is None:
        conn.close()
        raise HTTPException(status_code=404, detail="No such matched book")
    conn.execute("UPDATE user_books SET book_id = NULL, match_status = 'unmatched' WHERE id = ?",
                 (ub_id,))
    existing = conn.execute(
        "SELECT id FROM pending_books WHERE raw_title = ? AND raw_author = ? AND user_id = ?",
        (row["raw_title"], row["raw_author"], user_id)).fetchone()
    if existing:
        conn.execute("UPDATE pending_books SET seen_count = seen_count + 1 WHERE id = ?",
                     (existing["id"],))
    else:
        conn.execute("INSERT INTO pending_books (user_id, raw_title, raw_author) VALUES (?, ?, ?)",
                     (user_id, row["raw_title"], row["raw_author"]))
    invalidate_user_recs(conn, user_id)
    conn.commit()
    conn.close()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Catalog cache: the recommender used to load + JSON-parse ~64k books and
# recompute the global IDF on EVERY request. Both are user-independent, so we
# build them once and hold them in memory, rebuilding at most every few minutes
# so offline enrichment eventually shows up without a restart.
# ---------------------------------------------------------------------------
_CATALOG = {"books": None, "idf": None, "built_at": 0.0}
_CATALOG_TTL = 600            # seconds
REC_CACHE_TTL = 1800          # per-user cached recommendations valid this long


def _build_catalog(conn):
    rows = conn.execute(
        "SELECT id,title,author,genres,tropes,tags,pacing,spice_level,focus FROM books "
        "WHERE ((tropes IS NOT NULL AND tropes != '[]') OR (tags IS NOT NULL AND tags != '[]')) "
        "AND (status IS NULL OR status NOT LIKE 'archived%')").fetchall()
    books, df = [], defaultdict(int)
    for r in rows:
        tr = json.loads(r["tropes"] or "[]")
        tg = list({canonical_tag(t) for t in json.loads(r["tags"] or "[]")})
        books.append({"id": r["id"], "title": r["title"], "author": r["author"],
                      "genres": json.loads(r["genres"] or "[]"), "tropes": tr, "tags": tg,
                      "pacing": r["pacing"], "spice": canonical_spice(r["spice_level"]),
                      "focus": r["focus"]})
        for t in set(tr) | set(tg):
            df[t] += 1
    n = len(books) or 1
    idf = {t: math.log(n / c) for t, c in df.items()}
    return books, idf


def get_catalog(conn):
    now = time.time()
    if _CATALOG["books"] is None or now - _CATALOG["built_at"] > _CATALOG_TTL:
        b, idf = _build_catalog(conn)
        _CATALOG.update(books=b, idf=idf, built_at=now)
    return _CATALOG["books"], _CATALOG["idf"]


def invalidate_user_recs(conn, user_id):
    conn.execute("DELETE FROM rec_cache WHERE user_id = ?", (user_id,))


@app.get("/api/recommendations")
def get_recommendations(window: str = "all", tropes: str = "", tags: str = "",
                        user_id: str = Depends(current_user)):
    init_db()
    conn = get_db()

    # Optional user-chosen filters: keep only recs that carry at least one of the
    # selected tropes/tags (match-ANY), still ranked by the taste model.
    sel_tropes = {t for t in tropes.split(",") if t.strip()}
    sel_tags = {t for t in tags.split(",") if t.strip()}
    sel = sel_tropes | sel_tags
    filt = f"t:{','.join(sorted(sel_tropes))}|g:{','.join(sorted(sel_tags))}"

    # Serve from the per-user cache if a fresh result exists.
    cached = conn.execute("SELECT payload, computed_at FROM rec_cache "
                          "WHERE user_id=? AND window=? AND filters=?",
                          (user_id, window, filt)).fetchone()
    if cached and cached["payload"]:
        try:
            age = (datetime.now() - datetime.fromisoformat(cached["computed_at"])).total_seconds()
        except Exception:
            age = 1e9
        if age < REC_CACHE_TTL:
            conn.close()
            return json.loads(cached["payload"])

    profile = compute_profile(conn, user_id, window)
    if profile["matched_books"] == 0:
        conn.close()
        return {"recommendations": [], "profile_books": 0,
                "note": "No catalog matches in this window yet — upload a CSV or widen the window."}

    raw = profile["_raw"]
    gw, tw, tagw = raw["gw"], raw["tw"], raw["tagw"]
    liked_total = sum(raw["pacing"].values()) or 1

    exclude = {r["book_id"] for r in conn.execute(
        "SELECT DISTINCT book_id FROM user_books WHERE user_id = ? AND book_id IS NOT NULL",
        (user_id,))}

    books, idf = get_catalog(conn)          # preparsed, cached
    scored = []
    for b in books:
        if b["id"] in exclude:
            continue
        genres, b_tropes, b_tags = b["genres"], b["tropes"], b["tags"]
        score = (sum(gw.get(g, 0) for g in genres) * 0.3
                 + sum(tw.get(t, 0) * idf.get(t, 1.0) for t in b_tropes) * 0.3
                 + sum(tagw.get(t, 0) * idf.get(t, 1.0) for t in b_tags) * 0.4)
        score += raw["pacing"].get(b["pacing"], 0) / liked_total * 1.5
        score += raw["spice"].get(b["spice"], 0) / liked_total * 1.0
        score += raw["focus"].get(b["focus"], 0) / liked_total * 1.0
        if score <= 0:
            continue

        # Distinctive shared traits lead (tropes + specific tags first, moods last).
        cand = ([(t, tw.get(t, 0) * idf.get(t, 1.0), 0) for t in b_tropes if tw.get(t, 0) > 0]
                + [(t, tagw.get(t, 0) * idf.get(t, 1.0), 1 if t in MOODS else 0)
                   for t in b_tags if tagw.get(t, 0) > 0])
        overlap, seen = [], set()
        for name, w, is_mood in sorted(cand, key=lambda kv: (kv[2], -kv[1])):
            key = re.sub(r"[^a-z0-9]", "", canonical_tag(humanize(name)))
            if key not in seen and not is_junk_tag(name):
                seen.add(key)
                overlap.append(humanize(name))
        reason_bits = overlap[:3]
        reason = (f"Shares {', '.join(reason_bits)} with your top-rated reads"
                  if reason_bits else f"Strong {genres[0] if genres else 'genre'} match")

        scored.append({
            "book_id": b["id"], "title": b["title"], "author": b["author"],
            "score": round(score, 2), "reason": reason,
            "category": " · ".join(genres[:2]) if genres else "Other",
            "genres": genres[:3], "chips": overlap[:4],
            "_tropes": b_tropes, "_tags": b_tags,
        })

    if sel:
        scored = [r for r in scored if (set(r["_tropes"]) | set(r["_tags"])) & sel]

    # Diversity pass: top 3 per category, categories ordered by their best score
    scored.sort(key=lambda x: x["score"], reverse=True)
    by_cat, order = defaultdict(list), []
    for rec in scored:
        if rec["category"] not in by_cat:
            order.append(rec["category"])
        if len(by_cat[rec["category"]]) < 3:
            by_cat[rec["category"]].append(rec)
    final = [rec for cat in order for rec in by_cat[cat]][:15]
    for rec in final:
        rec.pop("_tropes", None)
        rec.pop("_tags", None)

    # Persist served recs so feedback can link to them (best-effort under a lock).
    try:
        for rec in final:
            cur = conn.execute(
                "INSERT INTO recommendations (user_id, book_id, score, score_breakdown) VALUES (?, ?, ?, ?)",
                (user_id, rec["book_id"], rec["score"], json.dumps({"reason": rec["reason"]})))
            rec["id"] = cur.lastrowid
        conn.commit()
    except sqlite3.OperationalError:
        for rec in final:
            rec.setdefault("id", None)

    note = None
    if sel and not final:
        note = "No recommendations match the selected filters in this window — try fewer or clear them."
    result = {"recommendations": final, "profile_books": profile["matched_books"],
              "note": note, "filtered": bool(sel)}

    # Cache the result for this (user, window, filters).
    try:
        conn.execute("INSERT OR REPLACE INTO rec_cache (user_id, window, filters, payload, computed_at) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (user_id, window, filt, json.dumps(result), datetime.now().isoformat()))
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()
    return result


class FeedbackRequest(BaseModel):
    recommendation_id: int
    rating: str
    reason_tag: str | None = None


@app.post("/api/feedback")
def submit_feedback(feedback: FeedbackRequest, user_id: str = Depends(current_user)):
    conn = get_db()
    # only accept feedback on a recommendation that belongs to this user
    owns = conn.execute("SELECT 1 FROM recommendations WHERE id=? AND user_id=?",
                        (feedback.recommendation_id, user_id)).fetchone()
    if not owns:
        conn.close()
        raise HTTPException(status_code=404, detail="Recommendation not found")
    conn.execute(
        "INSERT INTO feedback (recommendation_id, user_id, rating, reason_tags) VALUES (?, ?, ?, ?)",
        (feedback.recommendation_id, user_id, feedback.rating, feedback.reason_tag))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/pending-books")
def get_pending_books(limit: int = 100, user_id: str = Depends(current_user)):
    """Unmatched ('not in catalog') books for the user. Newest-of-equal-count
    first so freshly flagged mismatches surface. Pass limit=0 for the full list."""
    init_db()
    conn = get_db()
    q = ("SELECT id, raw_title, raw_author, seen_count FROM pending_books "
         "WHERE user_id = ? ORDER BY seen_count DESC, first_seen_at DESC")
    params = [user_id]
    if limit and limit > 0:
        q += " LIMIT ?"
        params.append(limit)
    books = [dict(r) for r in conn.execute(q, params)]
    conn.close()
    return books


@app.get("/privacy")
async def serve_privacy():
    p = os.path.join(FRONTEND_DIST, "privacy.html")
    if os.path.exists(p):
        return FileResponse(p)
    raise HTTPException(status_code=404, detail="Privacy page not built")


@app.get("/")
async def serve_index():
    built = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(built):
        return FileResponse(built)
    # Fallback: legacy single-file prototype (pre-build-step).
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


if __name__ == "__main__":
    init_db()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

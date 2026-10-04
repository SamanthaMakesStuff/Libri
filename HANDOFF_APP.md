# Handover — app / UI / multi-user (2026-08)

Covers the web app. For the enrichment pipeline see `HANDOFF.md`. For auth setup
see `MULTIUSER.md`.

## Environment
- New laptop; Python installed fresh. **`python` on PATH is the broken Windows
  Store stub** — use the full path: `C:\Users\Samantha\AppData\Local\Programs\Python\Python312\python.exe`.
- Deps installed: fastapi, uvicorn, rapidfuzz, langdetect, bs4, **authlib, itsdangerous** (+ requirements.txt).
- **Node 24 LTS installed** (`C:\Program Files\nodejs`, via winget). Frontend build:
  `cd frontend && npm install && npm run build` → `frontend/dist/`. Rebuild after any
  UI change (or run `npm run dev` for HMR with the API proxied to :8000).
- Run app: `python app.py` (uvicorn, port 8000, host 127.0.0.1). Serves the built
  `frontend/dist/`. `.claude/launch.json` points at the full python path; MCP
  `preview_start name:"BookRec Backend"`.
- Browser-pane screenshots are flaky ("pane not displayed"); verify via
  `javascript_tool` DOM measurements instead.

## What this app is
Personal→multi-user book recommender. FastAPI + SQLite (`book_rec.db`, ~96.8k
books), pure-code scorer (genres 30% / tropes 30% / tags 40% + pacing/spice/focus,
IDF rarity weighting). Frontend is one file: `static/index.html` (React + Babel via
CDN, "Lumina" design system).

## Done this session
1. **Lumina UI redesign** (`static/index.html`): Fraunces/Outfit fonts, 3 themes
   ×light/dark switcher (localStorage), landing↔profile views, time-window tabs,
   expandable matched-books, **shareable personality card** (derived archetype,
   PNG download/native-share), multi-select trope/tag **filter chips**
   (match-ANY), redesigned rec grid. Hero is a 2-col grid (`.hero-grid`, 1040px
   breakpoint): stats+bars+pacing/spice/focus left, personality card right, equal
   height. Responsive to mobile (single col, no h-scroll).
2. **Backend perf/caching** (`app.py`): in-memory catalog+IDF cache
   (`_build_catalog`/`get_catalog`, 10-min TTL) so requests stop re-parsing 64k
   rows; per-user `rec_cache` table (30-min TTL), invalidated on upload. Repeat
   recs ~28ms, cold ~0.7s.
3. **Multi-user rebuild** (all 4 steps): schema already had `users`/per-user FKs.
   - `_migrate_multiuser.py` (idempotent, backs up DB → `backups/book_rec.db.premultiuser_*`):
     added users OAuth cols, `pending_books.user_id` (privacy), `rec_cache`. `schema.sql` updated.
   - Google OAuth (Authlib) + SessionMiddleware. `current_user` dependency replaced
     hardcoded `USER_ID` in every endpoint; `compute_profile(conn, user_id, window)`.
   - **Dev mode** (no Google env) = demo user `test_user`, app fully usable.
     **Production** (set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`SESSION_SECRET`)
     = real login, unauth endpoints 401. Both verified.
   - Frontend: login screen, user chip + logout, "Demo Mode" chip. `/api/me` gates.

## Key files
- `app.py` — API + scorer + auth + serves `frontend/dist`.
- `frontend/` — Vite+React UI (source of truth): `src/main.jsx`, `src/styles.css`,
  `index.html`, `vite.config.js`, `vercel.json`, `README.md`, `.env.example`.
- `static/index.html` — **legacy** single-file prototype; only a fallback now.
- `_migrate_multiuser.py`, `schema.sql`, `MULTIUSER.md`.

## Data reality (matters for "public beta")
Tropes (most discriminative signal) sit on only ~8.7% of books; recs lean on
tags/moods for the long tail. Deterministic enrichment near its ceiling; real
jump needs LLM enrichment (blocked on API key). ~866 non-English archived
(`status LIKE 'archived%'`, excluded from recs).

## Next / open (rough priority)
- ~~401-redirect polish (expired session mid-use → login screen).~~ **Done** —
  `static/index.html`: central `check401`/`AuthError` routes every 401 (all `api()`
  calls + raw upload/feedback fetches) through `_onUnauth`, which flips to the login
  view and shows a "session expired" banner while keeping the chosen theme. Verified
  by simulating a 401 (fetch override) → clean drop to login, no console errors.
- ~~Frontend build step + self-host CDN deps.~~ **Done** — Vite + React project in
  `frontend/` is now the source of truth (`src/main.jsx` = whole app, `src/styles.css`,
  `index.html` entry). React/ReactDOM/html2canvas are bundled (no more unpkg/Babel
  CDN); only Google Fonts stays remote. `npm run build` → `frontend/dist/`; `app.py`
  serves `dist/index.html` + mounts `/assets` (falls back to legacy `static/index.html`
  if unbuilt). Fetches go through `xfetch` with a `VITE_API_BASE` prefix + `credentials:
  'include'` so a remote backend works without code changes. **Node 24 LTS was
  installed via winget** (was absent). Verified: built bundle renders full UI (no Babel,
  no global React), tab-switch loads recs, no console errors. See `frontend/README.md`.
- ~~Self-host fonts (last CDN dep).~~ **Done** — `@fontsource/fraunces` +
  `@fontsource/outfit` imported in `src/main.jsx` (weights 400-700 / 300-700), Google
  Fonts `<link>` removed from `index.html`. App is now **fully CDN-free**. Verified:
  9 faces load from bundle, `fonts.check` passes, **zero requests to google/gstatic**
  (GDPR win — no visitor-IP leak to Google).
- ~~Mobile polish.~~ **Done** — fixed mobile horizontal scroll: `.nav`/`.nav-actions`
  now `flex-wrap`, and `.hero-grid` base column `1fr`→`minmax(0,1fr)` + `min-width:0`
  on items (the `1fr` min-content blowout made a 374px column in a 335px box). Verified
  no h-scroll at 375/768, desktop 2-col hero intact at 1280, matched table scrolls
  internally. Minor: mobile nav is ~158px tall (actions wrap to their own rows) — could
  compact later, not broken.
- Deployment: HTTPS, publish OAuth consent screen, workers/monitoring. Consider
  Postgres before real traffic. **Session cookie + CORS are now env-gated** in
  `app.py`: `COOKIE_SAMESITE`, `COOKIE_SECURE=1`, `CORS_ORIGINS` (all default to the
  single-origin/dev behaviour). Set them for a split deploy.
- **Hosting decision (open):** backend can't run on Vercel (writes to ~200 MB SQLite;
  Vercel FS is read-only). Options weighed — free: Oracle Cloud Always-Free VM (whole
  app single-origin); near-free: Vercel (frontend) + Fly.io (backend + volume, ~$2-4/mo);
  Vercel + Render needs SQLite→Postgres rewrite (Render free disk is ephemeral). User
  to choose. Build works with all of them (single-origin now, `VITE_API_BASE` for split).
- Legal: catalog is scraped; Goodreads import is personal data. **Privacy policy
  drafted** — `frontend/public/privacy.html`, served at `/privacy` (app.py route +
  `vercel.json` rewrite), linked from the sign-in screen. UK-GDPR-oriented, accurate
  to real data flows; has **9 `[placeholders]`** (controller, contact, host/region,
  retention, date) to fill + a legal review before publishing. Catalog-scraping ToS
  risk is separate and still open.
- Optional: finish any mobile polish; tune rec scoring/chips.

## Gotchas
- Don't deploy without the Google env vars — falls back to a single shared demo profile.
- Recommendation results cache per (user,window,filters); enrichment changes show
  after the catalog TTL (~10min) or server restart.
- SQLite: `get_db()` sets busy_timeout+WAL; rec logging is best-effort under locks.

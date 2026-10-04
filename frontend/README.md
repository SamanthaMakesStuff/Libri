# Lumina frontend

React + Vite build for the Lumina UI. Replaces the old in-browser Babel prototype
(`../static/index.html`, kept only as a fallback). Source of truth:

- `src/main.jsx` — the whole app (components + `App` + mount).
- `src/styles.css` — the "Lumina" design system.
- `index.html` — Vite entry (fonts + `#root`).

## Develop

```bash
npm install
npm run dev          # Vite dev server on :5173, proxies /api and /auth to :8000
```

Run the FastAPI backend (`python app.py`, port 8000) alongside it. The dev proxy
(`vite.config.js`) makes them behave like one origin.

## Build

```bash
npm run build        # → frontend/dist/
```

`dist/` is what gets served in production:

- **Single-origin** (default): FastAPI serves `dist/index.html` and mounts
  `dist/assets` at `/assets` (see `app.py`). Nothing else to configure — leave
  `VITE_API_BASE` empty. Just rebuild after frontend changes.
- **Split** (frontend on Vercel, backend elsewhere): set `VITE_API_BASE` to the
  backend origin at build time (see `.env.example`). All API/auth calls and the
  Google sign-in link then point there. The backend must also set
  `CORS_ORIGINS=<this frontend's URL>`, `COOKIE_SAMESITE=none`, `COOKIE_SECURE=1`.

## Deploy to Vercel

Point the Vercel project's **Root Directory** at `frontend/`. `vercel.json` pins
the Vite framework preset (build `npm run build`, output `dist`). Add
`VITE_API_BASE` under the project's Environment Variables.

> Note: only the static frontend can go on Vercel. The FastAPI backend writes to
> a ~200 MB SQLite file and needs a host with a persistent, writable disk.

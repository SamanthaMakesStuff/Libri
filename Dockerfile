# syntax=docker/dockerfile:1

# ---- Stage 1: build the Vite/React frontend -> frontend/dist ----------------
# Built inside the image so we never rely on a committed dist/ (it's gitignored).
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# VITE_API_BASE is intentionally left empty -> the bundle calls the API on the
# same origin, which is exactly how FastAPI serves it here (single-origin deploy).
RUN npm run build

# ---- Stage 2: Python runtime ------------------------------------------------
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/book_rec.db

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Only what the web app needs at runtime. The 199MB DB is NOT baked in — it
# lives on the Fly volume mounted at /data (see fly.toml). schema.sql/static are
# small and kept for the legacy fallback paths in app.py.
COPY app.py schema.sql ./
COPY static/ ./static/
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8080
# Note: uvicorn is invoked directly (not `python app.py`), so app.py's __main__
# block — which would rebuild the DB — never runs. The pre-seeded DB on the
# volume is used as-is.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]

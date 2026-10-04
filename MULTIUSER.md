# Multi-user & Google sign-in

The app supports real per-user accounts via Google OAuth. It runs in one of two
modes depending on whether Google credentials are present:

| Mode | When | Behaviour |
|---|---|---|
| **Dev / demo** | no Google env vars set | Everyone is the shared `test_user` account. No login needed. The nav shows a **Demo Mode** chip. Good for local work. |
| **Production** | `GOOGLE_CLIENT_ID` **and** `GOOGLE_CLIENT_SECRET` set | Real login enforced. Unauthenticated API calls return **401**; the frontend shows a *Sign in with Google* screen. Each user gets their own imports, profile, and recommendations. |

The switch is automatic — `OAUTH_ENABLED` in `app.py` is simply
`bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)`.

> ⚠️ In production you **must** set the Google vars. If they're missing, the app
> falls back to demo mode and everyone shares one profile.

---

## 1. Create a Google OAuth client

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) → create or pick a project.
2. **APIs & Services → OAuth consent screen** — configure it (External is fine for a beta;
   add your email as a test user while it's unverified).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Web application**
   - **Authorized redirect URIs** (add each environment you'll run):
     - `http://localhost:8000/auth/callback`  — local testing
     - `https://YOUR-DOMAIN/auth/callback`     — production
4. Copy the **Client ID** and **Client secret**.

The requested scopes are `openid email profile` (name, email, avatar only).

## 2. Set environment variables

```bash
export GOOGLE_CLIENT_ID="…apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="…"
export SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

- `SESSION_SECRET` signs the session cookie — use a long random value and keep it
  stable (changing it logs everyone out). The default in code is an insecure
  placeholder for dev only.

On Windows PowerShell:
```powershell
$env:GOOGLE_CLIENT_ID="…"; $env:GOOGLE_CLIENT_SECRET="…"; $env:SESSION_SECRET="…"
```

## 3. Run

```bash
python app.py                     # or: uvicorn app:app --host 0.0.0.0 --port 8000
```

Visit the site → **Sign in with Google** → you're redirected back logged in.

---

## Auth endpoints (reference)

| Route | Purpose |
|---|---|
| `GET /auth/login` | Start Google sign-in (redirects to Google). In dev, logs straight in as demo. |
| `GET /auth/callback` | OAuth return; finds-or-creates the user and sets the session. |
| `POST /auth/logout` | Clears the session. |
| `GET /api/me` | `{ authenticated, oauth_enabled, demo, user }` — the frontend uses this to gate. |

Users are matched by Google subject id, then linked by email if an account with
that email already exists (`_find_or_create_oauth_user` in `app.py`).

## Schema

The multi-user tables already existed; `_migrate_multiuser.py` (idempotent, backs
up the DB first) adds:
- `users`: `email`, `oauth_provider`, `oauth_sub`, `avatar_url` (+ unique indexes)
- `pending_books.user_id` (was global — scoping it prevents leaking one user's
  imports to everyone)
- `rec_cache` (per-user recommendation cache)

`schema.sql` reflects the final shape for fresh installs.

## Before public traffic

- ~~Session cookie `https_only=True`.~~ Now env-gated in `app.py`: set
  `COOKIE_SECURE=1` (and `COOKIE_SAMESITE=none` for a cross-origin/split deploy)
  once behind HTTPS. Defaults stay Lax/insecure for local http.
- Publish the OAuth consent screen (out of "testing") so anyone can sign in.
  *(Manual Google Cloud Console step — see §1 above.)*
- ~~Client-side 401 handler for expired sessions.~~ **Done** — a central
  `check401`/`_onUnauth` in the frontend bounces an expired session to the login
  screen with a "session expired" banner (see `HANDOFF_APP.md`).
- Privacy policy: a **draft** is served at `/privacy` (source
  `frontend/public/privacy.html`) and linked from the sign-in screen. Fill in the
  9 highlighted placeholders (controller name, contact email, host/region,
  retention periods, date) and review before going public.

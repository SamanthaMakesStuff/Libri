# Deploying BookRec to Fly.io — the simple guide

This walks you through putting the app on the internet on [Fly.io](https://fly.io),
step by step, in plain language. You run every command in **PowerShell** on your
own machine (open the Start menu, type "PowerShell", hit Enter).

**The big picture (the analogy):** Fly gives you a tiny computer in a data centre.
We put your app on it as a sealed box (a "Docker image"), and we bolt on a small
hard drive (a "volume") that keeps your database safe even when the box is
replaced. You talk to Fly with a command tool called `fly`.

Expected cost: **~$4/month** (512 MB machine + 3 GB disk). No minimum fee.

---

## One-time: things you do once, ever

### Step 1 — Install the Fly tool (`fly`)

In PowerShell, paste this and press Enter:

```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

When it finishes, **close PowerShell and open it again** (so it can find the new
tool). Check it worked:

```powershell
fly version
```

If you see a version number, you're good. If it says "not recognized", the
install printed a line telling you to add a folder to your PATH — follow that,
or just reopen PowerShell once more.

### Step 2 — Make a Fly account / log in

```powershell
fly auth signup
```

This opens your web browser. Create an account (or click "sign in" if you
already have one). Fly **requires a credit/debit card** even though your usage
will be tiny — this is normal, it's how they stop abuse. Billing is by actual
usage, so a sleepy little app costs a few dollars a month.

Already have an account? Use `fly auth login` instead.

---

## Setting up your app (the first deploy)

Do all of this from inside your project folder:

```powershell
cd C:\Users\Samantha\BookRec
```

### Step 3 — Create the app on Fly

```powershell
fly launch --no-deploy
```

This reads the `fly.toml` file that's already in your project. It will ask a few
questions:

- **"Copy configuration to the new app?"** → **Yes**.
- **"Tweak these settings?"** → **No** (the settings are already correct).
- If it says the name **`bookrec-lumina` is taken**, it will ask for a new one.
  Type something unique (e.g. `libri-sam`). It updates `fly.toml` for you.
- If it ever offers a **Postgres or Redis database** → **No**. You don't need
  one; your data is a SQLite file.

`--no-deploy` means "set everything up but don't go live yet" — because we still
need to attach the disk first.

> **Write down your app name.** Your site will live at
> `https://YOUR-APP-NAME.fly.dev`. You can always see it again with `fly info`.

### Step 4 — Attach the hard drive (the "volume")

This is the disk that keeps your database. The name **must** be `book_data` and
the region **must** match your app (London = `lhr`), because `fly.toml` expects
exactly that:

```powershell
fly volumes create book_data --size 3 --region lhr
```

It warns that a single volume isn't redundant and asks **"Yes/No"** → **Yes**.
(For a personal app one disk is fine; Fly takes daily backups automatically.)

### Step 5 — Set your secret passwords

These are kept encrypted on Fly, never in your code. First, a random key that
signs login cookies:

```powershell
fly secrets set SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

> If that line errors, generate the value on its own and paste it in:
> run `python -c "import secrets; print(secrets.token_urlsafe(48))"`, copy the
> output, then run `fly secrets set SESSION_SECRET="paste-it-here"`.

You can add Google login later (see "Turning on Google sign-in" below). Until
you do, the app runs in **demo mode** — anyone visiting is the shared demo
account. That's perfect for a first test.

### Step 6 — Go live!

```powershell
fly deploy
```

Fly builds your app (this takes a few minutes the first time — it's compiling
the frontend and installing Python) and starts it. When it finishes, open it:

```powershell
fly open
```

Your site appears in the browser. **It works, but it has no books yet** — because
the database isn't on the disk yet. That's the next step.

### Step 7 — Put your database on the disk (do this once)

Your `book_rec.db` (about 199 MB) lives on your computer and needs to be copied
onto the Fly volume. From your project folder:

```powershell
fly ssh sftp shell
```

This opens a little file-transfer prompt. Type this line and press Enter:

```
put book_rec.db /data/book_rec.db
```

Wait for it to finish (a 199 MB upload — give it a minute or two), then type
`quit` to leave.

> **If it says it can't connect:** your machine may be asleep (we set it to nap
> when idle to save money). Wake it with `fly machine start`, then try the
> `fly ssh sftp shell` command again.

> ⚠️ **The 199 MB upload keeps dropping ("connection lost")?** That's expected —
> Fly's sftp tunnel is flaky for big files and has no resume. **Use the reliable
> compressed method in the Troubleshooting section below** ("Uploading a big
> database without the connection dropping"). It's what actually works.

Now refresh your site — your books are there. **You're live.** 🎉

---

## Turning on Google sign-in (optional, do it when ready)

Out of the box the app is in demo mode (one shared account). To give each
visitor their own account, add Google login. The full details are in
[`MULTIUSER.md`](MULTIUSER.md); the short version:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) → create
   a project → **APIs & Services → Credentials → Create OAuth client ID** →
   type **Web application**.
2. Under **Authorized redirect URIs**, add exactly:
   `https://YOUR-APP-NAME.fly.dev/auth/callback`
3. Copy the **Client ID** and **Client secret**, then set them on Fly:

```powershell
fly secrets set GOOGLE_CLIENT_ID="...apps.googleusercontent.com" GOOGLE_CLIENT_SECRET="..."
```

Setting secrets automatically restarts the app. Visit your site → you'll now get
a "Sign in with Google" screen. (While your Google project is "in testing", only
email addresses you add as test users can log in — publish the consent screen
when you're ready for the public.)

---

## Turning on auto-deploy from GitHub (optional, recommended)

Right now you deploy by typing `fly deploy`. If you'd rather have it deploy
automatically every time you push code to GitHub:

1. Make a deploy token:

```powershell
fly tokens create deploy
```

2. Copy the whole token it prints (starts with `FlyV1 ...`).
3. In your browser, go to
   **https://github.com/SamanthaMakesStuff/Lumina/settings/secrets/actions** →
   **New repository secret**. Name it exactly `FLY_API_TOKEN`, paste the token,
   save.

That's it. The workflow file (`.github/workflows/fly-deploy.yml`) is already in
your repo, so from now on `git push` to `main` deploys for you.

---

## Everyday commands (your cheat sheet)

| I want to... | Command |
|---|---|
| Open my live site | `fly open` |
| See if it's running | `fly status` |
| Watch what it's doing (live logs) | `fly logs` |
| Deploy after code changes | `fly deploy` |
| Wake a sleeping machine | `fly machine start` |
| See my app's name/URL | `fly info` |
| Check this month's cost | `fly dashboard` (opens billing in browser) |

---

## If something goes wrong

- **Deploy fails with an error:** run `fly logs` and read the last lines — it
  usually says what broke. Most first-time issues are a typo in `fly.toml` or a
  missing secret.
- **Site loads but says a server error / no data:** the database probably isn't
  uploaded yet, or isn't at `/data/book_rec.db`. Redo Step 7.
- **"Out of memory" / machine keeps restarting in the logs:** bump the memory.
  Edit `fly.toml`, change `memory = "512mb"` to `"1024mb"`, run `fly deploy`.
  (This raises cost to ~$6/mo — or try `"256mb"` to go cheaper if it's stable.)
- **Login redirect fails:** the redirect URI in Google Cloud must match your
  real `.fly.dev` URL exactly, including `https://` and `/auth/callback`.
- **It's asleep and slow on the first visit:** that's normal — we set it to nap
  when idle to save money, so the first request after a quiet spell takes ~1–2
  seconds to wake. Every visit after is instant.

---

## Backing up your database (good habit)

Your data lives on the Fly disk and Fly snapshots it daily, but it's wise to
keep your own copy now and then. From your project folder:

```powershell
fly ssh sftp get /data/book_rec.db book_rec.backup.db
```

That downloads the live database to your computer as `book_rec.backup.db`.

---

## Troubleshooting recipes (things we actually hit)

### Uploading a big database without the connection dropping

Fly's `fly ssh sftp` tunnel is unreliable for large files — a ~199 MB upload
tends to die partway with `copy file: connection lost (… bytes written)`, and
there's no resume, so retrying hits the same wall. A SQLite database compresses
a lot (ours went from 199 MB to ~62 MB), so the trick is: **compress it, upload
the small file, unpack it on the server.**

1. **Compress the database locally.** (Git Bash has `gzip`; or any zip tool.)
   ```bash
   gzip -c book_rec.db > book_rec.db.gz
   ```
   This creates `book_rec.db.gz` (~62 MB) — small enough to upload in one go.

2. **Clear any partial/corrupt files on the server** (a failed upload leaves a
   stub behind):
   ```powershell
   fly ssh console -C "rm -f /data/book_rec.db /data/book_rec.db-wal /data/book_rec.db-shm /data/book_rec.db.gz"
   ```

3. **Upload the compressed file and the unpack helper.** `_unpack_db.py` is a
   tiny script kept in the repo for exactly this. In the sftp shell
   (`fly ssh sftp shell`), at the `»` prompt:
   ```
   put _unpack_db.py /data/_unpack_db.py
   put book_rec.db.gz /data/book_rec.db.gz
   ```
   Wait for the big one to finish, then `quit`. Don't open the website while
   uploading (it would make the app recreate an empty DB and get in the way).

4. **Unpack on the server** — this rebuilds the real DB and deletes the `.gz`:
   ```powershell
   fly ssh console -C "python /data/_unpack_db.py"
   ```
   It prints `wrote 208629760 bytes …`. That exact byte count is your proof the
   file is complete.

5. **Restart** so the app opens the fresh database cleanly:
   ```powershell
   fly apps restart lumina
   ```

### "database disk image is malformed" (Internal Server Error on every page)

If the logs (`fly logs`) show `sqlite3.DatabaseError: database disk image is
malformed`, the database file on the volume is **corrupt or incomplete** — it is
*not* a code bug, and it is *not* an OAuth problem (login can succeed and still
hit this on the first data call). Two common causes:

- **A truncated upload** — the sftp transfer dropped partway (see above).
- **A stale WAL sidecar** — the app auto-created an empty `/data/book_rec.db`
  plus `-wal`/`-shm` files before you uploaded. Dropping a fresh main `.db` next
  to an old `-wal` makes SQLite try to replay the old journal onto it → malformed.

**Fix:** delete all three server files and re-upload cleanly (the compressed
method above deletes the sidecars for you in step 2). Then **verify the size**:
```powershell
fly ssh console -C "ls -la /data"
```
`book_rec.db` must read exactly **`208629760`** bytes. Anything smaller means the
upload was cut short — redo it.

To confirm your *local* copy is healthy before uploading:
```bash
python -c "import sqlite3; print(sqlite3.connect('book_rec.db').execute('PRAGMA integrity_check').fetchone()[0])"
```
It should print `ok`.

---

## Where your live data lives (important!)

Once the app is running, **all new data — user accounts, uploaded Goodreads
imports, the per-user "not in catalog yet" list, recommendations — is written to
`book_rec.db` on the Fly volume, not to the copy on your laptop.**

- It **persists** across restarts, redeploys, and the machine's idle naps, and
  Fly snapshots the volume daily.
- A Goodreads upload saves to two tables: `user_books` (every read book) and
  `pending_books` (the unmatched "not in catalog" list, one row per title with a
  `seen_count`). You can see the pending list at `/api/pending-books` while
  logged in.
- Your laptop's `book_rec.db` is the **older seed copy** and does *not* receive
  this live data. To pull the current live database down — e.g. to run the
  enrichment scripts against newly-pending books — use:
  ```powershell
  fly ssh sftp get /data/book_rec.db book_rec.live.db
  ```

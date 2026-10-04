"""Step 1 of the multi-user rebuild: schema + migration (idempotent).

Adds OAuth auth columns to `users`, scopes `pending_books` per user (privacy),
and creates `rec_cache` for the precompute step. Backs up the DB first. Safe to
re-run — every change is guarded.
"""
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C


def cols(c, t):
    return [r[1] for r in c.execute(f"PRAGMA table_info({t})")]


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"backups/book_rec.db.premultiuser_{ts}.bak"
    shutil.copy2(C.DB_PATH, backup)
    print(f"backed up DB -> {backup}")

    c = sqlite3.connect(C.DB_PATH, timeout=60)
    c.execute("PRAGMA busy_timeout=30000")

    # --- users: OAuth auth columns ---------------------------------------
    ucols = cols(c, "users")
    for col, ddl in [("email", "TEXT"), ("oauth_provider", "TEXT"),
                     ("oauth_sub", "TEXT"), ("avatar_url", "TEXT")]:
        if col not in ucols:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            print(f"  users + {col}")
    # NULLs are distinct in SQLite unique indexes, so the existing (email-less)
    # test_user row and future OAuth users coexist fine.
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_oauth "
              "ON users(oauth_provider, oauth_sub)")

    # --- pending_books: scope per user (was global -> would leak imports) --
    if "user_id" not in cols(c, "pending_books"):
        c.execute("ALTER TABLE pending_books ADD COLUMN user_id TEXT")
        n = c.execute("UPDATE pending_books SET user_id='test_user' "
                      "WHERE user_id IS NULL").rowcount
        c.execute("CREATE INDEX IF NOT EXISTS idx_pending_user "
                  "ON pending_books(user_id)")
        print(f"  pending_books + user_id (backfilled {n} rows -> test_user)")

    # --- per-user recommendation cache (used in the precompute step) ------
    c.execute("""CREATE TABLE IF NOT EXISTS rec_cache (
        user_id TEXT NOT NULL,
        window  TEXT NOT NULL,
        filters TEXT NOT NULL DEFAULT '',
        payload TEXT,
        computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, window, filters))""")

    c.commit()
    print("users cols now:", cols(c, "users"))
    print("pending_books cols now:", cols(c, "pending_books"))
    print("rec_cache:", "rec_cache" in
          [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
    c.close()
    print("migration complete")


if __name__ == "__main__":
    main()

"""Read-only: for a list of candidate tag slugs, report kind+status+usage."""
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

CANDIDATES = [
    "sapphic", "lesbian", "lgbtq", "gay", "queer", "transgender", "bisexual",
    "witches", "witchcraft", "witchy", "magic", "vampires", "ghosts", "pirates",
    "dragons", "space", "aliens", "murder", "police", "medical", "military",
    "spy", "spies", "detective", "atmospheric", "angsty", "suspenseful",
    "brooding", "humor", "cozy", "dark-academia", "gothic", "historical",
    "victorian", "regency", "western", "royalty", "mermaid", "mermaids",
    "steampunk", "cyberpunk", "dystopia", "apocalyptic", "zombies",
    "superheroes", "time-travel", "boarding-school", "small-town",
    "coming-of-age", "friendship", "family", "war", "romance", "fairy-tale",
    "fairy-tales", "retelling", "mythology", "epistolary", "noir",
    "psychological", "supernatural", "paranormal", "occult", "religion",
    "feminist", "satire", "adventure", "survival", "spooky", "creepy",
]

conn = sqlite3.connect(C.DB_PATH, timeout=600)
use = Counter()
for (t,) in conn.execute("SELECT tags FROM books WHERE tags IS NOT NULL AND tags!='[]'"):
    try:
        for s in json.loads(t):
            use[s] += 1
    except Exception:
        pass

rows = {}
for slug in CANDIDATES:
    r = list(conn.execute("SELECT kind, status FROM taxonomy WHERE slug=?", (slug,)))
    rows[slug] = r
conn.close()

for slug in CANDIDATES:
    r = rows[slug]
    info = ", ".join(f"{k}:{s}" for k, s in r) if r else "NOT IN TAXONOMY"
    print(f"  {slug:<18} use={use.get(slug,0):>5}   {info}")

"""Central config for the enrichment pipeline. No magic numbers elsewhere."""
import os
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "book_rec.db"
TAXONOMY_MD = ROOT / "taxonomy.md"

# --- API ---------------------------------------------------------------
# Key is read from env, or a gitignored file. Never hardcode.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or (
    (ROOT / "anthropic_key.txt").read_text(encoding="utf-8").strip()
    if (ROOT / "anthropic_key.txt").exists() else None)

MODEL_BULK = "claude-haiku-4-5"
MODEL_ESCALATE = "claude-sonnet-4-6"
BOOKS_PER_REQUEST = 20
REQUESTS_PER_BATCH = 750
MAX_SPEND_DEFAULT = 100.0          # USD hard stop

# --- Matching thresholds (Phase 0 / 6) ---------------------------------
FUZZY_AUTO_ALIAS = 92              # >= this token_sort_ratio -> auto-alias
EMBED_SUGGEST = 0.80               # >= this cosine -> suggest alias (review)
EMBED_AUTO_MERGE = 0.87            # >= this cosine -> auto-merge (Phase 6)
FUZZY_AUTO_MERGE = 92              # Phase 6 fuzzy auto-merge
EMBED_BORDERLINE_LOW = 0.70        # 0.70-0.87 -> LLM adjudication (Phase 6)
PROPOSED_MIN_FREQUENCY = 3         # below this, drop proposed terms as noise
AUTHOR_VERIFY_FUZZY = 90           # OL dump author verification (Phase 3)
EMBED_MODEL = "all-MiniLM-L6-v2"

# --- Open Library dumps (Phase 3a) -------------------------------------
OL_DIR = Path(r"D:\Downloads\ol_dump_2026-06-30")
OL_WORKS = OL_DIR / "ol_dump_works_2026-06-30.txt.gz"
OL_AUTHORS = OL_DIR / "ol_dump_authors_2026-06-30.txt.gz"
# No standalone editions dump was downloaded; editions live in the combined dump.
OL_EDITIONS = OL_DIR / "ol_dump_2026-06-30.txt.gz"
OL_CHECKPOINT = ROOT / "ol_ingest_checkpoint.json"

# --- Outputs -----------------------------------------------------------
TAXONOMY_REVIEW_CSV = ROOT / "taxonomy_review.csv"
PROPOSED_TERMS_CSV = ROOT / "proposed_terms_review.csv"
DUPES_REVIEW_CSV = ROOT / "dupes_review.csv"
CLEAN_LOG = ROOT / "clean_log.jsonl"
VOCAB_PROMPT = ROOT / "vocab_prompt.txt"

# --- Junk blocklist (Phase 0 step 5) -----------------------------------
# Exact raw terms that are shelf/format/ownership noise, never vocabulary.
BLOCKLIST_EXACT = {
    "#digitally-own", "digitally-own", "paperback", "hardcover", "hardback",
    "ebook", "e-book", "kindle", "audiobook", "audio", "audible",
    "all reviews & lists", "all reviews and lists", "books fiction",
    "english", "fiction in english", "anthologies", "book", "books",
    "fiction", "nonfiction", "non-fiction", "general", "unknown", "none",
    "to-read", "currently-reading", "read", "tbr", "owned", "wishlist",
    "favorites", "favourites", "default", "shelf", "my-books", "library",
    "reviews", "lists", "series", "novel", "novels", "adult", "new",
}
# Substring/prefix heuristics -> also blocklisted.
BLOCKLIST_SUBSTR = (
    "digitally", "borrowed", "loaned", "purchased", "bought",
    "to-buy", "wish-list", "reviewed", "review-", "shelf-", "goodreads",
    "storygraph", "netgalley", "calibre", "did-not-finish",
    "reread", "re-read", "currently", "rating",
)
# Rating/format noise needs ANCHORED patterns — a bare "-star" substring wrongly
# ate "star-crossed lovers" and "touch-starved", which are real tropes.
BLOCKLIST_REGEX = (
    r"^\d+\s*-?\s*stars?$",     # "5 stars", "5-star"
    r"^stars?$",
    r"^dnf$", r"^arc$", r"^own$", r"^owns$", r"^owned\b.*",
    r"^\d{4}$",                 # bare years
    r"^\d{4}\s*-\s*\d{4}$",     # date ranges e.g. 1939-1945
)
BLOCKLIST_PREFIX = ("#", "@", "http", "www.")

# StoryGraph-style moods — valuable, formalised as kind='mood' (brief Context).
MOODS = ["dark", "emotional", "tense", "mysterious", "adventurous", "reflective",
         "funny", "sad", "challenging", "relaxing", "inspiring", "hopeful",
         "lighthearted"]

# Non-fiction genre names used by triage (Phase 2).
NONFICTION_GENRES = {
    "Art", "History", "Biography & Memoir", "Business & Economics", "Cooking",
    "Health & Fitness", "Psychology", "Philosophy", "Politics",
    "Religion & Spirituality", "Self-Help", "Science & Nature", "True Crime",
    "Travel", "Music", "Education", "Reference",
}
FICTION_GENRES = {
    "Romance", "Fantasy", "Sci-Fi", "Mystery", "Thriller", "Horror",
    "Historical Fiction", "Literary Fiction", "General Fiction", "Adventure",
    "Erotica", "Western", "Humor", "Romantasy", "Paranormal", "Short Stories",
    "Graphic Novel",
}

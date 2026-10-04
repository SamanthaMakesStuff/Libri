"""Phase 0 — taxonomy compiler (`enrich taxonomy-build`).

Builds the `taxonomy` + `taxonomy_alias` tables from taxonomy.md and from the
vocabulary already present in `books`, with a full audit trail in `tag_merge_log`.
"""
import csv
import json
import re
import sqlite3
from collections import Counter

from rapidfuzz import fuzz, process

import config as C

# --- taxonomy.md structure -------------------------------------------------
# section number -> (genre display name(s) for `genres`, is_nonfiction)
SECTION_GENRES = {
    1: (["Romance"], False), 2: (["Fantasy"], False), 3: (["Sci-Fi"], False),
    4: (["Mystery", "Thriller"], False), 5: (["Horror"], False),
    6: (["Young Adult"], False), 7: (["Historical Fiction"], False),
    8: (["Literary Fiction"], False), 9: ([], False), 10: ([], True),
}
# The genre-kind rows implied by the section headers themselves.
SECTION_GENRE_ROWS = ["Romance", "Fantasy", "Sci-Fi", "Mystery", "Thriller",
                      "Horror", "Young Adult", "Historical Fiction",
                      "Literary Fiction"]

# Terms the doc explicitly flags as tag-level or warning-level, overriding
# their subsection's default kind.
KIND_OVERRIDES = {
    "hea": "tag", "hfn": "tag", "happily ever after": "tag",
    "happily for now": "tag", "dubcon": "warning",
    "closed door": "tag", "low spice": "tag", "fade to black": "tag",
    "moderate spice": "tag", "high spice": "tag", "explicit": "tag",
    "slow burn spice": "tag", "bdsm": "tag", "polyamory": "tag",
    "multiple pov intimacy scenes": "tag",
}

# Compound entries the doc writes as one chunk but which are two vocabulary terms.
POST_SPLIT = {"hea hfn": [("HEA", "tag"), ("HFN", "tag")]}


def _split_terms(paragraph):
    """Split a term list on commas that are NOT inside parentheses."""
    out, buf, depth = [], [], 0
    for ch in paragraph:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def slugify(text):
    """'Enemies to Lovers' -> 'enemies-to-lovers'."""
    t = de_camel(str(text)).lower()
    t = re.sub(r"&", " and ", t)
    t = re.sub(r"[^a-z0-9]+", "-", t)
    return re.sub(r"-+", "-", t).strip("-")


def de_camel(text):
    """'enemiesToLovers' -> 'enemies To Lovers' (before lowercasing)."""
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r" \1", str(text))


def normalize_raw(term):
    """Normalised comparison form of any raw vocabulary string."""
    t = de_camel(str(term)).lower().replace("_", " ")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_blocked(raw):
    t = normalize_raw(raw)
    r = str(raw).strip().lower()
    if not t or len(t) < 2:
        return True
    if r.startswith(C.BLOCKLIST_PREFIX):
        return True
    if t in C.BLOCKLIST_EXACT or r in C.BLOCKLIST_EXACT:
        return True
    if any(s in r for s in C.BLOCKLIST_SUBSTR):
        return True
    if any(re.match(p, t) for p in C.BLOCKLIST_REGEX):
        return True
    if re.fullmatch(r"[\d\s\-]+", t):          # bare numbers / years
        return True
    return False


# --- parsing ---------------------------------------------------------------
def _clean_term(raw):
    """Return (display, aliases[]) for one comma-separated taxonomy.md entry."""
    t = raw.strip()
    if not t:
        return None, []
    t = re.split(r"\s+[—–]\s+", t)[0].strip()      # drop em-dash commentary
    aliases = []
    for paren in re.findall(r"\(([^)]*)\)", t):
        p = paren.strip()
        # a parenthetical is an alias only if it reads like an expansion,
        # not an editorial note
        if (len(p.split()) <= 4 and not re.search(
                r"also|only|flag|note|see |context|cross-listed|e\.g\.", p, re.I)):
            aliases.append(p)
    t = re.sub(r"\s*\([^)]*\)", "", t).strip()      # strip complete parentheticals
    t = re.sub(r"\s*\([^)]*$", "", t).strip()       # strip a dangling "(" fragment
    t = t.strip(" .;:")
    return (t or None), [a.strip(" .;:") for a in aliases if a.strip(" .;:")]


def _term_paragraph(body):
    """Pick the comma-rich term list from a subsection body (skip prose)."""
    best, best_commas = None, 0
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if not p or p.startswith(("#", ">", "-", "*")):
            continue
        n = p.count(",")
        if n > best_commas:
            best, best_commas = p, n
    if not best or best_commas < 3:
        return None
    # lists are sometimes introduced by "...categories: term, term, ..."
    if ":" in best:
        head, _, tail = best.rpartition(":")
        if tail.count(",") >= 3:
            best = tail
    return best.strip()


def parse_taxonomy_md(path):
    """taxonomy.md -> [{display, kind, applies_to, genres, aliases}]."""
    text = path.read_text(encoding="utf-8")
    out, seen, by_slug = [], set(), {}

    def add(display, kind, applies_to, genres, aliases=(), universal=False):
        key = slugify(display)
        if not key:
            return
        if key in seen:
            # §9 lists cross-genre tropes: mark an already-seen term universal
            if universal:
                by_slug[key]["genres"] = []
            return
        seen.add(key)
        rec = {"display": display, "kind": kind, "applies_to": applies_to,
               "genres": genres, "aliases": list(aliases)}
        by_slug[key] = rec
        out.append(rec)

    for g in SECTION_GENRE_ROWS:                     # the genres themselves
        add(g, "genre", "fiction", [])

    # split into "## N. Title" sections
    sections = re.split(r"\n##\s+", text)
    for sec in sections:
        m = re.match(r"(\d+)\.\s*([^\n]+)\n(.*)", sec, re.S)
        if not m:
            continue
        num, _title, body = int(m.group(1)), m.group(2), m.group(3)
        if num not in SECTION_GENRES:
            continue
        genres, nonfiction = SECTION_GENRES[num]

        # subsections (### ...) or the whole body when there are none
        parts = re.split(r"\n###\s+", body)
        subs = ([("", parts[0])] if len(parts) == 1
                else [("", parts[0])] + [(p.split("\n", 1)[0].strip(),
                                          p.split("\n", 1)[1] if "\n" in p else "")
                                         for p in parts[1:]])
        for sub_title, sub_body in subs:
            para = _term_paragraph(sub_body)
            if not para:
                continue
            st = sub_title.lower()
            if nonfiction:
                kind, applies = "subject", "nonfiction"
            elif "subgenre" in st:
                kind, applies = "subgenre", "fiction"
            elif "spice" in st or "heat" in st:
                kind, applies = "tag", "fiction"
            else:
                kind, applies = "trope", "fiction"

            for chunk in _split_terms(para):
                display, aliases = _clean_term(chunk)
                if not display or len(display) < 2:
                    continue
                norm = normalize_raw(display)
                if norm in POST_SPLIT:               # e.g. "HEA / HFN" -> two tags
                    for d, k in POST_SPLIT[norm]:
                        add(d, k, applies, genres)
                    continue
                # override by full term or by its leading token ("dubcon (…)")
                k = (KIND_OVERRIDES.get(norm)
                     or KIND_OVERRIDES.get(norm.split()[0] if norm else "")
                     or kind)
                a = "both" if k == "warning" else applies
                add(display, k, a, genres, aliases, universal=(num == 9))

    for mood in C.MOODS:                             # brief: formalise moods
        add(mood, "mood", "both", [])
    return out


# --- DB --------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS taxonomy (
  slug TEXT PRIMARY KEY, display TEXT NOT NULL, kind TEXT NOT NULL,
  applies_to TEXT NOT NULL, genres TEXT DEFAULT '[]', definition TEXT,
  status TEXT DEFAULT 'active', merged_into TEXT, source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS taxonomy_alias (
  alias TEXT PRIMARY KEY, slug TEXT NOT NULL REFERENCES taxonomy(slug));
CREATE TABLE IF NOT EXISTS enrichment_state (
  book_id TEXT PRIMARY KEY REFERENCES books(id), book_class TEXT,
  needs_enrichment INTEGER, stage TEXT DEFAULT 'pending', confidence TEXT,
  batch_id TEXT, model TEXT, attempts INTEGER DEFAULT 0, last_error TEXT,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS tag_merge_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, raw_term TEXT, resolved_slug TEXT,
  method TEXT, score REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_tax_kind ON taxonomy(kind, status);
CREATE INDEX IF NOT EXISTS idx_state_stage ON enrichment_state(stage);
"""


def _propose(conn, raw, score):
    """Record a genuinely-new candidate term (status='proposed', never active)."""
    conn.execute(
        """INSERT OR IGNORE INTO taxonomy (slug, display, kind, applies_to,
           status, source) VALUES (?,?,'tag','both','proposed','existing_data')""",
        (slugify(raw), raw))
    conn.execute("INSERT INTO tag_merge_log (raw_term, resolved_slug, method, score)"
                 " VALUES (?,?,'new_proposed',?)", (raw, slugify(raw), score))


def build(dry_run=False):
    conn = sqlite3.connect(C.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)

    terms = parse_taxonomy_md(C.TAXONOMY_MD)
    print(f"parsed taxonomy.md -> {len(terms)} terms")

    if not dry_run:
        # idempotent: this pass fully re-resolves the raw vocabulary
        conn.execute("DELETE FROM tag_merge_log")
        for t in terms:
            conn.execute(
                """INSERT INTO taxonomy (slug, display, kind, applies_to, genres, source)
                   VALUES (?,?,?,?,?,'taxonomy_md')
                   ON CONFLICT(slug) DO UPDATE SET display=excluded.display,
                     kind=excluded.kind, applies_to=excluded.applies_to,
                     genres=excluded.genres""",
                (slugify(t["display"]), t["display"], t["kind"], t["applies_to"],
                 json.dumps(t["genres"])))
            for a in [t["display"]] + t["aliases"]:
                conn.execute("INSERT OR IGNORE INTO taxonomy_alias VALUES (?,?)",
                             (normalize_raw(a), slugify(t["display"])))
        conn.commit()

    # ---- ingest existing DB vocabulary -----------------------------------
    raw_terms = Counter()
    for r in conn.execute("SELECT tropes, tags FROM books"):
        for field in ("tropes", "tags"):
            for v in json.loads(r[field] or "[]"):
                if isinstance(v, str) and v.strip():
                    raw_terms[v.strip()] += 1
    print(f"distinct raw vocabulary in books: {len(raw_terms):,}")

    tax = {row["slug"]: row["display"] for row in
           conn.execute("SELECT slug, display FROM taxonomy WHERE status='active'")}
    alias_map = {row["alias"]: row["slug"] for row in
                 conn.execute("SELECT alias, slug FROM taxonomy_alias")}
    display_list = list(tax.values())
    display_to_slug = {d: s for s, d in tax.items()}

    # optional embedding tier
    embedder = None
    try:
        from sentence_transformers import SentenceTransformer, util  # noqa
        embedder = SentenceTransformer(C.EMBED_MODEL)
        tax_emb = embedder.encode(display_list, convert_to_tensor=True,
                                  show_progress_bar=False)
        print(f"embedding tier: enabled ({C.EMBED_MODEL})")
    except Exception as e:
        print(f"embedding tier: DISABLED ({type(e).__name__}) — "
              f"widening fuzzy review band instead")
        tax_emb = None

    stats = Counter()
    review_rows, samples = [], []
    pending_embed = []          # (raw, freq, norm, fuzzy_best, fuzzy_score)
    for raw, freq in raw_terms.most_common():
        norm = normalize_raw(raw)
        # Known-vocabulary check FIRST: a term in the taxonomy must never be
        # junked by a blocklist heuristic (e.g. "star-crossed lovers").
        if norm not in alias_map and is_blocked(raw):
            stats["blocklist"] += 1
            if not dry_run:
                conn.execute("INSERT INTO tag_merge_log (raw_term, resolved_slug, method, score)"
                             " VALUES (?,NULL,'blocklist',NULL)", (raw,))
            continue
        if norm in alias_map:                          # exact / existing alias
            stats["alias"] += 1
            slug = alias_map[norm]
            if len(samples) < 50:
                samples.append((raw, slug, "alias", 100.0, freq))
            if not dry_run:
                conn.execute("INSERT INTO tag_merge_log (raw_term, resolved_slug, method, score)"
                             " VALUES (?,?,'alias',100)", (raw, slug))
            continue
        best = process.extractOne(norm, display_list, scorer=fuzz.token_sort_ratio)
        score = best[1] if best else 0
        if best and score >= C.FUZZY_AUTO_ALIAS:       # auto-alias
            slug = display_to_slug[best[0]]
            stats["fuzzy"] += 1
            alias_map[norm] = slug
            if len(samples) < 50:
                samples.append((raw, slug, "fuzzy", score, freq))
            if not dry_run:
                conn.execute("INSERT OR IGNORE INTO taxonomy_alias VALUES (?,?)", (norm, slug))
                conn.execute("INSERT INTO tag_merge_log (raw_term, resolved_slug, method, score)"
                             " VALUES (?,?,'fuzzy',?)", (raw, slug, score))
            continue
        # defer: embedding tier is batch-encoded after this loop (far faster)
        if tax_emb is not None:
            pending_embed.append((raw, freq, norm))
            continue
        if best and 80 <= score < C.FUZZY_AUTO_ALIAS:   # no embeddings: wider fuzzy band
            stats["fuzzy_review"] += 1
            review_rows.append([raw, freq, "fuzzy", best[0],
                                display_to_slug[best[0]], score])
            continue
        stats["proposed"] += 1
        if not dry_run:
            _propose(conn, raw, score)

    # ---- batch embedding tier ------------------------------------------
    if pending_embed and tax_emb is not None:
        from sentence_transformers import util
        print(f"embedding {len(pending_embed):,} unresolved terms (batched)...")
        norms = [p[2] for p in pending_embed]
        emb = embedder.encode(norms, convert_to_tensor=True, batch_size=256,
                              show_progress_bar=False)
        sims = util.cos_sim(emb, tax_emb)          # one matrix op
        best_idx = sims.argmax(dim=1)
        for i, (raw, freq, norm) in enumerate(pending_embed):
            cos = float(sims[i][int(best_idx[i])])
            cand = display_list[int(best_idx[i])]
            if cos >= C.EMBED_SUGGEST:
                stats["embed_suggest"] += 1
                review_rows.append([raw, freq, "embedding", cand,
                                    display_to_slug[cand], round(cos, 3)])
            else:
                stats["proposed"] += 1
                if not dry_run:
                    _propose(conn, raw, round(cos, 3))
    if not dry_run:
        conn.commit()
        with open(C.TAXONOMY_REVIEW_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["raw_term", "frequency", "method", "nearest_display",
                        "nearest_slug", "score"])
            w.writerows(sorted(review_rows, key=lambda r: -r[1]))

    print("\n=== taxonomy census (by kind/status) ===")
    for row in conn.execute("SELECT kind, status, COUNT(*) n FROM taxonomy "
                            "GROUP BY kind, status ORDER BY n DESC"):
        print(f"  {row['kind']:<10} {row['status']:<9} {row['n']:>6}")
    print("\n=== raw vocabulary resolution ===")
    for k, v in stats.most_common():
        print(f"  {k:<15} {v:>6}")
    print(f"\nreview CSV rows: {len(review_rows):,} -> {C.TAXONOMY_REVIEW_CSV.name}")
    print("\n=== 50 sample alias resolutions ===")
    for raw, slug, method, score, freq in samples:
        print(f"  {raw[:38]:<38} -> {slug[:30]:<30} [{method} {score:.0f}] x{freq}")
    conn.close()

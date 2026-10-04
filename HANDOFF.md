# BookRec Enrichment — Handoff

Read this, then run `python enrich.py status` to confirm live numbers (figures
here are point-in-time, 2026-07-24).

## What this project is

Personal book recommendation web app (FastAPI + SQLite, pure-code scorer — no
LLM in the serving path). Scores books against the user's taste via weighted
overlap of **genres (30%) / tropes (30%) / tags (40%)**, plus pacing/spice/focus.
The whole value is **canonical, deduplicated, accurate vocabulary** — *a wrong
tag is worse than a missing one; a duplicate tag silently fragments the signal.*

**Working dir:** `C:\Users\Samantha\BookRec` · **Shell:** PowerShell.
Inline `python -c` breaks on quotes — **write a `.py` file and run it**.
`python` is on PATH. Nothing here is git-tracked (repo root is the home folder),
so **deletes are permanent** — archive, don't delete.

## The user

Sharp, protective of community vocabulary (`ice-queen`, `sapphic`, `masc-femme`,
`cinnamon-roll`). Has repeatedly caught real errors — several times per session.
**Take her challenges seriously and verify with data, not assertion.** When she
flags something, ASK which part is wrong before changing it.
**Key preference:** "how do readers categorise this?" is a legitimate basis for a
tag/trope — don't strip reader-facing categories on textual literalism.

## Current state (2026-07-25)

- **96,797 books** · **8,386 with ≥1 trope** (was 5,818) · concrete tags added to ~2,500 books
- content warnings on 6,282 · active taxonomy **~2,100 terms** · ~6,400 proposed
- **2026-07-25 session** (deterministic genre/tag packs, all `--rollback`-able):
  - `_trope_match.py` — romance/fantasy/sci-fi/horror trope packs (the mystery
    technique generalised). Promoted **2,443 books / 2,940 tropes** (`run_20260725_002452`).
  - mystery_2 (Wikipedia plot summaries): **131 books / 148 tropes** (`run_20260725_002705`).
  - `_tag_match.py` — first TAG pack (tags are 40% of score). Promoted the
    high-precision concrete-noun tags — vampires/ghosts/witches/pirates/mermaids/
    zombies/aliens/space/spies/steampunk/occult/noir/superheroes/supernatural/
    paranormal: **2,348 books / 2,799 tags** (`run_20260725_011014`), plus 95 `spies`
    (`run_20260725_011057`) and 90 `retelling` (`run_20260725_011306`).
  - **HELD, not promoted:** identity tags (lesbian/gay/bisexual/transgender/lgbtq)
    + mythology + gothic → `tag_review_identity_hold.csv`. Blurb-matching can't
    tell "a lesbian novel" from "a book about lesbian history", and the catalog
    mis-shelves gender-studies / lit-crit as fiction (genre `Literary Fiction`).
    ~30-50% nonfiction pollution survived even a strengthened guard. These need
    the LLM pass (Phase 4) or a real fiction/nonfiction classifier. Getting this
    community vocabulary *right* matters more than coverage — do NOT bulk-promote.

## Overnight run 2026-07-25 (unattended, results)

Deterministic pipeline (`_overnight_pipeline.py`) completed; all reversible.
- **Language:** archived **866** clear non-English books (`status='archived_nonenglish'`;
  recommender skips `status LIKE 'archived%'`). Conservative title-based detection
  (non-Latin script + leading non-English article/diacritic). Backup
  `lang_archive_backup_*.json`; rollback `python _lang_archive.py --rollback <f>`.
  **8,553 borderline** → `lang_uncertain.csv` (mostly English proper-noun titles
  langdetect misfired on — kept, not archived).
- **Fiction/non-fiction:** the auto-classifier was TOO aggressive fiction→non-fiction
  (~33% of trope-strips hit real novels), so `_fix_class_phase2.py` **reverted all
  3,024 →non-fiction flips and restored all 346 stripped tropes**, keeping only the
  **801 safe →fiction rescues** (novels mis-shelved as non-fiction; a few harmless
  memoir-as-fiction misses remain). Net: no trope data lost. `class_uncertain.csv`
  (4,289) left for review. **Non-fiction trope-stripping is NOT done** — needs a
  more precise classifier or the external verify pass.
- **Tropes:** added 11 Jones-blog mystery/crime patterns to `_trope_match_mystery.py`
  (red-herring, perfect-crime, twist-ending, criminal-mastermind, corrupt-cop, …);
  promoted **57 books** (`run_*` in enrich promote --list-runs). Coverage 8,386→8,443.
- **Steps 4 & 6 (external verify/backfill) did NOT run:** the environment's network
  was down overnight — Google Books returned HTTP 429, Open Library and Wikipedia
  timed out. `_verify_external.py` (Google Books, capped/resumable) is built and
  ready for when network works. The uncertain CSVs are the review lists you asked for.
- **MoodReads scrape FAILED and corrupted the catalog** — see DO NOT BREAK #7;
  recovered from backup, nothing durable scraped.

## Phase status vs the brief (`D:\Downloads\enrichment-tool-claude-code-brief.md`)

| Phase | State |
|---|---|
| 0 Taxonomy · 1 Clean · 2 Triage · 3 Metadata · 6 Canonicalise · 7 Promote | Done |
| **4 Bulk enrichment** | **BLOCKED — no API key.** The core of the plan |
| 5 Targeted grounding | Partial — Wikipedia fetcher built (5a); 5b needs a model |
| 8 Pilot & evaluation | Not started |

**~52k fiction books are still pending, ~36k of them WITH descriptions.** That's
Phase 4's job; nothing free substitutes for it.

## RUNNING RIGHT NOW

Nothing. `_overnight_trope.py` **finished** 2026-07-24 17:22 (286 new Wikipedia
descriptions; `trope_review_mystery_2.csv` produced and since promoted). No
detached jobs left. The Wikipedia write-lock holder is gone, so DB writes are
unblocked.

## DO NOT BREAK THESE

1. **NEVER run `python sync_db.py --refresh`.** Its `--refresh` blanket-overwrites
   all 96k books from the legacy catalog and reverts Phase 1 + every promotion
   (verified: turns `forced-proximity` into `forcedProximity`). Plain
   `python sync_db.py` (insert-only) is safe.
2. **After ANY `sync_db.py`, run `python enrich.py clean`.** The insert path
   re-introduces raw non-slug terms every time.
3. **Only ONE process may write `bookCatalog.json`** — two concurrent scrapers
   corrupt it. The MoodReads supervisor refuses to start if one is running.
4. **SQLite lock contention is real.** The Wikipedia fetch holds the write lock
   across its commit cycle. Before any DB write (ingest/promote/repair),
   **pause the fetch**, write, then relaunch it. It is resumable.
5. **`reclassify()` genre logic is now ADDITIVE** — catalogue genres come first
   and are never deleted or demoted; tag evidence is appended. Do not revert.
7. **MoodReads catalog write is now ATOMIC (fixed 2026-07-25).** The scraper used
   to rewrite `bookCatalog.json` in place (`open(...,'w')` + `json.dump`), so a
   mid-write crash truncated it — that corrupted the 49 MB catalog overnight
   (recovered from backup; corrupt copy in `archive/bookCatalog.CORRUPT.*`).
   Fixed: `scrape_moodreads.atomic_write_json()` writes a `.tmp` + `os.fsync` +
   `os.replace`, so the live file is always a complete valid JSON. The scrape
   (next chunk **2701–3700**) is safe to run again. DB is never touched by it.
6. **`enrich_inline.clean()` now enforces slug KIND, not just membership**
   (`FIELD_KIND`). All taxonomy kinds share one namespace, so before this fix a
   *subgenre* named `spy-espionage-thriller`/`legal-thriller`/`locked-room-mystery`/
   `heist` sailed into `books.tropes` as if it were a trope. Any new matcher must
   map a field only to slugs of that field's kind — the matchers validate this at
   startup. Do not weaken the check back to bare membership.

## Standard workflows

**MoodReads ingest** (after a scrape completes) — in this order:
```
python sync_db.py            # insert-only
python enrich.py clean       # MANDATORY: fixes raw slugs
python _merge_moodreads.py   # scoped additive merge (+ --rollback <backup>)
python enrich.py clean       # routes new trope-kind terms into tropes column
```

**MoodReads scrape:** `nohup python -u _moodreads_supervisor.py <start> <end> &`
Runs the scraper **in-process** (spawning children broke with 0xC0000142 once the
launching shell ended). Ranges done: 2–2700. Next chunk starts at **2701**.
~86 pages 403-blocked in earlier ranges, retryable.

**Promote a trope review CSV:**
```
python _apply_trope_review.py <review.csv> <tag>     # -> batch + decisions CSV
python -c "import enrich_inline; enrich_inline.ingest('inline_batch_<tag>.json')"
python enrich.py promote --decisions <tag>_trope_decisions.csv
```

## Deterministic extraction (the technique that works) — now generalised

Maps distinctive description phrases to existing taxonomy slugs. **No LLM, zero
cost.** Two tiers: A (~95%, auto-applyable), B (~85%). Genre-gated, fiction-only.
`src='both'` prefers Wikipedia plot summaries over OL blurbs.

- `_trope_match_mystery.py` — the original mystery pack (768 books promoted
  `run_20260723_234459`). **Now emits only valid trope slugs** (the 4 subgenre
  leaks remapped/dropped — see DO NOT BREAK #6).
- **`_trope_match.py`** — romance/fantasy/sci-fi/horror trope packs. `python
  _trope_match.py all --both`. Validates every slug is an active **trope** at
  startup; picks the dominant slug where the taxonomy has near-dupes.
- **`_tag_match.py`** — the TAG pack (tags = 40% of score). Chunked + streaming
  (`chunk=2000`) so it stays cheap on a slow laptop; `NONFICTION_SIGNAL` skips
  mis-shelved academic books. `_apply_tag_review.py` is the tags analogue of
  `_apply_trope_review.py`.
- `_audit_trope_csv.py <csv> <N> [slugs…]` — samples matches in context; the
  precision gate. **Run it before every promote** (it caught Robyn Carr's *Virgin
  River* series matching `virgin-heroine`, a Poe anthology matching `professor`,
  and gender-studies texts matching `lesbian`).

Shared plumbing in `_trope_match.clean_desc()` strips series-index, anthology,
comp-title ("for fans of…") and author-bio boilerplate — the #1 false-positive
source. It is guarded by cheap literal pre-checks (was ~20ms/book, now ~2.5ms).

Limits: only concepts with a lexical fingerprint are detectable. Identity tags
(`lesbian`/`sapphic`/…) and abstract "vibe" tags CANNOT be done reliably this way
— the blurb rarely distinguishes fiction from books *about* the topic. Leave
those to the LLM pass.

## Wikipedia fetcher (`_wiki_fetch.py`)

Searches MediaWiki, verifies by **author SURNAME** (first names caused
`Under Pressure` to match *Under the Dome*), rejects disambiguation pages, and
fuzzy-guards the title. Records misses as `source='wikipedia_miss'` so they are
never retried — **without that marker a chunked loop spins forever** (cost 9
hours once). Yield is low (~15%) because these books are mostly obscure indie.

## Awaiting the user's review

- `tag_review_identity_hold.csv` — identity/mythology/gothic tags held back
  (nonfiction pollution; needs the LLM pass, NOT bulk promotion — see Current state)
- `mystery_reclass_review.csv` — 92 borderline non-fiction cases
- ~382 MoodReads terms parked `proposed` (`swoony`, `melancholic`…)
- ~6,400 proposed taxonomy terms below the frequency-3 noise floor
- Taxonomy gap noticed: there is a `witch-romance` trope but no generic `witches`
  *trope* (only the tag) and no generic espionage trope — spy books now use the
  `spies` tag. Consider adding trope-level slugs if the LLM pass wants them.

## Recent fixes worth knowing

- **Genre corruption (fixed 2026-07-24):** old `reclassify()` emitted only
  `[primary, subgenre]`, destroying other genres — 1,653 books had their identity
  replaced (Bloodstone: `Fantasy` → `Mystery, crime`). Repaired 1,700 disjoint
  books + restored the primary genre on 3,821 more (Gerald's Game → Horror, Dark
  Tower → Fantasy). Backups: `genre_repair_backup_*`, `primary_genre_backup_*`.
  **Deliberately did NOT restore all lost genres** — the catalogue arrays are
  noisy shelf aggregations (Six of Crows listed as Fantasy+Sci-Fi+Thriller+
  Mystery+Romance); restoring everything would flood the signal.
- **Ambiguous re-triage:** 4,507 of 8,996 reclassified. Word-boundary matching is
  essential — `fiction` matched inside `nonfiction`, `roman` inside `romance`.
- **`enrich_inline` guard:** a model `known=false` can no longer wipe a book that
  already carries original catalogue vocab (this had stranded 5 lesfic titles).
- **`enrich_canonicalise.py`** (Phase 6) — `review` / `--apply <csv>`; taxonomy
  grew 564 → ~2,100 via per-genre review CSVs.

## Folder layout

Root = live code + files pinned by `config.py`. `scrapers/` (all fetchers, with a
sys.path shim — **run them from the repo root**), `batches/`, `review/`,
`backups/`, `logs/`, `archive/scripts/`.
**Do not move:** `book_rec.db`, `taxonomy.md`, `taxonomy_decisions.csv`,
`vocab_decisions_final.csv`, `clean_log.jsonl`, `bookCatalog*.json`,
`priority_slice.json`, scraper progress JSON.

## Reversibility

Every promote is `--rollback`-able (`python enrich.py promote --list-runs`).
Timestamped backups exist for every direct DB edit. `_merge_moodreads.py
--rollback <file>`.

## Useful

- `python enrich.py status` · `python _grounded_batch.py 0 0`
- `python _trope_match_mystery.py --out X.csv --both`
- `python _wiki_fetch.py --test`

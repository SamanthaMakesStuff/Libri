"""Overnight orchestrator (detached).

Phase 1 - finish the Wikipedia description fetch over all no-description
          mystery/crime/thriller books (resumable: skips ones already cached).
Phase 2 - re-run the deterministic trope matcher, now preferring the richer
          Wikipedia plot summaries, over books that are STILL trope-less
          (the 768 already promoted are auto-excluded because they now have
          tropes). Writes trope_review_mystery_2.csv for morning review.

Nothing is auto-promoted here - the new matches are left for the user to review,
exactly as they asked. Sequential phases, so no DB lock contention with itself;
the only other live writer (moodreads) touches the catalog JSON, not the DB.

Runs to completion unattended. Logs to logs/overnight_trope.log.
"""
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "overnight_trope.log"


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def phase1_wikipedia():
    import _wiki_fetch as wf
    found, scanned = wf.fetch_all(log=log)
    return found


def phase2_rematch():
    import _trope_match_mystery as tm
    books, assigns = tm.run(out="trope_review_mystery_2.csv", src="both")
    log(f"phase 2: re-match complete - {books} books, {assigns} trope assignments "
        f"-> trope_review_mystery_2.csv")
    return books, assigns


log("overnight orchestrator started")
try:
    found = phase1_wikipedia()
    log(f"phase 1 done: {found} new Wikipedia descriptions this run")
    phase2_rematch()
    log("overnight orchestrator finished OK")
except Exception:
    log("FAILED:\n" + traceback.format_exc())

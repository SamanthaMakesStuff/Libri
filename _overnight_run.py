"""Overnight run — waits until 22:00 local, then executes, unattended.

Order is by value-if-interrupted (the fast local win first, network work after):
  1. Tag-pack EXPANSION promote  (local, fast) — apply the audited
     tag_review_expansion.csv (18.6k tags / 13k books), ingest (kind-validated),
     promote, clean. Definitely completes.
  2. Wikipedia DESCRIPTION BACKFILL (network, capped) — fetch descriptions for
     description-less priority-genre fiction so they become enrichable.
  3. RE-MATCH (local, fast) — re-run the trope + tag matchers so the freshly
     fetched descriptions actually produce tropes/tags, then promote.
  4. Wikipedia VERIFICATION (network, capped) — resolve class-uncertain books
     from authoritative categories; backfill descriptions as it goes.

Each phase is a subprocess: a failure is logged and the next phase still runs.
Everything is backed up and reversible. The MoodReads scrape is NOT started here.
"""
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "overnight_run.log"
PY = sys.executable
START_HHMM = (22, 0)


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait_until_start():
    now = datetime.now()
    target = now.replace(hour=START_HHMM[0], minute=START_HHMM[1], second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    secs = (target - now).total_seconds()
    log(f"waiting {secs/3600:.2f}h until {target:%Y-%m-%d %H:%M} to start")
    # sleep in chunks so the wait is visible/interruptible
    while datetime.now() < target:
        time.sleep(min(300, (target - datetime.now()).total_seconds()))


def run(cmd, name):
    log(f"START {name}: {' '.join(cmd)}")
    t0 = time.time()
    try:
        r = subprocess.run([PY] + cmd, cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        tail = "\n".join((r.stdout or "").splitlines()[-12:])
        log(f"  {name} tail:\n{tail}")
        if r.returncode != 0:
            log(f"  {name} STDERR:\n{(r.stderr or '')[-1200:]}")
        log(f"END {name} rc={r.returncode} in {time.time()-t0:.0f}s")
        return r.returncode == 0
    except Exception as e:
        log(f"END {name} EXCEPTION {e!r}")
        return False


def promote_csv(review_csv, tag, apply_script, ingest_batch):
    """apply -> ingest (kind-validated) -> promote -> clean, for a review CSV."""
    if not run([apply_script, review_csv, tag], f"{tag}-apply"):
        return
    run(["-c", f"import enrich_inline; enrich_inline.ingest('{ingest_batch}')"], f"{tag}-ingest")
    run(["enrich.py", "promote", "--decisions", f"{tag}_" +
         ("tag" if "tag" in apply_script else "trope") + "_decisions.csv"], f"{tag}-promote")


log("=" * 60)
log("overnight run scheduled")
wait_until_start()
log("overnight run START")

# 1. tag expansion (pre-generated + audited today)
promote_csv("tag_review_expansion.csv", "tagexp", "_apply_tag_review.py",
            "inline_batch_tagexp.json")
run(["enrich.py", "clean"], "clean-after-tags")

# 2. description backfill (network, capped)
run(["_wiki_backfill.py", "--cap", "4000"], "wiki-backfill")

# 3. re-match on the newly described books, then promote
run(["_trope_match_mystery.py", "--out", "trope_review_rematch_mystery.csv", "--both"], "rematch-mystery")
promote_csv("trope_review_rematch_mystery.csv", "rmys", "_apply_trope_review.py",
            "inline_batch_rmys.json")
run(["_trope_match.py", "all", "--both"], "rematch-genre")
# union the genre CSVs and promote
run(["_union_reviews.py"], "rematch-union")
promote_csv("trope_review_all.csv", "rgen", "_apply_trope_review.py",
            "inline_batch_rgen.json")
run(["_tag_match.py", "--out", "tag_review_rematch.csv", "--both"], "rematch-tags")
promote_csv("tag_review_rematch.csv", "rtag", "_apply_tag_review.py",
            "inline_batch_rtag.json")
run(["enrich.py", "clean"], "clean-after-rematch")

# 4. Wikipedia verification of class-uncertain (network, capped)
run(["_verify_wiki.py", "--cap", "3000"], "wiki-verify")

log("overnight run DONE")

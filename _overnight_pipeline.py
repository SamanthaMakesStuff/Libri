"""Overnight deterministic pipeline (phases 1-3). Runs unattended; each phase is
a subprocess so a failure is logged and the next phase still runs. Everything is
backed up and reversible. The MoodReads scrape runs concurrently in its own
process (it writes the catalog JSON, not the DB, so no lock contention).

  Phase 1  _lang_archive.py    archive confident non-English (title-based)
  Phase 2  _class_mark.py      mark fiction/non-fiction; strip confirmed-NF tropes
  Phase 3  mystery/crime/thriller trope generation from existing descriptions,
           audited-and-promoted (union of the deterministic matchers)

Phase 4 (external verification of the uncertain logs) is a separate capped
process, _verify_external.py, because it is rate-limited and best-effort.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "overnight_pipeline.log"
PY = sys.executable


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, name):
    log(f"START {name}: {' '.join(cmd)}")
    t0 = time.time()
    try:
        r = subprocess.run([PY] + cmd, cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        tail = "\n".join((r.stdout or "").splitlines()[-15:])
        log(f"  {name} stdout tail:\n{tail}")
        if r.returncode != 0:
            log(f"  {name} STDERR:\n{(r.stderr or '')[-1500:]}")
        log(f"END {name} rc={r.returncode} in {time.time()-t0:.0f}s")
        return r.returncode == 0
    except Exception as e:
        log(f"END {name} EXCEPTION {e!r}")
        return False


def phase3_tropes():
    """Deterministic mystery/crime/thriller tropes -> audited auto-promote."""
    ok = run(["_trope_match_mystery.py", "--out", "trope_review_overnight.csv", "--both"],
             "phase3-match")
    if not ok:
        return
    # build batch + decisions, ingest (kind-validated), promote, clean
    run(["_apply_trope_review.py", "trope_review_overnight.csv", "overnight"], "phase3-apply")
    run(["-c", "import enrich_inline; enrich_inline.ingest('inline_batch_overnight.json')"],
        "phase3-ingest")
    run(["enrich.py", "promote", "--decisions", "overnight_trope_decisions.csv"], "phase3-promote")
    run(["enrich.py", "clean"], "phase3-clean")


log("=" * 60)
log("overnight pipeline START")
run(["_lang_archive.py"], "phase1-lang")
run(["_class_mark.py"], "phase2-class")
phase3_tropes()
log("overnight pipeline deterministic phases DONE")

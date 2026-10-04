#!/usr/bin/env python3
"""
Continuous Hardcover enrichment driver: repeatedly enrich a batch then sync,
until no books are left to process. Resumable (hc_enrich checkpoints), safe to
stop/restart. Runs one enricher at a time so bookCatalog.json is never contended.

Run detached:
  python run_hardcover_enrich.py            # default 4000/batch
Progress -> hardcover_driver.log
"""
import os as _os, sys as _sys  # noqa: E402  (added by _tidy.py)
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # sibling scrapers

import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent.parent   # data files live at the repo root
LOG = HERE / "hardcover_driver.log"
BATCH = 4000


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(args):
    r = subprocess.run([sys.executable, "-u", *args], cwd=HERE,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.stdout or ""


DISCOVER_FLOOR = 25   # add new Hardcover books read by >= this many users


def main():
    log("=== hardcover enrichment driver started ===")

    # Phase 1: enrich every existing catalog book lacking tropes/tags.
    batch_num = 0
    while True:
        batch_num += 1
        log(f"[enrich] batch {batch_num}: up to {BATCH}...")
        out = run(["hc_enrich.py", "--limit", str(BATCH)])
        m = re.search(r"Processed (\d+), enriched (\d+)", out)
        processed = int(m.group(1)) if m else 0
        enriched = int(m.group(2)) if m else 0
        log(f"[enrich] batch {batch_num}: processed {processed}, enriched {enriched}")
        if processed == 0:
            log("[enrich] complete — nothing left to enrich.")
            break
        sync = run(["sync_db.py", "--refresh"])
        log("[enrich] synced.\n" + "\n".join(sync.strip().splitlines()[-3:]))
        time.sleep(2)

    # Phase 2: add popular Hardcover books not already in the catalog.
    log(f"[discover] adding new Hardcover books (users_count >= {DISCOVER_FLOOR})...")
    out = run(["hc_discover.py", "--floor", str(DISCOVER_FLOOR)])
    log("[discover] " + (out.strip().splitlines()[-1] if out.strip() else "no output"))
    sync = run(["sync_db.py", "--refresh"])
    log("[discover] synced.\n" + "\n".join(sync.strip().splitlines()[-3:]))

    log("=== hardcover driver finished (enrich + discover) ===")


if __name__ == "__main__":
    main()

"""Keep the MoodReads scrape alive overnight, optionally starting at a set time.

The scraper dies early for boring reasons: a sustained 403 wall, a network
blip, an unhandled catalog record. It is fully resumable (it skips ids already
in moodreads_progress.json), so the fix is simply to restart it.

Policy:
  * optionally wait until --at HH:MM before the first cycle
  * if the scraper exits, wait --cooldown (default 1h) and restart
  * give up when the run stops making progress, so we don't hammer the site
    all night for nothing, or when the time/restart budget is spent

Only ONE scraper may run at a time - two concurrent processes would both write
bookCatalog.json and corrupt it. This supervisor refuses to start if one is
already running.

Usage:
  nohup python -u _moodreads_supervisor.py 1301 2000 --at 22:00 &
  nohup python -u _moodreads_supervisor.py 1301 2000 &          # start now
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent

ap = argparse.ArgumentParser()
ap.add_argument("start", type=int)
ap.add_argument("end", type=int)
ap.add_argument("--at", help="wait until this HH:MM local time before starting")
ap.add_argument("--delay", default="3", help="seconds between page fetches")
ap.add_argument("--cooldown", type=int, default=3600, help="seconds between restarts")
ap.add_argument("--max-restarts", type=int, default=12)
ap.add_argument("--max-hours", type=float, default=12.0)
ap.add_argument("--max-no-progress", type=int, default=3)
a = ap.parse_args()

PROG = ROOT / "moodreads_progress.json"
LOG = ROOT / "logs" / "moodreads_supervisor.log"
SCRAPE_LOG = ROOT / "logs" / f"moodreads_{a.start}_{a.end}.log"


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def done_in_range():
    try:
        return len([i for i in json.loads(PROG.read_text())
                    if a.start <= i <= a.end])
    except Exception:
        return 0


def scraper_already_running():
    """Two writers to bookCatalog.json would corrupt it - refuse to be the second."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'scrape_moodreads' } | "
             "Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=60)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:
        return False


if a.at:
    hh, mm = (int(x) for x in a.at.split(":"))
    target = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target < datetime.now():
        target += timedelta(days=1)
    wait = (target - datetime.now()).total_seconds()
    log(f"scheduled: sleeping {wait/3600:.1f}h until {target:%Y-%m-%d %H:%M}")
    time.sleep(wait)

if scraper_already_running():
    log("a scrape_moodreads process is ALREADY RUNNING - refusing to start a "
        "second writer (would corrupt bookCatalog.json). Exiting.")
    sys.exit(1)

started = time.time()
restarts = no_progress = 0
total = a.end - a.start + 1
log(f"supervisor up: range {a.start}-{a.end}, delay {a.delay}s, "
    f"cooldown {a.cooldown}s, max {a.max_restarts} restarts / {a.max_hours}h")

while True:
    before = done_in_range()
    log(f"cycle {restarts + 1}: starting scraper ({before} of {total} ids done)")
    # Run the scraper IN-PROCESS rather than spawning a child.
    # Spawning broke once the launching shell session ended: every child died
    # instantly with 0xC0000142 (DLL init failure) and produced no output, so
    # the supervisor burned cycles doing nothing. Importing sidesteps that
    # entire class of Windows failure.
    rc = 0
    try:
        import runpy
        old_argv, old_cwd = sys.argv, os.getcwd()
        os.chdir(str(ROOT))
        sys.argv = ["scrape_moodreads.py", str(a.start), str(a.end),
                    "--delay", a.delay]
        with open(SCRAPE_LOG, "a", encoding="utf-8", buffering=1) as out:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = out
            try:
                runpy.run_path(str(ROOT / "scrapers" / "scrape_moodreads.py"),
                               run_name="__main__")
            except SystemExit as e:
                rc = e.code or 0
            finally:
                sys.stdout, sys.stderr = old_out, old_err
        sys.argv, _ = old_argv, os.chdir(old_cwd)
    except Exception as e:
        rc = -1
        log(f"  scraper raised: {type(e).__name__}: {e}")

    after = done_in_range()
    gained = after - before
    log(f"  scraper exited rc={rc}; +{gained} ids this cycle ({after}/{total})")

    if after >= total:
        log("range fully covered - done."); break
    no_progress = no_progress + 1 if gained == 0 else 0
    if no_progress >= a.max_no_progress:
        log(f"no progress in {a.max_no_progress} consecutive cycles "
            f"(likely a hard 403 wall) - stopping."); break
    restarts += 1
    if restarts >= a.max_restarts:
        log("restart budget spent - stopping."); break
    if (time.time() - started) / 3600 >= a.max_hours:
        log("time budget spent - stopping."); break
    log(f"  cooling off {a.cooldown // 60} min before restart")
    time.sleep(a.cooldown)

log("supervisor finished.")

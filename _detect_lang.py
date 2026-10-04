"""Detect each book's language and cache the result to lang_detect.json.

Non-destructive. Prefers the description (most reliable signal); falls back to
title+author. Non-Latin scripts are flagged directly; Latin-script text goes to
langdetect. Marks low-signal cases 'uncertain' rather than guessing, so the
removal step can leave those alone.

  python _detect_lang.py            # detect + cache + print tally
"""
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import config as C

from langdetect import detect_langs, DetectorFactory
DetectorFactory.seed = 0        # deterministic

CACHE = "lang_detect.json"

# Disk-backed memo of langdetect(title) so repeated passes (dry/apply/rollback
# re-checks) never pay the detection cost twice. Keyed by the exact title.
import atexit
import os
_LD_CACHE = "langdetect_cache.json"
try:
    _ld = json.load(open(_LD_CACHE, encoding="utf-8")) if os.path.exists(_LD_CACHE) else {}
except Exception:
    _ld = {}
_ld_dirty = False


def _cached_detect(title):
    global _ld_dirty
    if title in _ld:
        return _ld[title]
    try:
        res = [(l.lang, l.prob) for l in detect_langs(title)]
    except Exception:
        res = []
    _ld[title] = res
    _ld_dirty = True
    return res


@atexit.register
def _flush_cache():
    if _ld_dirty:
        try:
            json.dump(_ld, open(_LD_CACHE, "w", encoding="utf-8"))
        except Exception:
            pass

# Unicode script blocks that are unambiguously not English.
NONLATIN = re.compile(
    r"[Ѐ-ӿ"      # Cyrillic
    r"Ͱ-Ͽ"       # Greek
    r"֐-׿"       # Hebrew
    r"؀-ۿݐ-ݿ"  # Arabic
    r"ऀ-ॿ"       # Devanagari
    r"ঀ-৿"       # Bengali
    r"਀-ൿ"       # other Indic (Gurmukhi..Malayalam incl. Kannada)
    r"฀-๿"       # Thai
    r"ᄀ-ᇿ가-힯"  # Hangul
    r"぀-ヿ一-鿿㐀-䶿"  # Kana + CJK
    r"]")


def latin_ratio(s):
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return 1.0
    latin = sum(1 for ch in letters
                if "LATIN" in unicodedata.name(ch, ""))
    return latin / len(letters)


def classify(title, author, desc):
    """Return (lang, english_bool_or_None, basis).

    Detect on the TITLE — it is written in the book's own language. The
    description is NOT a reliable signal: the catalog pairs English descriptions
    with foreign books and foreign descriptions with English books, so using it
    both misses and false-positives. Description is used only as a same-direction
    tiebreaker when the title is too short to judge.
    """
    title = (title or "").strip()
    desc = (desc or "").strip()
    if NONLATIN.search(title) and latin_ratio(title) < 0.6:
        return ("nonlatin", False, "script")

    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", title)
    if len(letters) < 8 or len(title.split()) < 2:
        # Title too short/ambiguous for reliable detection -> leave uncertain.
        return ("?", None, "title-short")
    langs = _cached_detect(title)                # list of (lang, prob)
    if not langs:
        return ("?", None, "detect-failed")
    top_lang, top_prob = langs[0]
    if top_lang == "en":
        return ("en", True, "title")
    # Non-English title guess. Titles are short, so require strong confidence and
    # confirm English isn't a close runner-up before calling it non-English.
    en_prob = max((p for l, p in langs if l == "en"), default=0.0)
    if top_prob >= 0.9995 and en_prob < 0.02:
        return (top_lang, False, "title")
    return (top_lang, None, "title-lowconf")     # not confident -> uncertain


def main():
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    ids = [r[0] for r in conn.execute("SELECT id FROM books")]
    total = len(ids)
    print(f"detecting language for {total:,} books", flush=True)

    out = {}
    tally = Counter()
    CH = 2000
    for i in range(0, total, CH):
        batch = ids[i:i + CH]
        ph = ",".join("?" * len(batch))
        rows = conn.execute(
            f"""SELECT b.id, b.title, b.author,
                    COALESCE(w.description,o.description) AS descr
                FROM books b
                LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
                LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
                WHERE b.id IN ({ph})""", batch).fetchall()
        for r in rows:
            lang, eng, basis = classify(r["title"], r["author"], r["descr"])
            out[r["id"]] = {"lang": lang, "english": eng, "basis": basis}
            key = "english" if eng is True else ("non-english" if eng is False else "uncertain")
            tally[key] += 1
            tally[f"lang:{lang}"] += 1
        print(f"  ...{min(i+CH,total):,}/{total:,}", flush=True)
    conn.close()

    json.dump(out, open(CACHE, "w", encoding="utf-8"))
    print("\nTALLY:")
    for k in ("english", "non-english", "uncertain"):
        print(f"  {k:12} {tally[k]:,}")
    print("\ntop non-English languages:")
    for k, n in tally.most_common():
        if k.startswith("lang:") and k not in ("lang:en",):
            print(f"  {k[5:]:8} {n:,}")
    print(f"\n-> {CACHE}")


if __name__ == "__main__":
    main()

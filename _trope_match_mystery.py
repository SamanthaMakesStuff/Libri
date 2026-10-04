"""Deterministic trope extraction for mystery/crime/thriller, from descriptions.

Maps distinctive phrases -> existing taxonomy trope slugs. Patterns are tuned
for PRECISION (a wrong trope is worse than a missing one): multi-word or
context-bound phrases, never bare generic words like 'murder' or 'detective'.

Two confidence tiers, from the prototype precision check:
  A (>=90% in sampling)  - safe to auto-apply
  B (~70-85%)            - route to human review

Runs on trope-less mystery fiction WITH a description. Emits a review CSV
showing, per book, each matched trope + the phrase in context + the description,
so precision can be judged directly before anything is written.

  python _trope_match_mystery.py            # writes trope_review_mystery.csv
  python _trope_match_mystery.py --apply trope_review_mystery.csv   # later
"""
import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

TIER_A = {
 "serial-killer": r"serial killer|serial murder|string of (brutal )?murders|series of (brutal )?murders|a killer who has (killed|murdered)|the killer'?s (next|latest) victim",
 # `legal-thriller` is a SUBGENRE, not a trope; the equivalent active trope is
 # court-case-as-backbone-of-plot. (The subgenre slug leaked into books.tropes
 # before enrich_inline enforced kind — see _apply_trope_review / enrich_inline.)
 "court-case-as-backbone-of-plot": r"district attorney|defen[cs]e (attorney|lawyer|counsel)|courtroom (drama|thriller|scene|battle)|federal prosecutor|on trial for|legal thriller|the defendant",
 "kidnapping": r"\bkidnap(s|ped|ping|per)?\b|\babduct(s|ed|ion)\b|held (hostage|for ransom)",
 "unsolvable-cold-case-reopened": r"cold case|unsolved (murder|case|crime|disappearance|killing)|decades[- ]old (murder|case|mystery|crime)|reopen(s|ed|ing)? the (case|investigation)|never (solved|caught)",
 "race-against-time": r"race against (time|the clock)|before it'?s too late|running out of time|ticking clock|before (the killer|he|she) (strikes|kills) again",
 "femme-fatale": r"femme fatale",
 "cat-and-mouse-pursuit": r"cat[- ]and[- ]mouse",
 # `locked-room-mystery` is a subgenre; the active trope for the same reader
 # family (impossible crime / isolated suspect pool) is closed-circle-of-suspects.
 "closed-circle-of-suspects": r"locked[- ]room|closed circle|sealed room",
 "witness-protection": r"witness protection",
 # `heist` is a subgenre with no accurate generic trope, so it is no longer
 # emitted here (it was silently landing in books.tropes as a non-trope).
 "amnesia": r"\bamnesia\b|no memory of|can'?t remember (what|who|how|anything)|lost (her|his) memory|wakes up.{0,30}(no memory|can'?t remember)",
 "amateur-sleuth-stumbling-into-a-case": r"amateur (detective|sleuth)|reluctant (detective|investigator|sleuth)|takes it upon (herself|himself) to (solve|investigate)",
}
TIER_B = {
 "missing-person": r"goes missing|went missing|missing person|(girl|boy|woman|man|child|daughter|son|wife|husband|sister|brother|student|teenager|friend) (who )?(has )?(disappear|vanish)|disappearance of (a|her|his|the|his|their)|vanished without a trace",
 "revenge-plot": r"\brevenge\b|\bavenge\b|vengeance|out for blood",
 "blackmail": r"blackmail",
 # `spy-espionage-thriller` removed: it is a subgenre, and the only espionage
 # trope (espionage-double-agent) is too specific to apply to every spy novel.
 # Spy thrillers are captured by the `spies` TAG in _tag_match.py instead.
 "conspiracy": r"a (vast|sinister|government|shadowy|deadly) conspiracy|conspiracy to (kill|murder|assassinate|cover)|uncover(s|ed|ing)? a conspiracy|government cover[- ]up|massive cover[- ]up",
 "framed-protagonist": r"framed for|wrongly (accused|convicted)|accused of a (murder|crime).{0,25}(didn'?t|did not) commit|set up for (a|the) (murder|crime)",
 "evil-twin-doppelganger": r"evil twin|doppelg[aä]nger|identical twin.{0,45}(murder|kill|dead|missing|disappear)",
 # --- added from the Jones mystery/crime/thriller trope list (multiword,
 #     high-precision fingerprints mapped to existing active trope slugs) ---
 "red-herring": r"red herring",
 "perfect-crime": r"perfect (crime|murder)|the perfect (crime|murder)",
 "twist-ending": r"shocking twist|twist ending|the big reveal|a (final|shocking|stunning|jaw-dropping) twist|nothing is as it seems|nothing is what it seems",
 "criminal-mastermind": r"criminal mastermind|master criminal",
 "killer-hiding-in-plain-sight": r"hiding in plain sight|(killer|murderer) (is|was|walks) among (them|us)|closer to home than",
 "detective-who-becomes-a-suspect": r"(detective|investigator|sleuth|cop|inspector|agent).{0,50}(becomes?|is|now|turned|prime|the) .{0,10}suspect|(accused|suspect|framed).{0,45}(the (crime|murder) (she|he) (was|is) investigating|(her|his) own (case|investigation))",
 "corrupt-cop-official": r"corrupt (cop|police|detective|officer|official|politician|senator|mayor|judge|force)",
 "wrong-person-convicted": r"wrongly (convicted|imprisoned|jailed)|wrong (man|woman|person) (convicted|imprisoned|behind bars|in prison)|\bexonerat(e|ed|ion)",
 "it-was-suicide-or-was-it": r"ruled a suicide|apparent suicide|was it (suicide|really an accident|an accident)|suicide.{0,15}(or was it|but .{0,10}murder)",
 "buddy-cop-mismatched-partners": r"mismatched (partners|detectives|cops)|buddy[- ]cop|unlikely (partners|duo|pair).{0,30}(cop|detective|police|investigat)",
 "stalker-unhinged-ex-as-red-herring-or-real-threat": r"\bstalker\b|obsessive ex|unhinged ex|being stalked",
}
ALL = {**{k: (v, "A") for k, v in TIER_A.items()},
       **{k: (v, "B") for k, v in TIER_B.items()}}
COMP = {k: (re.compile(v, re.I), tier) for k, (v, tier) in ALL.items()}


def context(desc, m, pad=40):
    s = max(0, m.start() - pad)
    return "..." + " ".join(desc[s:m.end() + pad].split()) + "..."


def match(desc):
    out = []
    for slug, (rx, tier) in COMP.items():
        m = rx.search(desc)
        if m:
            out.append((slug, tier, m.group(0), context(desc, m)))
    return out


def run(out="trope_review_mystery.csv", src="ol"):
    """src: 'ol' = Open Library descriptions only (original run);
            'both' = prefer Wikipedia plot summary, fall back to OL (re-run)."""
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    GEN = ("(b.genres LIKE '%Mystery%' OR b.genres LIKE '%crime%' "
           "OR b.genres LIKE '%Thriller%' OR b.genres LIKE '%mystery%')")
    # Wikipedia plot summaries are richer than blurbs, so prefer them.
    desc_expr = ("COALESCE(w.description, o.description)" if src == "both"
                 else "o.description")
    rows = conn.execute(f"""SELECT b.id, b.title, b.author, {desc_expr} AS description
        FROM books b JOIN enrichment_state s ON s.book_id=b.id
        LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
        LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
        WHERE {GEN} AND s.book_class='fiction'
          AND (b.tropes IS NULL OR b.tropes='[]')
          AND {desc_expr} IS NOT NULL AND TRIM({desc_expr})!=''""").fetchall()

    out_rows, freq, tier_books = [], Counter(), Counter()
    for r in rows:
        ms = match(r["description"])
        if not ms:
            continue
        tiers = {t for _, t, _, _ in ms}
        tier_books["A+B" if tiers == {"A", "B"} else next(iter(tiers))] += 1
        for slug, tier, phrase, ctx in ms:
            freq[slug] += 1
            out_rows.append({"decision(keep/blank)": "", "tier": tier, "trope": slug,
                             "matched_phrase": phrase, "book_id": r["id"],
                             "title": r["title"], "author": r["author"] or "",
                             "context": ctx})
    conn.close()

    out_rows.sort(key=lambda x: (x["tier"], x["trope"]))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    books_matched = len({r["book_id"] for r in out_rows})
    print(f"scanned {len(rows):,} trope-less mystery fiction with descriptions ({src})")
    print(f"books with >=1 match: {books_matched:,} ({books_matched/max(1,len(rows))*100:.0f}%)")
    print(f"total trope assignments: {len(out_rows):,} | by tier (books): {dict(tier_books)}")
    for slug, n in freq.most_common():
        print(f"   [{ALL[slug][1]}] {n:>4}  {slug}")
    print(f"-> {out}")
    return books_matched, len(out_rows)


if __name__ == "__main__":
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "trope_review_mystery.csv"
    src = "both" if "--both" in sys.argv else "ol"
    run(out=out, src=src)

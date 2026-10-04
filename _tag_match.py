"""Deterministic TAG extraction from descriptions — the sibling of
_trope_match.py. Tags are 40% of the recommendation score (tropes are 30%), and
~22k fiction books have a description but no tags at all, so this is the highest-
leverage deterministic pass available without an API key.

Same discipline as the trope packs:
  * every target is validated as an ACTIVE **tag** at startup (a subgenre or
    trope slug with the same name is rejected — e.g. `dark-academia` is a
    subgenre, `dragons`/`royalty` are tropes, so they are NOT here);
  * patterns are distinctive, never bare high-frequency words;
  * the same clean_desc() strips series-index / anthology / comp-title noise;
  * two tiers, A auto-applyable and B for a look;
  * a book is only offered tags it does not already carry.

Identity tags (`sapphic`, `lesbian`, `lgbtq`, `bisexual`, `transgender`, `gay`)
are handled conservatively and on explicit signal only — this vocabulary matters
to the user and a wrong identity tag is worse than a missing one. Whenever a
specific identity fires, `lgbtq` is added as an umbrella (it is how the catalog
already pairs them: lesbian books carry both).

  python _tag_match.py --out tag_review.csv --both
"""
import csv
import json
import re
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C
from _trope_match import clean_desc, context   # reuse the boilerplate stripper

# Tier A — distinctive fingerprints, safe to auto-apply.
TAG_A = {
 # --- creatures / paranormal -------------------------------------------
 "vampires": r"\bvampires?\b|\bvampiric\b",
 "ghosts": r"\bghost(s|ly)?\b|\bhaunting\b|\bpoltergeist\b|\bspectral\b|\bapparition\b",
 "witches": r"\bwitch(es|craft)?\b|\bcoven\b|\bsorceress\b|\bwitchy\b",
 "pirates": r"\bpirates?\b|\bbuccaneer\b|\bprivateer\b",
 "mermaids": r"\bmermaids?\b|\bmerfolk\b|\bmerman\b|\bsiren of the sea\b",
 "zombies": r"\bzombies?\b|\bundead\b|\bthe walking dead\b|reanimated corpse",
 "aliens": r"\baliens?\b|\bextraterrestrial\b|\bmartians?\b",
 "superheroes": r"\bsuperheroe?s?\b|\bsuper[- ]?powered\b|\bmasked vigilante\b",
 # --- setting / subgenre-vibe ------------------------------------------
 "space": r"\bouter space\b|\bdeep space\b|\bspace ?ship\b|\bspace station\b|\bspacecraft\b|\bspacefaring\b|\bspace travel\b|\bspace colony\b|\binterstellar\b|\bstarship\b",
 "steampunk": r"\bsteampunk\b|\bclockwork (city|empire|world|automaton)\b",
 "gothic": r"\bgothic\b",
 "occult": r"\boccult\b|\bblack magic\b|\bnecromanc(y|er)\b|\bsummoning ritual\b",
 "mythology": r"\bmytholog(y|ical|ies)\b|\bgreek myth|\bnorse myth|\broman myth|\bpantheon of\b|\bthe gods of\b",
 "noir": r"\bnoir\b|\bhard[- ]boiled\b",
 # espionage has no accurate generic *trope* (only espionage-double-agent, which
 # is too specific), so spy thrillers are tagged here instead.
 "spies": r"\bespionage\b|\bsecret agent\b|\bdouble agent\b|\bspy (ring|network|thriller|novel)\b|\bintelligence (officer|operative|agent)\b|\bundercover (agent|operative)\b|\b(CIA|MI5|MI6|KGB|MOSSAD) (agent|officer|operative|spy)\b",
 "steampunk-airships": None,   # placeholder guard, removed below
 # --- creatures / fantasy (added 2026-08 expansion) --------------------
 "werewolves": r"\bwerewol(f|ves)\b|\blycan(thropes?)?\b|\bwolf shifter\b",
 "robots": r"\brobots?\b|\bandroids?\b|\bautomatons?\b",
 "artificial-intelligence": r"\bartificial intelligence\b|\bsentient (AI|A\.I\.|machine|computer|program)\b|\bself[- ]aware (AI|machine|computer)\b|\brogue AI\b",
 "demons": r"\bdemons?\b|\bdemonic\b",
 "fairies": r"\bfairies\b|\bfaeries?\b|\bpixies?\b|\bfae folk\b",
 "assassins": r"\bassassins?\b|\bassassination\b|\bhit ?man\b|\bcontract killer\b|\bhired killer\b",
 "monsters": r"\bmonsters?\b|\bcreatures? (of|from) (the deep|nightmare|another world|the dark)\b",
 "angels": r"\b(fallen|guardian) angels?\b|\bangelic\b|\bangels? and demons\b|\bthe archangel\b",
 # --- identity (explicit signal only) ----------------------------------
 "lesbian": r"\blesbian\b",
 "sapphic": r"\bsapphic\b|\bwlw\b|women who love women",
 "bisexual": r"\bbisexual\b|\bbi[- ]curious\b",
 "transgender": r"\btransgender\b|\btrans (woman|man|girl|boy|women|men)\b|\bnonbinary\b|\bnon[- ]binary\b",
}
# Tier B — plausible but broader; route to a look.
TAG_B = {
 "gay": r"\bgay (man|men|romance|love|couple|protagonist|teen|boy)\b|\bm/m romance\b",
 "lgbtq": r"\blgbtq?(ia)?\+?\b|\bqueer (romance|fiction|love|teen|protagonist|character|community|coming-of-age)\b",
 "retelling": r"\bre[- ]?telling\b|\bre[- ]?told\b|\bre[- ]?imagining\b|\bmodern retelling\b|a fresh spin on the (myth|tale|legend|fairy tale)",
 "paranormal": r"\bparanormal\b",
 "supernatural": r"\bsupernatural\b",
 # --- broader themes / settings / professions (2026-08 expansion) ------
 "magic": r"\bmagic(al)?\b|\bsorcer(y|er|ess)\b|\bspell(s|book|casting)?\b|\benchant(ed|ment|ress)\b|\bwizardry\b",
 "epic": r"\bepic (fantasy|saga|adventure|tale|journey|quest|story|struggle)\b|\bsweeping (saga|epic)\b|\ban epic\b",
 "police": r"\bpolice\b|\bdetective\b|\bhomicide\b|\bprecinct\b|\bpolice procedural\b|\bdetective (inspector|sergeant)\b|\bthe force\b",
 "murder": r"\bmurder(s|ed|er|ous)?\b|\bhomicide\b|\bslain\b|\bbrutally killed\b",
 "military": r"\bmilitary\b|\bsoldiers?\b|\bmarines?\b|\bnavy seal\b|\bspecial forces\b|\bcombat\b|\bwar[- ]?zone\b|\bplatoon\b",
 "war": r"\bwar[- ]?torn\b|\bwartime\b|\bbattlefield\b|\bfront lines?\b|\bcivil war\b|\bworld war\b|\bthe great war\b",
 "revenge": r"\brevenge\b|\bvengeance\b|\bavenge\b|\bout for blood\b",
 "music": r"\brock ?star\b|\bmusician\b|\blead singer\b|\bthe band\b|\borchestra\b|\bsymphony\b|\bviolinist\b|\bpianist\b|\bcomposer\b|\bjazz (club|singer|band)\b|\bband(-| )?mate\b",
 "cooking": r"\bchef\b|\bculinary\b|\brestaurant\b|\bbaker(y|ies)?\b|\bcook[- ]?off\b|\bpastry\b|\bpâtisserie\b",
 "art": r"\bpainter\b|\bpaintings?\b|\bart (gallery|forger|dealer|heist|thief|world)\b|\bsculptor\b|\bthe artist\b",
 "medical": r"\bsurgeons?\b|\bmedical (thriller|examiner|drama|mystery)\b|\bparamedics?\b|\bemergency room\b|\bthe hospital\b",
 "academia": r"\bprofessor\b|\buniversity\b|\bfaculty\b|\bgraduate student\b|\btenure\b|\bacademia\b",
 "college": r"\bcollege\b|\bsorority\b|\bfraternity\b|\bfreshman\b|\bdorm(itory)?\b|\bcampus\b",
 "friendship": r"\bfriendship\b|\bbest friends?\b|\blifelong friends?\b|\bunlikely friend(ship)?\b|\bcircle of friends\b",
 "survival": r"\bsurvival (story|thriller|horror|game)\b|\bfight(ing)? (for|to) survive\b|\blast (survivors?|humans?) (on|of)\b|\bstruggle to survive\b|\bstranded\b",
 "western": r"\bwild west\b|\bgunslinger\b|\bcowboys?\b|\bthe old west\b|\bfrontier (town|justice|life)\b|\boutlaws?\b",
 # DROPPED after audit — these are *vibe* words that mostly matched mis-shelved
 # academic nonfiction (feminist scholarship, "the satire of X", evocative
 # cookbooks) rather than fiction featuring the theme. A wrong tag is worse than
 # a missing one, and these need judgement a blurb can't reliably give:
 #   feminist, atmospheric, satire, cozy, survival, western.
}

# Drop the placeholder/guard entries whose value is None.
TAG_A = {k: v for k, v in TAG_A.items() if v}
TAG_B = {k: v for k, v in TAG_B.items() if v}

# Whenever one of these fires, also add the umbrella lgbtq tag.
IDENTITY = {"lesbian", "sapphic", "bisexual", "transgender", "gay"}

# The `fiction` class and the catalog genres are both noisy — academic readers,
# scholarly companions and criticism are frequently mis-shelved as "Literary
# Fiction" or "Fantasy" (e.g. "The transgender studies reader", "Christianizing
# Homer"). These markers are near-exclusive to nonfiction blurbs, so a book
# whose description trips one is skipped entirely rather than tagged from its
# subject matter. Kept deliberately narrow to avoid catching genuine novels.
NONFICTION_SIGNAL = re.compile(
    r"\bscholarship\b|\bscholarly\b|\bscholars\b|\bstudies reader\b|\bcompanion to\b|"
    r"\bcritical essays\b|\bessays (on|in|about)\b|\breadings in\b|\ba study of\b|"
    r"\bliterary criticism\b|\bannotations?\b|\bbibliograph|\bmonograph\b|"
    r"\btextbook\b|\brecipes?\b|\ban anthology of\b|\bthis collection of essays\b|"
    r"\bcultural history\b|\bacademic\b|\bnonfiction\b|\bnon-fiction\b|"
    r"\bexamines the (role|history|relationship|way|question|impact|nature) of\b|"
    # strengthened after auditing the identity / mythology / gothic tags, which
    # were polluted by gender-studies readers, lit-crit and film criticism:
    r"\bexamin(e|es|ing) (the|how|various)\b|\bdiscusses\b|\bdepictions of\b|"
    r"\bexplores the (ways?|role|history|relationship|impact|politics|culture)\b|"
    r"\bthe rights of\b|\(lgbtq?\)|\blgbtq? (studies|theory|rights|activis|movement)\b|"
    r"\bactivis(m|t)\b|\bideolog(y|ies|ical)\b|\bcompiled\b|\bedited by\b|"
    r"\bthe lives of\b|\bin the lyrics of\b|\ba (cultural|social|literary) history\b|"
    r"\bthis (book|volume|study|collection|anthology|reader) (examines|explores|"
    r"discusses|traces|argues|offers|presents|collects|charts|considers)\b|"
    r"\bcinema\b|\bin film and literature\b|\bcriticism\b|\bessays\b|"
    r"\bintroduction (to|by)\b|\banalys(is|es|ing)\b|\btheoretical\b|"
    r"\bconflicting ideologies\b|\bidentity and\b|\bthe study of\b",
    re.I)


def validate(conn):
    live = {r[0]: (r[1], r[2]) for r in
            conn.execute("SELECT slug, kind, status FROM taxonomy")}
    both = set(TAG_A) & set(TAG_B)
    bad = [f"{s}: in BOTH tiers" for s in sorted(both)]
    for slug in list(TAG_A) + list(TAG_B) + ["lgbtq"]:
        ks = live.get(slug)
        if ks is None:
            bad.append(f"{slug}: NOT IN TAXONOMY")
        elif ks != ("tag", "active"):
            bad.append(f"{slug}: kind={ks[0]} status={ks[1]} (need tag/active)")
    if bad:
        raise SystemExit("tag pack references invalid slugs:\n  " + "\n  ".join(bad))


def build_comp():
    comp = {k: (re.compile(v, re.I), "A") for k, v in TAG_A.items()}
    comp.update({k: (re.compile(v, re.I), "B") for k, v in TAG_B.items()})
    return comp


FIELDS = ["decision(keep/blank)", "tier", "tag", "matched_phrase",
          "book_id", "title", "author", "context"]


def run(out="tag_review.csv", src="both", limit_per_book=10, chunk=2000):
    """Chunked + streaming: fetch light (id-only) list once, then pull
    descriptions and write matches one chunk at a time so peak memory stays
    ~one chunk regardless of the 22k total (kind to a slow laptop). Rows are
    appended to a temp file as they are found, then sorted into `out` at the end
    (the sort holds only the matched rows, a few thousand, not all descriptions).
    """
    comp = build_comp()
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    validate(conn)
    # Prefer Wikipedia, then OL, then Google Books descriptions.
    desc_join = ("COALESCE(w.description, o.description, g.description)"
                 if src == "both" else "o.description")
    # Target ALL active fiction that has a description — not just fully-untagged
    # books — so the expansion can add missing concrete tags to books that
    # currently carry only mood tags. Existing tags are deduped per book, and
    # promote union-merges, so nothing already present is disturbed.
    ids = [r[0] for r in conn.execute(
        f"""SELECT b.id FROM books b JOIN enrichment_state s ON s.book_id=b.id
        LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
        LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
        LEFT JOIN book_metadata g ON g.book_id=b.id AND g.source='googlebooks'
        WHERE s.book_class='fiction'
          AND (b.status IS NULL OR b.status NOT LIKE 'archived%')
          AND {desc_join} IS NOT NULL AND TRIM({desc_join})!=''""")]
    conn.close()
    total = len(ids)
    print(f"scanning {total:,} fiction-with-description ({src}), chunk={chunk}", flush=True)

    out_rows, freq, tier_books, skipped, done = [], Counter(), Counter(), 0, 0
    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    for i in range(0, total, chunk):
        batch = ids[i:i + chunk]
        ph = ",".join("?" * len(batch))
        rows = conn.execute(
            f"""SELECT b.id, b.title, b.author, b.tags,
                    COALESCE(w.description,o.description,g.description) AS description
                FROM books b
                LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
                LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
                LEFT JOIN book_metadata g ON g.book_id=b.id AND g.source='googlebooks'
                WHERE b.id IN ({ph})""", batch).fetchall()
        for r in rows:
            desc = clean_desc(r["description"], r["title"])
            if desc is None or NONFICTION_SIGNAL.search(desc):
                skipped += 1
                continue
            try:
                existing = set(json.loads(r["tags"] or "[]"))
            except Exception:
                existing = set()
            found = {}
            for slug, (rx, tier) in comp.items():
                if slug in existing:            # don't re-propose an existing tag
                    continue
                m = rx.search(desc)
                if m:
                    found[slug] = (tier, m.group(0), context(desc, m))
            if not found:
                continue
            if IDENTITY & set(found) and "lgbtq" not in found:
                found["lgbtq"] = ("A", "(implied by identity tag)",
                                  "added because a specific LGBTQ identity tag fired")
            items = list(found.items())[:limit_per_book]
            tiers = {t for _, (t, _, _) in items}
            tier_books["A+B" if tiers == {"A", "B"} else next(iter(tiers))] += 1
            for slug, (tier, phrase, ctx) in items:
                freq[slug] += 1
                out_rows.append({"decision(keep/blank)": "", "tier": tier, "tag": slug,
                                 "matched_phrase": phrase, "book_id": r["id"],
                                 "title": r["title"], "author": r["author"] or "",
                                 "context": ctx})
        done += len(batch)
        print(f"  ...{done:,}/{total:,} | {len(out_rows):,} matches", flush=True)
    conn.close()

    out_rows.sort(key=lambda x: (x["tier"], x["tag"]))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out_rows)

    books_matched = len({r["book_id"] for r in out_rows})
    print(f"skipped {skipped:,} boilerplate")
    print(f"books with >=1 tag match: {books_matched:,} "
          f"({books_matched/max(1,total)*100:.0f}%)")
    print(f"total tag assignments: {len(out_rows):,} | by tier (books): {dict(tier_books)}")
    for slug, n in freq.most_common():
        print(f"   [{comp.get(slug, (None,'A'))[1]}] {n:>4}  {slug}")
    print(f"-> {out}")
    return books_matched, len(out_rows)


if __name__ == "__main__":
    src = "both" if "--both" in sys.argv else "ol"
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "tag_review.csv"
    run(out=out, src=src)

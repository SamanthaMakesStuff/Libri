"""Validated apply-set for canon_cross-genre.csv (all 1,592 rows decided).

Structural fixes needed here that earlier batches didn't have:
  * self-referential merges (chicago -> chicago) = "make this canonical" -> activate
  * merge CHAINS (irish-literature -> irish -> ireland) resolved transitively
  * 7 terms marked accept that batch 1 already merged away; re-asserted as merges
    so they aren't resurrected as duplicate standalone terms
"""
import csv
import sqlite3

import config as C

SRC = "canon_cross-genre.csv"
KEEP = {"accept", "activate", "approve", "keep", "yes"}
KILL = {"reject", "drop", "no", "delete"}

RETARGET = {
    "alternative-history": "alternate-history",   # active subgenre
    "fairy-tales": "fairy-tale-retelling",        # fairy-tales was merged there in batch 1
    "dubious-consent": "dubcon",                  # active (kind=warning)
    "political": "politics",
    "hollywood": "los-angeles",                   # los-angeles becomes canonical here
    "protective-male-protagonist": "touch-her-and-die-possessive-protective-hero",
    "irish": "ireland",                           # chain: irish-literature -> irish -> ireland
    "weird": "",                                  # target was Rejected -> see FORCE_ACTIVATE
}

CREATE = {
    "atlanta": "tag", "brazilian": "tag", "new-orleans": "tag",
    "business-people": "tag", "business-women": "tag",
    "consensual-non-consent": "warning",          # CNC; parallels the active `dubcon`
    "male-male-female-romance": "subgenre",       # mmf; parallels male-male/male-female-romance
}

# target was rejected, but the term itself is a legitimate genre -> stand alone
FORCE_ACTIVATE = {"weird-fiction"}
# meaningless catch-all, not worth a term
FORCE_DROP = {"fiction-general"}

EXTRA_MERGE = {
    "actor": "actors", "african-american": "african-americans",
    "amateur-detective": "amateur-detectives",
    "angst": "angsty", "asian-americans": "asian-american",
    "boarding-school": "boarding-schools",
    "career": "careers", "children-s-books": "children-s-book",
    "cosy-mystery": "cozy-mystery", "cowboys": "cowboy", "cults": "cult",
    "dark-humour": "dark-humor", "educational": "education", "essays": "essay",
    "humour": "humor", "lesbians": "lesbian", "mermaid": "mermaids",
    "narrative-non-fiction": "narrative-nonfiction", "newadult": "new-adult",
    "pirate": "pirates", "retellings": "retelling",
    "social-sciences": "social-science", "vampire": "vampires",
    "veterinarian": "veterinarians",
    "bookclub": "book-club", "criminal": "criminals", "ghost": "ghosts",
    "high-school": "high-schools", "school": "schools", "shifter": "shifters",
    # plural -> singular is the natural direction for a practice/topic tag
    "meditations": "meditation",
}

# scored 88-94 by fuzzy but are NOT the same concept - merging would destroy meaning
DO_NOT_MERGE = {
    "bakers", "bankers",                       # 92 - totally different jobs
    "asexuality", "sexuality",                 # 94 - asexuality is its own orientation
    "immortality", "mortality",                # 90 - opposites
    "human-animal-relationships",              # 89 vs human-ai-relationship
    "engineering", "bioengineering",           # 88 - broad vs narrow
    "business-enterprises", "new-business-enterprises",
    "depression", "depressions",               # mental health vs economic
    "female-author", "male-author",
    "female-friendship", "male-friendship",
    "female-protagonist", "male-protagonist",
    "fathers-and-daughters", "mothers-and-daughters",
    "development", "developmental",
    # --- caught on review: a PLACE is not a NATIONALITY. A book set in Africa
    # is not necessarily by or about African people, so these stay distinct.
    "africa", "african", "america", "american", "korea", "korean",
    "russia", "russian", "australia",
    # people vs the condition itself - same class of error
    "alcoholics", "alcoholism",
}

conn = sqlite3.connect(C.DB_PATH, timeout=120)
active = {r[0] for r in conn.execute("SELECT slug FROM taxonomy WHERE status='active'")}
alias_of = {r[0]: r[1] for r in conn.execute("SELECT alias, slug FROM taxonomy_alias")}

raw = {}
for r in csv.DictReader(open(SRC, encoding="utf-8-sig")):
    d = (r.get("decision") or "").strip()
    if d:
        raw[r["term"]] = (d, r.get("kind") or "tag", r.get("genre_bucket") or "")


def target_of(d):
    return d.split(":", 1)[1].strip() if ":" in d else ""


def resolve(term, tgt, depth=0):
    """Follow merge chains: a -> b where b itself merges to c, becomes a -> c."""
    if depth > 5 or not tgt:
        return tgt
    if tgt in RETARGET:
        tgt = RETARGET[tgt]
    if tgt == term:                       # self-reference handled by caller
        return tgt
    # the target may itself be merged away by one of OUR extra merges
    if tgt in EXTRA_MERGE and tgt not in DO_NOT_MERGE:
        return resolve(term, EXTRA_MERGE[tgt], depth + 1)
    # ...or by an alias already applied in an earlier batch
    if tgt not in active and tgt.replace("-", " ") in alias_of:
        a = alias_of[tgt.replace("-", " ")]
        if a != tgt:
            return resolve(term, a, depth + 1)
    nxt = raw.get(tgt)
    if nxt and nxt[0].lower().startswith("merge"):
        t2 = target_of(nxt[0])
        if t2 and t2 != tgt:
            return resolve(term, t2, depth + 1)
    return tgt


rows_out, seen = [], set()
stats = {"activate": 0, "drop": 0, "merge": 0, "selfref_activate": 0,
         "chain_resolved": 0, "retargeted": 0, "extra_merge": 0,
         "realias": 0, "created": 0}

for term, (d, kind, bucket) in raw.items():
    if term in seen:
        continue
    low = d.lower()
    if term in FORCE_DROP:
        out = "drop"; stats["drop"] += 1
    elif term in FORCE_ACTIVATE:
        out = "activate"; stats["activate"] += 1
    elif low in KEEP:
        norm = term.replace("-", " ")
        if term in EXTRA_MERGE and term not in DO_NOT_MERGE:
            out = f"merge:{EXTRA_MERGE[term]}"; stats["extra_merge"] += 1
        elif norm in alias_of and alias_of[norm] != term:
            # batch 1 already merged this away - don't resurrect it
            out = f"merge:{alias_of[norm]}"; stats["realias"] += 1
        else:
            out = "activate"; stats["activate"] += 1
    elif low in KILL:
        out = "drop"; stats["drop"] += 1
    elif low.startswith("merge"):
        tgt = target_of(d)
        if tgt == term:                        # "make me canonical"
            out = "activate"; stats["selfref_activate"] += 1
        else:
            before = tgt
            tgt = resolve(term, tgt)
            if tgt != before:
                stats["chain_resolved" if before not in RETARGET else "retargeted"] += 1
            out = f"merge:{tgt}" if tgt else "drop"
            stats["merge"] += 1
    else:
        continue
    seen.add(term)
    rows_out.append({"decision": out, "term": term, "kind": kind,
                     "genre_bucket": bucket, "applies_to": ""})

for slug, kind in CREATE.items():
    if slug not in seen:
        rows_out.append({"decision": "activate", "term": slug, "kind": kind,
                         "genre_bucket": "", "applies_to": ""})
        seen.add(slug); stats["created"] += 1

with open("canon_apply5.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["decision", "term", "kind", "genre_bucket", "applies_to"])
    w.writeheader(); w.writerows(rows_out)

print(f"wrote canon_apply5.csv ({len(rows_out)} decisions)")
for k, v in stats.items():
    print(f"  {k:<18} {v:>5}")
print(f"\n  created: {', '.join(sorted(CREATE))}")
print(f"  guarded from bad merges: {len(DO_NOT_MERGE)} terms")

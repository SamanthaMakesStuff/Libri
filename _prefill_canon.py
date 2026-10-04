"""Pre-fill the Phase 6 decision column with the calls that are mechanical.

Deliberately conservative: only (a) merges into slugs that ALREADY exist in the
active taxonomy and are semantically unambiguous, (b) library/format/index
artifacts that carry no taste signal, (c) the user's explicit rulings.
Genuine taste-vocabulary judgements are left BLANK on purpose.
"""
import csv
import glob

# user's explicit rulings + prior CSV ruling
USER = {"lgbtq": "activate", "classics": "activate", "war": "drop"}

# merges into terms that are already active
MERGE = {
    "young-adult-fiction": "young-adult",
    "morally-grey-characters": "morally-gray-antihero",
    "magic-system-with-consequences": "magic-system-with-a-cost",
    "ya-fantasy": "fantasy",
    "fantasy-fiction": "fantasy",
    "enemies-to-allies": "rival-turned-ally",
    "dragons-and-mythical-creatures": "dragons",
    "elves": "elves-dwarves-orcs",
    "heist-and-rebellions": "heist",
    "quest": "quest-journey-narrative",
    "apprentices": "apprenticeship-training-arc",
    "lit-rpg": "lit-rpg-game-lit",
    "fairy-tales": "fairy-tale-retelling",
    "human-alien-encounters": "first-contact-with-aliens",
    "interplanetary-voyages": "space-exploration",
    "general-science-fiction": "sci-fi",
    "extraterrestrial-beings": "aliens",          # aliens is activated below
    "artificial-intelligence-ai": "artificial-intelligence",
    "touch-her-and-die": "touch-her-and-die-possessive-protective-hero",
    "billionaires": "billionaire-romance",
    "traditional-detectives": "detective-fiction",
    "adventure-stories": "adventure-novels",
    "action-and-adventure": "adventure-novels",
    "literature-and-fiction": "literary-fiction",
    "romantic": "romance",
    "intense": "tense",
    "christmas": "holiday-romance",
    "holiday": "holiday-romance",
    "mystery-and-detective-stories": "detective-fiction",
}

# genuinely new vocabulary worth having (strong cases only)
ACTIVATE = {
    "space", "aliens", "robots", "zombies", "androids", "spaceship",
    "artificial-intelligence", "life-on-other-planets", "space-warfare",
    "captive-romance", "yearning", "hurt-comfort", "angsty", "atmospheric",
    "progression-fantasy", "noir",
}

# library records, formats, franchise/index artifacts, mangled concatenations
DROP = {
    "audio-book", "sample", "movie", "pdf", "tv-and-video-game-tie-ins",
    "award-winning-series", "scifi-masterwork", "dune-imaginary-place",
    "star-wars", "hercule-fictitious-character", "alex-fictitious-character",
    "jim-fictitious-character", "marple", "imaginary-places",
    "science-fiction-and-fantasy-science-fiction-adventure",
    "thriller-and-suspense-thriller-and-suspense-crime-thrillers",
    "thriller-and-suspense-crime-fiction", "jeune-adulte", "spanish",
    "juvenile-fiction", "juvenile-nonfiction", "children-s-stories",
    "childrens-and-young-adult", "literature", "english-fiction",
    "literary-criticism", "literary-collections", "games-and-activities",
    "comics-and-graphic-novels", "graphic-novels", "light-novels", "light-novel",
}


def decide(term):
    if term in USER:
        return USER[term]
    if term in MERGE:
        return f"merge:{MERGE[term]}"
    if term in ACTIVATE:
        return "activate"
    if term in DROP:
        return "drop"
    return ""


filled = 0
for path in ["proposed_terms_review.csv"] + sorted(glob.glob("canon_*.csv")):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    if not rows:
        continue
    n = 0
    for r in rows:
        d = decide(r["term"])
        if d and not (r.get("decision") or "").strip():
            r["decision"] = d
            n += 1
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    if path == "proposed_terms_review.csv":
        filled = n
    print(f"  {path:<34} pre-filled {n:>4}")

print(f"\nmaster file pre-filled: {filled} decisions "
      f"({len(MERGE)} merges, {len(ACTIVATE)} activations, {len(DROP)} drops, {len(USER)} yours)")
print("everything else left BLANK for your judgement.")

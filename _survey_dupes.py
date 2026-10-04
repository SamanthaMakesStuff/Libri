"""Read-only: how often is each near-duplicate trope slug actually used on books?

The taxonomy carries several pairs that mean the same thing (chosen-one /
the-chosen-one, fated-mates / fated-mates-destined-mates ...). A pattern pack
must target the DOMINANT slug or it fragments the signal, so count real usage.
"""
import json
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

conn = sqlite3.connect(C.DB_PATH, timeout=600)
use = Counter()
for (t,) in conn.execute("SELECT tropes FROM books WHERE tropes IS NOT NULL AND tropes!='[]'"):
    try:
        for s in json.loads(t):
            use[s] += 1
    except Exception:
        pass
conn.close()

GROUPS = [
    ["chosen-one", "the-chosen-one", "prophecy-bound-protagonist"],
    ["magic-school-magical-academy", "magic-school-setting", "magical-school-academy"],
    ["fated-mates", "fated-mates-destined-mates", "mating-bond"],
    ["slow-burn", "slow-burn-romance", "quiet-literary-slow-burn"],
    ["misunderstanding", "misunderstanding-big-mis"],
    ["found-footage-document-framing", "found-footage-documentary-framing"],
    ["single-parent-romance", "single-dad-mom", "nanny-single-parent-romance"],
    ["twist-ending", "twist-ending-rug-pull-reveal", "twist-ending-reality-reframing-reveal"],
    ["fake-dating", "fake-relationship-fake-engagement", "fake-marriage",
     "fake-marriage-becomes-real", "marriage-of-convenience"],
    ["age-gap", "age-gap-may-december-romance"],
    ["found-family", "found-family-adventuring-party", "band-of-misfits"],
    ["enemies-to-lovers", "hate-to-love", "rivals-to-lovers",
     "enemies-to-lovers-across-warring-factions"],
    ["secret-royalty", "secret-heir-lost-heir-secret-royalty", "royalty"],
    ["court-intrigue", "royal-court-intrigue", "court-intrigue-romance"],
    ["generation-ship", "generation-ship-society"],
    ["immigrant-experience", "immigrant-diaspora-experience",
     "immigrant-cultural-identity-coming-of-age"],
    ["identity-and-self-discovery", "identity-crisis-self-discovery"],
    ["haunted-house-mansion", "haunted-house-romance", "possessed-home"],
    ["competition-tournament-structure", "tournament-competition", "competition-trial-arc"],
    ["epistolary-structure", "epistolary-journal-format", "letters-diary-as-narrative-device"],
    ["multiple-pov", "dual-multiple-pov-structure"],
    ["dual-timeline", "dual-timeline-past-and-present-structure"],
    ["snowed-in-stranded", "snowed-in-trapped-together", "trapped-together", "stranded-together"],
    ["forbidden-knowledge", "forbidden-knowledge-education"],
    ["cinnamon-roll", "cinnamon-roll-sunshine-love-interest", "sunshine", "grumpy-sunshine"],
]
for g in GROUPS:
    print("  ".join(f"{s}={use.get(s,0)}" for s in g))

print(f"\ntotal distinct tropes in use: {len(use)}")
print("\ntop 40 in use:")
for s, n in use.most_common(40):
    print(f"  {n:>5}  {s}")

# Book Genre & Trope Taxonomy

Compiled from Goodreads' genre shelves, StoryGraph community trope lists, TV Tropes, and genre-writing resources (Writer's Digest, Book Riot, Jericho Writers, Kindlepreneur, EveryWriter, and others). Cross-checked across multiple sources per genre so a trope only made the list if it showed up consistently, not just on one site's personal favorites.

**A note on scope, since "every single" trope isn't really achievable:** TV Tropes alone lists 400+ tropes for horror specifically, and new tropes get coined constantly (romance especially — BookTok mints new trope names monthly). What follows is a genuinely large, well-organized *working vocabulary* — likely 90%+ of what you'll actually encounter tagging a real catalog — not a literal exhaustive enumeration. Treat it the same way the recommendation-engine spec treats your taxonomy generally: a strong seed list that the enrichment pipeline's "flag genuinely new tags for review" step will keep growing over time, rather than a frozen final list.

---

## How to use this against your schema

- **Genres** = top-level category (Romance, Fantasy, Mystery, etc.) — usually one or two per book.
- **Subgenres** = more specific flavor within a genre (e.g., within Fantasy: epic fantasy vs. cozy fantasy) — these could live in your `genres` array alongside the top-level genre, or as their own field if you want that granularity.
- **Tropes** = the recurring plot devices, relationship dynamics, and character types — these map to your `tropes` array.
- **Tags** = the more specific/niche descriptors (a trope's flavor, or things too specific to be a trope) — these map to your `tags` array. I've noted where something is really tag-level rather than trope-level.
- Many tropes are **cross-genre** (enemies to lovers shows up in fantasy, contemporary, historical, sci-fi). I've listed them once in the genre they originate from most strongly, plus a dedicated cross-genre section — don't feel like you need to duplicate every trope under every genre it could theoretically apply to.

---

## 1. Romance

### Subgenres
Contemporary romance, historical romance, paranormal romance, romantasy (fantasy romance), dark romance, romantic suspense, sports romance, small-town romance, category/office romance, LGBTQ+ romance, erotica, new adult, romantic comedy (rom-com), holiday romance, military romance, billionaire romance, cowboy/western romance, second-chance romance (also a trope), reverse harem, why choose.

### Relationship-dynamic tropes
Enemies to lovers, friends to lovers, strangers to lovers, hate to love, grumpy/sunshine, opposites attract, second chance romance, childhood sweethearts, exes-to-lovers, love triangle, forbidden love, star-crossed lovers, workplace romance, boss/employee romance, teacher/student (age-appropriate contexts only), age gap / May-December romance, brother's best friend, best friend's sibling, single parent romance, nanny/single-parent romance, roommates to lovers, neighbors to lovers, marriage of convenience, arranged marriage, fake dating, fake relationship/fake engagement, fake marriage, mail-order bride, secret relationship, forced proximity, only one bed, snowed in / trapped together, road trip romance.

### Character-type & premise tropes
Alpha hero, bad boy, grumpy hero, cinnamon roll / sunshine love interest, billionaire love interest, secret royalty, secret identity, celebrity/star romance, sports star romance, rockstar romance, bodyguard romance, boss's son/daughter, virgin heroine, playboy reformed, single dad/mom, widow(er) finding love again, best friend's older sibling, mentor/mentee (age-appropriate), rivals-to-lovers (sports/business/academic rivals), matchmaker/setup gone right.

### Plot-device tropes
Meet-cute, love at first sight, slow burn, insta-love, betting/wager on seduction, secret baby, amnesia, tragic past, runaway bride/groom, wedding-that-isn't, holiday/seasonal setup, summer romance, vacation romance, letters/pen-pal romance (epistolary), matchmaking app / dating app mishap, catfish/mistaken identity, class divide (rich/poor), different worlds, blackmail into relationship, jealousy plot, misunderstanding/big-mis, grovel arc, HEA (happily ever after) / HFN (happily for now) — note these last two are structural expectations rather than tropes proper and often live better as a `tags` field than `tropes`.

### Paranormal/romantasy-specific tropes
Fated mates / destined mates, shifter romance, vampire romance, fae romance, demon/angel romance, witch romance, found family (romance context), touch her and die / possessive-protective hero, mating bond, soulmates, immortal/mortal romance, court intrigue romance, monster romance ("monsterfucker"), grumpy fae lord, morally gray love interest.

### Spice/heat-adjacent (tag-level, not trope-level, but commonly requested)
Closed door, low spice/fade to black, moderate spice, high spice/explicit, slow-burn spice, dubcon (dubious consent — flag for content warnings), BDSM, polyamory, multiple POV intimacy scenes.

---

## 2. Fantasy

### Subgenres
Epic/high fantasy, low fantasy, urban fantasy, romantasy, grimdark, sword and sorcery, portal fantasy, fairy tale retelling, mythology retelling, cozy fantasy, dark fantasy, LitRPG/GameLit, fantasy of manners, flintlock/gaslamp fantasy, science fantasy, magical realism (often treated as its own genre bordering literary fiction), fae fantasy, dragon fantasy, dark academia (fantasy-adjacent).

### Hero/character tropes
The chosen one, reluctant hero, farm boy/orphan hero, secret heir / lost heir / secret royalty, the wise mentor, the dark lord/ultimate evil, morally gray antihero, redemption arc / antagonist-to-hero, the outcast hero, discovery of hidden powers, prophecy-bound protagonist, unlikely hero, band of misfits, found family, the last of their kind, mentor's death (fridging the mentor), rival turned ally.

### World/plot tropes
Prophecy, quest/journey narrative, portal to another world, magic school / magical academy, kingdoms at war, royal court intrigue, coup/rebellion against the crown, ancient evil awakening, forbidden magic, magic system with a cost (hard magic), soft/vague magic system, elemental magic, blood magic, necromancy, resurrection magic, magical artifact/relic of great power, one ring to rule them all (singular world-ending artifact), enchanted sleep, curse that must be broken, deal with a devil/demon, prophecy that's misinterpreted, war between good and evil, secret magical society hidden in the mundane world, apprenticeship/training arc, tournament/competition (deadly trials), heist in a fantasy setting, found family adventuring party.

### Creature/setting tropes
Dragons, elves/dwarves/orcs (classic fantasy races), shapeshifters, fae courts (Seelie/Unseelie), talking animals, magical creatures as companions, floating islands/cities, skyships, ancient ruins, forbidden forest, secret underground city, magic school setting, medieval European-coded setting, non-European-coded fantasy setting, multiple warring kingdoms, magical creatures bestiary-style worldbuilding.

### Cross-fantasy-romantasy tropes
Fated mates, court intrigue romance, enemies-to-lovers across warring factions, forbidden love across species/courts, morally gray fae love interest — (see also Romance section; these overlap heavily with romantasy).

---

## 3. Science Fiction

### Subgenres
Hard sci-fi, soft sci-fi, space opera, military sci-fi, cyberpunk, solarpunk, dystopian, utopian, post-apocalyptic, apocalyptic, first contact, time travel, alternate history, generation ship / colonization sci-fi, biopunk, science fantasy, climate fiction (cli-fi), YA dystopian (cross-listed with YA).

### Setting/premise tropes
Dystopian government / totalitarian regime, post-apocalyptic wasteland, resistance movement / rebellion against the state, generation ship, space colonization, terraforming, first contact with aliens, alien invasion, galactic empire, intergalactic war, hive mind, faster-than-light travel, warp speed, cryosleep/suspended animation, space station setting, remote research facility, virtual reality world, simulated reality (are-we-in-a-simulation), parallel universe / multiverse, alternate history (what if history diverged), generation-spanning saga.

### Technology/concept tropes
Rogue/sentient AI, benevolent AI companion, robot uprising, cybernetic enhancement, transhumanism, uploaded consciousness / digital immortality, genetic engineering, cloning, nanotechnology, biotechnology gone wrong, mind control/mind reading technology, teleportation, hologram/holographic technology, surveillance state, technology in the wrong hands, techno-babble/gadget-driven plot, human-AI relationship, post-human society.

### Time & space tropes
Time travel (forward), time travel (backward, with paradox risk), time loop, causal loop paradox, grandfather paradox, alternate timeline, time traveler stranded in the wrong era, space exploration, deep space mission, asteroid field peril, generation ship society, wormhole/hyperspace travel.

### Thematic tropes
Ethics of scientific progress, humanity vs. its own creation, corporate dystopia, environmental collapse narrative, post-scarcity society, resource scarcity conflict, class stratification in a future society, first-generation-off-Earth identity, uploaded/digital afterlife, what-does-it-mean-to-be-human.

---

## 4. Mystery, Crime & Thriller

### Subgenres
Cozy mystery, police procedural, detective fiction (hardboiled/noir), legal thriller, psychological thriller, domestic thriller, spy/espionage thriller, heist, courtroom drama, true crime-adjacent fiction, locked-room mystery, whodunit, howdunit, historical mystery, culinary/craft cozy mystery, amateur sleuth, serial killer thriller, action thriller, political thriller, medical thriller, techno-thriller.

### Structural/plot tropes
Locked-room mystery, closed circle of suspects, isolated setting (remote house/island/snowed-in), whodunit, howdunit (how was it done, not who), red herring, unreliable narrator, dual timeline / past-and-present structure, epistolary structure (letters/diaries/transcripts), missing person, ticking clock, MacGuffin (item everyone's chasing), perfect crime, framed protagonist, amnesia (victim or suspect), twist ending / rug-pull reveal, everyone-did-it (ensemble guilt), it-was-suicide-or-was-it, unsolvable-cold-case-reopened, first case / rookie investigator, wrong-person-convicted, court case as backbone of plot.

### Character tropes
Lone detective / maverick investigator, buddy cop / mismatched partners, alcoholic/broken detective, amateur sleuth stumbling into a case, serial detective (recurring protagonist across a series), femme fatale, mysterious stranger, stalker/unhinged ex as red herring or real threat, criminal mastermind, corrupt cop/official, informant with their own agenda, detective who becomes a suspect, killer hiding in plain sight, the confidant/sidekick who knows too much.

### Thriller-specific tropes
Kidnapping, blackmail, hostage situation, home invasion, conspiracy, espionage/double agent, sleeper agent, witness protection, cat-and-mouse pursuit, race against time, betrayal from within a trusted group, chase sequence, assassination plot, government cover-up, corporate conspiracy, revenge plot.

---

## 5. Horror

### Subgenres
Gothic horror, psychological horror, cosmic/Lovecraftian horror, body horror, folk horror, slasher, supernatural horror, haunted house, occult horror, monster horror, survival horror, splatterpunk, quiet horror/literary horror, horror-comedy.

### Setting tropes
Haunted house/mansion, abandoned building (asylum, hospital, school), remote/isolated location (cabin, island, snowed-in), small town with a dark secret, creepy hotel/motel, woods/forest as threat, underground/basement horror, suburban horror (evil in the mundane), possessed home.

### Antagonist/threat tropes
Ghost/vengeful spirit, demon/possession, ancient curse, ancient evil/cosmic entity, serial killer, slasher villain, monster in the dark, cannibalistic/backwoods threat, evil twin/doppelganger, creepy child, sentient inanimate object (doll, toy), body horror transformation, parasite/infection horror, folk-horror ritual community, killer that won't die, occult ritual gone wrong.

### Character/structural tropes
Final girl, nonbelievers who dismiss the warning, sole survivor, unreliable narrator (is it supernatural or is she losing her mind), found footage/documentary framing, epistolary horror (journals, transcripts), slow descent into madness, twist ending / reality-reframing reveal, small-group-picked-off-one-by-one, sinister warning ignored, one last scare (post-resolution jump scare), possession of a loved one, "I thought you were my friend" betrayal reveal.

---

## 6. Young Adult (cross-genre lens)

YA isn't a genre so much as an age-category lens applied across Fantasy, Sci-Fi, Contemporary, Romance, etc. — but it has its own recurring tropes worth tracking separately, since your earlier conversation noted YA books get miscategorized on Goodreads' crowd-sourced shelves.

Coming of age, chosen one (YA-flavored — often with a school setting), found family, magical school/academy, dystopian society / faction system, forbidden knowledge, first love, first heartbreak, love triangle, best friend becomes love interest, rebellion against an oppressive system, identity crisis / self-discovery, class divide, sacrifice for the greater good, mentor figure, absent/dead parents, sibling bond as central relationship, epistolary/journal format, mental health representation as central theme, immigrant/cultural-identity coming-of-age, neurodivergent protagonist, queer coming-of-age, survival narrative (maze/wilderness/dystopian trial), competition/trial arc (tournament, sorting, selection).

---

## 7. Historical Fiction

### Subgenres
War fiction (WWI/WWII/other conflicts), Regency, Victorian, Tudor/royal court fiction, ancient world (Rome, Greece, Egypt), medieval, colonial/postcolonial, biographical historical fiction, historical mystery, saga (multi-generational).

### Tropes
Star-crossed lovers across class/social lines, war and its aftermath on ordinary lives, hidden history / untold women's history, real historical figure as secondary character, dual timeline (past/present, connecting a modern character to a historical one), family saga across generations, letters/diary as narrative device, class divide, arranged marriage, war correspondence romance, resistance/spy work during wartime, coming-of-age against a historical backdrop, immigrant experience, based-on-a-true-story framing, court intrigue, forbidden knowledge/education (especially for women), survival against historical injustice.

---

## 8. Literary & Contemporary Fiction

Tropes here tend to be quieter and theme-driven rather than plot-device-driven — worth tagging differently than genre-fiction tropes, since "trope" in the plot-device sense is a looser fit.

Domestic fiction (marriage/family strain), interpersonal character study, multi-generational family saga, dual/multiple POV structure, unreliable narrator, non-linear timeline, grief and loss as central theme, coming-of-age (adult version — "second coming of age"), midlife reckoning, small-town secrets, class/social commentary, immigrant/diaspora experience, found family, chosen family vs. biological family tension, addiction narrative, mental health narrative, identity and self-discovery, epistolary structure, novel-in-stories/linked short stories structure, quiet/literary slow burn (no major plot event, character-driven).

---

## 9. Cross-genre / universal tropes

These show up across nearly every genre above and are worth keeping as their own reusable trope entries rather than duplicating per-genre:

Found family, enemies to lovers, love triangle, forced proximity, only one bed, road trip, dual timeline, multiple POV, unreliable narrator, epistolary structure, secret identity, amnesia, revenge plot, redemption arc, chosen one, prophecy, coming of age, class divide, forbidden love, twist ending, slow burn, second chance, mentor figure, found footage/document framing, competition/tournament structure.

---

## 10. Non-fiction categories (for completeness — tropes don't apply the same way)

If your catalog includes non-fiction, "tropes" isn't really the right lens — these function more as subject categories: Memoir, biography, autobiography, essay collection, narrative nonfiction, true crime, history, popular science, psychology, self-help, business, politics, philosophy, travel writing, food writing/cookbooks, nature writing, health & wellness, spirituality/religion, sports writing, art & music, humor/comedy essays.

For these, consider a separate `subjectTags` field rather than forcing them through `tropes` — e.g., "grief memoir," "immigrant memoir," "addiction recovery memoir," "corporate exposé," "science communication for general audiences" function more like your `tags` field already does for sub-trope specificity.

---

## Suggested next step

Given this is meant to seed a controlled vocabulary that the enrichment pipeline builds on, I'd treat this file as the v1 import: run it against your current `bookCatalog.json` tag usage to see what you're already using vs. what's missing, so you can decide what to backfill versus what to leave for the enrichment pipeline to add organically as new books come in. Happy to write that comparison script if useful.

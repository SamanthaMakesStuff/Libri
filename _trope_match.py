"""Deterministic trope extraction, generalised to romance / fantasy / sci-fi /
horror — the same technique proven on mystery (768 books, 907 tropes, no LLM).

Maps distinctive description phrases -> existing taxonomy trope slugs. Patterns
are tuned for PRECISION, because a wrong trope is worse than a missing one:
multi-word or context-bound phrases, never bare generic words. Every pack is
genre-gated, so `billionaire` only fires inside romance and `dragons` only
inside fantasy.

Two confidence tiers, matching the mystery pack:
  A  - distinctive enough to auto-apply (~95% in the mystery audit)
  B  - plausible but needs a human eye (~85%)

Every slug used below is validated against the live taxonomy at startup and
must be an ACTIVE **trope**. (The mystery pack silently wrote
`spy-espionage-thriller`, which is a *subgenre*; that check exists so a pattern
can never again leak a non-trope into the tropes column.) Where the taxonomy
holds near-duplicates, patterns target the slug that is actually dominant in
the data - `secret-heir-lost-heir-secret-royalty` (199 books) not
`secret-royalty` (3) - so matches reinforce the existing signal instead of
fragmenting it.

  python _trope_match.py romance --out trope_review_romance.csv --both
  python _trope_match.py all --both          # every pack, one CSV per genre
"""
import csv
import re
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config as C

# ---------------------------------------------------------------- romance ---
ROMANCE_A = {
 "fake-dating": r"fake[- ]dating|fake (relationship|girlfriend|boyfriend|fianc[eé]e?|date|engagement)|pretend(s|ing|ed)? to be (his|her|their) (girlfriend|boyfriend|fianc[eé]e?|wife|husband|partner|date)|pos(e|es|ing|ed) as (his|her) (girlfriend|boyfriend|fianc[eé]e?|wife|husband)",
 "marriage-of-convenience": r"marriage of convenience|convenient marriage|marry (him|her).{0,40}(inherit|inheritance|green card|save the (ranch|farm|estate|company))",
 "arranged-marriage": r"arranged marriage|arranged to marry|betrothed to (a|an|the) (stranger|man|woman|lord|prince)|promised in marriage",
 "mail-order-bride": r"mail[- ]order bride",
 "secret-baby": r"secret baby|he (doesn'?t|didn'?t|never) know(s)? (he has|about) (a|his) (son|daughter|child|baby)|hid (her|the) pregnancy|never told him.{0,30}(pregnant|his child|his son|his daughter)",
 "enemies-to-lovers": r"enemies[- ]to[- ]lovers|sworn enem(y|ies).{0,40}(attract|desire|love|kiss)|can'?t stand (each other|him|her).{0,50}(attract|drawn|desire)",
 "friends-to-lovers": r"friends[- ]to[- ]lovers|best friends?.{0,40}(fall|falling|fell) (in love|for (each other|him|her))|more than friends",
 "second-chance": r"second[- ]chance (romance|love|at love)|the one that got away|rekindl(e|es|ed|ing).{0,25}(romance|love|relationship|flame)|reunited.{0,30}(after|years|decade)",
 "single-dad-mom": r"single (dad|mom|mother|father)|widow(ed|er)? (father|mother|dad|mom) (of|with|raising)",
 "billionaire-love-interest": r"billionaire|self[- ]made (millionaire|mogul)",
 "boss-employee-romance": r"boss[- ](employee|secretary|assistant)|sleeping with (her|his) boss|fall(s|ing|en)? for (her|his) (new )?boss|off[- ]limits boss|(her|his) (new |arrogant |infuriating |handsome )+boss",
 "only-one-bed": r"only one bed|one bed left|(just|only) a single bed",
 "forced-proximity": r"forced proximity|stuck (together|with him|with her) (in|for|until)|trapped (together|in a).{0,30}(cabin|elevator|storm|island)",
 "snowed-in-stranded": r"snowed[- ]in|stranded (together )?(in|by) (a|the) (blizzard|snowstorm|storm)|blizzard (traps|strands)",
 "fated-mates": r"fated mates?|destined mates?|true mate|the mate bond|\bmy mate\b",
 "shifter-romance": r"\bshifters?\b|werewol(f|ves)|were[- ]wolf|wolf shifter|bear shifter|alpha of (the|his) pack",
 "vampire-romance": r"\bvampires?\b|\bvampiric\b",
 # bare kraken/tentacle caught a children's fantasy and an octopus *metaphor*;
 # the romance framing has to be explicit.
 "monster-romance": r"monster romance|monster (boyfriend|girlfriend|lover|mate|husband|wife)|(minotaur|orc|kraken|beast) (boyfriend|lover|mate|husband)",
 # `orc-romance` dropped: bare "orc" in a romance-shelved book found Tolkien's
 # Morgoth's Ring and two Taran Matharu YA fantasies, never a romance.
 # "(her|his) alien" without \b matched "Her alienation grows".
 "alien-romance": r"alien (warrior|prince|mate|male|captain|lover|husband)|(her|his) alien\b",
 "age-gap": r"age gap|years (his|her) (junior|senior)|old enough to be (her|his) (father|mother|daughter|son)|(twenty|thirty|fifteen|ten) years (older|younger) than",
 "bodyguard-romance": r"\bbodyguard\b|hires? a (former )?(navy seal|marine|soldier) to protect",
 "one-night-stand-to-lovers": r"one[- ]night stand|a single night (together|of passion)",
 "wake-up-married-vegas-wedding": r"wakes? up married|vegas wedding|drunken (wedding|marriage)|married in vegas",
 "runaway-bride-groom": r"runaway (bride|groom)|(leaves|left|jilted) (him|her)? ?at the altar|calls? off the wedding",
 "love-triangle": r"love triangle|torn between two (men|women|brothers|sisters|lovers)|caught between two (men|women)",
 "forbidden-love": r"forbidden (love|romance|affair|attraction|desire)|strictly off[- ]limits|shouldn'?t want (him|her).{0,30}(but|can'?t)",
 "brother-s-best-friend": r"brother'?s best friend",
 "best-friend-s-brother": r"best friend'?s (older )?brother",
 "opposites-attract": r"opposites attract|couldn'?t be more different|complete opposites",
 "soulmates": r"\bsoulmates?\b|soul[- ]bond",
 "love-at-first-sight": r"love at first sight",
 "small-town": r"small[- ]town (romance|charm|life|sheriff|bakery|bookshop)|returns? to (her|his) (small )?hometown|the small town of",
 "sports-star-romance": r"\bhockey (player|star|team)|\bquarterback\b|\bNFL\b|\bNHL\b|football (player|star)|professional athlete|(baseball|basketball|soccer) (player|star)",
 "rockstar-romance": r"rock ?star|lead singer|the band'?s (frontman|guitarist|drummer)|on tour with (the band|his band)",
 # bare \bvirgin\b matched Robyn Carr's entire *Virgin River* series, so the
 # word only counts as predicate or possessive, never as a place name.
 "virgin-heroine": r"(her|his) virginit(y|ies)|(is|was|still) a virgin\b|\bvirgin (bride|heroine|widow)\b|the last virgin|remained? a virgin",
 "omegaverse-abo": r"omegaverse|\bomega\b.{0,40}\balpha\b|\balpha\b.{0,40}\bomega\b.{0,20}(bond|heat|mate)",
 "workplace-romance": r"office romance|workplace romance|coworkers?.{0,30}(attract|fall|romance)|colleagues.{0,25}(fall|romance|attract)",
 "letters-pen-pal-romance": r"pen pals?|through (their )?letters|writes? to (him|her).{0,30}(front|war|prison)",
 # "summer in" alone matched L.P. Hartley's The Go-Between and a children's
 # fantasy - a book merely *set* over a summer is not a summer romance.
 "summer-romance": r"summer (romance|fling)|one perfect summer|summer (at the lake|by the sea)",
 "bad-boy": r"\bbad boy\b|the town'?s (bad boy|troublemaker)",
 "grumpy-sunshine": r"grumpy.{0,40}sunshine|sunshine.{0,40}grumpy|grumpy[- ]sunshine",
}
ROMANCE_B = {
 # an ex-husband who is merely a plot obstacle is not exes-to-lovers; require
 # the rekindling.
 "exes-to-lovers": r"ex[- ](husband|wife|boyfriend|girlfriend|fianc[eé]e?)\b.{0,80}(again|back (in|into) (her|his) life|second chance|rekindl|still (loves?|wants?)|can'?t resist|reunit)|(reunit|rekindl|second chance|back together).{0,60}ex[- ](husband|wife|boyfriend|girlfriend|fianc[eé]e?)\b",
 # "the queen"/"the king" are metaphor magnets in blurbs ("the queen of beach
 # books"), so only titled-character forms count.
 "royalty": r"\b(crown )?prince(ss)?\b|\bduke\b|\bduchess\b|\bearl of\b|\bthe (young|new|widowed) (king|queen)\b|heir to the throne",
 "secret-heir-lost-heir-secret-royalty": r"secret(ly)? (a )?(princess|prince|heir|royal)|long[- ]lost heir|rightful heir|didn'?t know (she|he) was (a )?(royal|princess|prince|heir)",
 "holiday-seasonal-setup": r"\bchristmas\b|\bholiday season\b|\bvalentine'?s day\b|\bnew year'?s eve\b",
 # bare "professor" matched a Poe collection and a short-fiction anthology's
 # table of contents; the student-teacher relation must be explicit.
 # "(her|his) tutor" alone found an epic-fantasy sorcerer tutoring a prince.
 "teacher-student-adult": r"(her|his) (professor|teaching assistant)\b|professor.{0,50}(student|pupil).{0,40}(attract|affair|romance|forbidden)|(student|pupil).{0,40}(falls? for|affair with).{0,20}(her|his|the) (professor|teacher|instructor)",
 # a Regency "coach" is a carriage - require the sport.
 "coach-athlete": r"\bcoach\b.{0,50}(athlete|player|team|training|season)|(head|hockey|football|basketball|swim|track) coach",
 # the trope is the widow finding love *again*, not any widowed character.
 "widow-finding-love-again": r"\bwidow(ed|er)?\b.{0,70}(falls? in love|new love|love again|remarr|second chance|suitor|courtship|find love)|(falls? in love|love again|remarr|second chance).{0,50}\bwidow(ed|er)?\b",
 "matchmaker-setup-gone-right": r"matchmaker|matchmaking|sets? (her|him) up on a (blind )?date",
 "catfish-mistaken-identity": r"mistaken identity|\bcatfish(ed|ing)?\b|thinks? (she|he) is someone else",
 # bare "nanny" caught a literary immigrant novel and a fired-the-nanny aside;
 # require the hiring setup that makes it the romance trope.
 "nanny-guardian-romance": r"(hires?|needs?|wanted|becomes?|takes? a job as|work(s|ing) as) (a |the |his |her )?(nanny|au pair|governess)|(nanny|au pair|governess) (to|for) (his|her|the) (son|daughter|child|children|baby|kids)",
 "matchmaking-app-dating-app-mishap": r"(dating|matchmaking) app|swipes? right|online dating profile",
 # "makes a bet" with no \b matched "makes a better hero"; an unqualified wager
 # also pulled in Around the World in 80 Days. Require the romantic stake.
 "bet-wager-romance": r"\b(bet|wager)\b.{0,60}(seduce|win her|win his|marry|kiss|date|bed (her|him))|(seduce|marry|kiss).{0,40}\b(on a bet|for a wager)\b",
 "road-trip-romance": r"road trip",
 "playboy-reformed": r"\bplayboy\b|notorious (rake|womani[sz]er)|confirmed bachelor",
 "class-divide": r"wrong side of the tracks|from (two )?different worlds|(her|his) world.{0,25}(never|couldn'?t) (mix|meet)",
 "neighbors-to-lovers": r"the (girl|boy|man|woman) next door|new neighbo(u)?r",
 "divorce-separation-romance": r"(recently|newly|freshly) (divorced|separated)|\bdivorc[ée]e\b|after (her|his) divorce|(her|his) (recent|bitter|messy) divorce|going through a divorce",
 # bare "possessive" described a *villain* (V.C. Andrews' Tony Tatterton).
 "touch-her-and-die-possessive-protective-hero": r"possessive (hero|alpha|mate|husband|lover|billionaire)|fiercely protective|\bmine\b.{0,20}(growl|snarl)",
 # "behind closed doors" is a stock blurb flourish, not a secret relationship.
 "secret-relationship": r"secret (relationship|affair|romance)|keep(ing)? (their|it) (relationship|affair) (a )?secret",
}

# ---------------------------------------------------------------- fantasy ---
FANTASY_A = {
 "dragons": r"\bdragons?\b|\bdragonrider|\bwyvern\b",
 "elves-dwarves-orcs": r"\belves\b|\belven\b|\bdwarves\b|\bdwarven\b|\borcs\b|\bgoblins\b",
 "magic-school-magical-academy": r"magic (school|academy)|academy (of|for) (magic|the arcane|young mages)|magical academy|school for (witches|wizards|mages|magic)|wizarding school",
 "chosen-one": r"the chosen one|\bthe one\b.{0,30}(prophec|destined|foretold)|destined to (save|destroy) (the|us|them)",
 "prophecy": r"\bprophecy\b|\bprophesied\b|\bfortold\b|\bforetold\b|an ancient prediction",
 "portal-to-another-world": r"portal (to|into) another (world|realm)|transported to (a|another) (magical |strange |different )?(world|realm|land)|pulled into (a|another) (world|realm)|finds? (herself|himself|themselves) in a (strange|magical|new|different) (world|realm|land)|whisked away to (a|an|the|another) (magical|strange|fantastical|enchanted|other) (world|realm|land|kingdom)",
 "quest-journey-narrative": r"embark(s|ed|ing)? on a (perilous |dangerous |epic )?(quest|journey)|a quest to (find|retrieve|destroy|save|recover)|sets? (out|off) on a (quest|journey)",
 "the-dark-lord-ultimate-evil": r"\bdark lord\b|the Dark One|evil (overlord|emperor)|(a|an) (great|ultimate|absolute) evil",
 "ancient-evil-awakening": r"ancient evil (awaken|stir|rise|return)|awaken(s|ed|ing)? (an|something) ancient|something ancient (stirs|wakes|awakens)|long[- ]dormant evil",
 "necromancy": r"necroman(cy|cer|tic)|raise the dead|army of the dead|reanimat(e|ed|ing) corpses",
 "blood-magic": r"blood magic|magic (fuel|powered) by blood|blood (price|sacrifice) for (the )?magic",
 "shapeshifters": r"shape[- ]?shift(er|ers|ing|s)?|can (turn|change) into (a|an) (wolf|bear|beast|animal)",
 "magic-system-with-a-cost": r"magic (comes|came) (at|with) a (price|cost)|the price of magic|magic (demands|takes|costs) (a|its|her|his)",
 "curse-that-must-be-broken": r"break the curse|lift the curse|the curse (can|must) (only )?be broken|cursed until",
 "ancient-curse": r"\bancient curse\b|a curse (laid|cast) (centuries|generations|long) ago",
 "kingdoms-at-war": r"kingdoms at war|war between (the )?(two )?kingdoms|warring kingdoms|(realm|kingdom)s? on the brink of war",
 "coup-rebellion-against-the-crown": r"overthrow the (king|queen|crown|throne|emperor)|(lead|leads|leading|led) a rebellion|rebellion against the (crown|king|queen|throne)|plot to (usurp|seize) the throne",
 "court-intrigue": r"court intrigue|(political )?intrigue.{0,25}court|the royal court|machinations of the court",
 "secret-heir-lost-heir-secret-royalty": r"long[- ]lost heir|rightful heir to the throne|secret(ly)? (the|a) (heir|princess|prince)|true heir",
 "found-family": r"found family|ragtag (group|band|crew|bunch)|band of misfits|misfit(s)? (who|that) become",
 "talking-animals": r"talking animals|animals (who|that) (can )?(talk|speak)|a talking (cat|dog|fox|raven|horse)",
 "magical-creatures-as-companions": r"(bonded|bonds?) (with|to) a (dragon|griffin|wolf|familiar)|(her|his) (dragon|griffin|familiar) companion",
 # unanchored "rob" matched inside "problems".
 "heist-in-a-fantasy-setting": r"\b(heist|steals?|stealing|robs?|robbery)\b.{0,40}(kingdom|palace|vault of the|magical artifact)|impossible heist",
 "magical-artifact-relic-of-great-power": r"(ancient|magical|powerful) (artifact|relic)|the (sword|amulet|crown|stone|blade) of (great )?power|an artifact of immense power",
}
FANTASY_B = {
 "elemental-magic": r"elemental magic|control(s|ling)? (fire|water|earth|air|the elements)|bend(s|ing)? the elements|master of the elements",
 "discovery-of-hidden-powers": r"discovers? (she|he|they) (has|have|is|are).{0,30}(power|magic|gift)|powers? (she|he) never knew|hidden (power|magic) (within|awaken)|(her|his) magic awakens",
 "apprenticeship-training-arc": r"apprentice(d|ship)? (to|under)|takes? (her|him) on as (an )?apprentice|train(s|ing) under (a|the) master",
 "mentor-figure": r"wise (old )?(mentor|wizard|sorcerer|master)|takes? (her|him|them) under (his|her) wing|(her|his) mentor",
 "tournament-competition": r"deadly (tournament|competition|trial|games)|the (trials|tournament) (begin|to determine)|compete in (a|the) (tournament|trials)",
 "farm-boy-orphan-hero": r"farm ?(boy|hand)|orphan(ed)? (boy|girl|child).{0,40}(destiny|magic|power|prophec)",
 "rebellion-against-an-oppressive-system": r"rebellion against|rise (up )?against (the|an) (empire|regime|oppress|tyrant)|resistance against (the|an)",
 "multiple-warring-kingdoms": r"(five|four|three|seven) kingdoms|the (warring|rival) houses",
 "forbidden-magic": r"forbidden magic|magic (is|was) (outlawed|forbidden|banned)|practi[cs]ing (the )?forbidden (arts|magic)",
 # `fae-courts` is the taxonomy's only fae trope. Explicit court language is
 # solid, but bare fae/fey is a reader-facing fantasy signal rather than proof
 # of the *courts*, so the whole slug sits in tier B for a human to split.
 "fae-courts": r"(seelie|unseelie)|fairy court|(the )?fae court|court of (thorns|dreams|nightmares|the fae)|\bfae\b|\bfaerie(s)?\b|\bfey\b",
}
# NOTE: there is no plain `witch` trope in the taxonomy - only `witch-romance`.
# An earlier draft mapped \bwitch\b in fantasy to it and pulled 215 books,
# nearly all of them non-romance (The Witch's Heart, Seriously Wicked). Left
# out deliberately: the right fix is a `witches-covens` trope, not a bad slug.

# ----------------------------------------------------------------- sci-fi ---
SCIFI_A = {
 "alien-invasion": r"alien invasion|aliens invade|invaded by (aliens|an alien)|invasion (from|of) (space|another world)|extraterrestrial invasion",
 "first-contact-with-aliens": r"first contact|humanity'?s first (meeting|encounter) with|first alien (contact|encounter)",
 "generation-ship": r"generation ship|colony ship|the ship (has|had) been travel(l)?ing for (generations|centuries)",
 "space-colonization": r"coloni[sz](e|ing|ation of) (a new|another|a distant) (planet|world)|colony on (mars|a distant|another)|the first colonists",
 "terraforming": r"terraform(ing|ed|s)?",
 "faster-than-light-travel": r"faster[- ]than[- ]light|\bFTL\b|light[- ]speed (travel|drive)",
 "warp-speed": r"warp (drive|speed|core)",
 "wormhole-hyperspace-travel": r"\bwormhole\b|\bhyperspace\b|\bhyperdrive\b|jump gate|\bjumpgate\b",
 "time-loop": r"time loop|relives? the same (day|hour|moment)|the same day (over and over|again and again)|stuck (in|reliving) the same day",
 "parallel-universe-multiverse": r"parallel (universe|world|realit)|\bmultiverse\b|alternate realit(y|ies)",
 "rogue-sentient-ai": r"rogue (AI|A\.I\.)|the (AI|A\.I\.) (turns|rebels|goes rogue|takes over|becomes self[- ]aware)|sentient (AI|computer|machine)|self[- ]aware (AI|machine)",
 "robot-uprising": r"robot(s)? (rise|uprising|rebel|revolt)|machines (rise|rebel|revolt)|android (uprising|rebellion)",
 "human-ai-relationship": r"falls? in love with (an |the )?(AI|android|robot|hologram)|romance with (an |the )?(AI|android)",
 "dystopian-government-totalitarian-regime": r"totalitarian (regime|government|state)|dystopian (future|society|world|state)|oppressive regime|under the regime'?s",
 "surveillance-state": r"surveillance state|constant surveillance|\bbig brother\b|every move is (watched|monitored|recorded)|the state watches",
 "post-apocalyptic-wasteland": r"post[- ]apocalyptic|after the apocalypse|the wasteland|what (little )?remains of (civili[sz]ation|humanity|the world)|in the ruins of the old world",
 "genetic-engineering": r"genetic(ally)? (engineer|modif|alter)|gene[- ](edit|splic|therapy)|designer (babies|children)|engineered (humans|people)",
 "cloning": r"\bclones?\b|\bcloning\b|cloned (human|version|copy)",
 "cybernetic-enhancement": r"\bcyborg\b|cybernetic(ally)?|neural implant|augmented (human|soldier|body)|\bbionic\b",
 "uploaded-consciousness-digital-immortality": r"upload(s|ed|ing)? (her|his|their|the)? ?(consciousness|mind|memories)|digital immortality|mind upload|consciousness (transferred|stored)",
 "virtual-reality-world": r"virtual (reality|world)|inside the (game|simulation)|\bVR\b|fully immersive (game|world)",
 "intergalactic-war": r"(interstellar|galactic|intergalactic) war|war (across|between) (the )?(stars|galaxies|worlds|systems)",
 "space-station-setting": r"space station|orbital station|aboard the station",
 "cryosleep-suspended-animation": r"cryo(sleep|genic|stasis|-sleep)|suspended animation|frozen for (centuries|decades|years)|wakes? from (cryo|stasis)",
 "nanotechnology": r"\bnanotech|\bnanobots?\b|\bnanites?\b|\bnanomachines?\b",
 "hive-mind": r"hive[- ]mind|collective consciousness",
 "corporate-dystopia": r"\bmegacorp|corporations? rule|corporate[- ](controlled|owned) (city|world|state)|company town of the future",
 "environmental-collapse-narrative": r"climate (collapse|catastrophe|refugee)|rising seas|environmental collapse|a dying planet|the last (forests|water|harvest)",
 "what-does-it-mean-to-be-human": r"what it means to be human|the nature of humanity|question(s|ing)? (what|whether) (makes us|it means to be) human",
 "teleportation": r"teleport(s|ed|ing|ation)?",
 "deep-space-mission": r"deep[- ]space (mission|expedition|probe)|mission to (the outer|a distant) (planet|system|star)",
}
SCIFI_B = {
 "alternate-timeline": r"alternate (timeline|history)|history (was|is) (changed|altered|rewritten)|a world where (the war|hitler|the south)",
 "galactic-empire": r"galactic empire|\bthe Empire\b.{0,40}(galax|star|planet|rebel)",
 "simulated-reality": r"simulated realit|none of (it|this) is real|the world (isn'?t|is not) real|living in a simulation|reality is a simulation",
 "mind-control-mind-reading-technology": r"mind control|read(s|ing)? minds|\btelepath(y|ic|s)?\b|thought[- ]reading",
 "class-stratification-in-a-future-society": r"(divided|split) into (castes|rigid classes|tiers)|the (upper|lower) levels of the city|born into (a|your) (caste|tier)",
 # "dwindling supplies" is any survival story (it matched Dan Simmons' The Terror).
 "resource-scarcity-conflict": r"water (wars|shortage|rations)|dwindling resources|the last (of the )?(oil|water|fuel)",
 "space-exploration": r"explor(e|es|ing|ation of) (deep )?space|interstellar (voyage|expedition|travel)|charting (the|new) (stars|systems)",
 "biotechnology-gone-wrong": r"(experiment|virus|bioweapon).{0,30}(escapes?|goes wrong|out of control)|engineered (virus|plague|pathogen)",
 "transhumanism": r"\btranshuman|beyond human|the next stage of (human )?evolution",
}

# ----------------------------------------------------------------- horror ---
HORROR_A = {
 "haunted-house-mansion": r"haunted (house|mansion|manor|hotel|estate|home)|the house (is|was) (haunted|alive|watching)|a house with a (dark )?(history|past)",
 "ghost-vengeful-spirit": r"vengeful (spirit|ghost)|restless spirit|the ghost of|angry spirits?|\bpoltergeist\b",
 "demon-possession": r"possessed by (a|an)? ?(demon|spirit|entity|something)|demonic possession|\bexorcis(m|t|e)",
 "occult-ritual-gone-wrong": r"ritual (goes|went) (wrong|awry)|summon(s|ed|ing) (a|an|something)? ?(demon|entity|thing|evil)|the seance|dabbl(e|ed|ing) in the occult",
 "ancient-evil-awakening": r"ancient evil (awaken|stir|rise)|awaken(s|ed|ing) something (ancient|evil|old)|something (ancient|old) (stirs|wakes|awakens)|disturb(s|ed) something",
 "final-girl": r"final girl",
 "cannibalistic-backwoods-threat": r"\bcannibals?\b|\bcannibalis(m|tic)\b",
 "sole-survivor": r"sole survivor|only survivor|the last one (left|alive)",
 "home-invasion": r"home invasion|(break|broke|breaks) into (her|his|their) (home|house).{0,40}(terror|nightmare|trapped)|strangers? at the door",
 "remote-isolated-location": r"remote (cabin|island|village|research station|outpost|farmhouse)|cut off from the outside world|isolated (cabin|island|farmhouse|community)|miles from (anywhere|help)",
 "small-group-picked-off-one-by-one": r"one by one.{0,30}(die|dies|vanish|disappear|killed)|picked off one by one|they start(ed)? (to )?(die|dying|disappearing)",
 "found-footage-documentary-framing": r"found footage|recovered (tapes|footage|recordings)|the (tapes|recordings) (were|was) (found|recovered)|documentary (crew|footage)",
 "slow-descent-into-madness": r"(descent|descending|spiral(s|ing)?) into (madness|insanity)|losing (her|his) (mind|grip on realit)|is (she|he) going (mad|insane)",
 "woods-forest-as-threat": r"something (in|lives in) the woods|the (woods|forest) (are|is) (watching|alive|wrong)|never go into the (woods|forest)|deep in the (woods|forest).{0,30}(something|wrong|evil)",
}
HORROR_B = {
 "body-horror-transformation": r"body horror|(her|his) (body|flesh|skin) (begins|starts|began) to (change|transform|split|melt)|transform(ing|ed) into something",
 "parasite-infection-horror": r"\bparasit(e|es|ic)\b|the infect(ed|ion) (spread|takes)|a host for",
 "folk-horror-ritual-community": r"pagan (ritual|village|rite)|the villagers.{0,40}(ritual|sacrifice|harvest)|folk horror|an old (rite|custom) the village",
 "creepy-child": r"creepy (child|kid|girl|boy)|the child(ren)? (are|is) (not right|wrong|different)|a child who (never|doesn'?t) (blink|smile|speak)",
 "monster-in-the-dark": r"something in the (dark|basement|attic|walls)|whatever (lives|lurks) (in|beneath)|a creature (in|from) the",
 "epistolary-horror": r"(through|told in) (letters|diary entries|journal entries|transcripts)|(her|his) diary reveals",
}

PACKS = {
 "romance": (ROMANCE_A, ROMANCE_B,
    "(b.genres LIKE '%Romance%' OR b.genres LIKE '%romance%')"),
 "fantasy": (FANTASY_A, FANTASY_B,
    "(b.genres LIKE '%Fantasy%' OR b.genres LIKE '%fantasy%')"),
 "sci-fi":  (SCIFI_A, SCIFI_B,
    "(b.genres LIKE '%Sci-Fi%' OR b.genres LIKE '%Science Fiction%' "
    "OR b.genres LIKE '%sci-fi%' OR b.genres LIKE '%science fiction%')"),
 "horror":  (HORROR_A, HORROR_B,
    "(b.genres LIKE '%Horror%' OR b.genres LIKE '%horror%')"),
}


def validate(conn):
    """Every pack slug must be an ACTIVE TROPE. Guards against the
    `spy-espionage-thriller` class of bug (that slug is a subgenre)."""
    live = {r[0]: (r[1], r[2]) for r in
            conn.execute("SELECT slug, kind, status FROM taxonomy")}
    bad = []
    for genre, (a, b, _) in PACKS.items():
        # comp is built tier-A-then-tier-B, so a slug in both tiers would have
        # its A pattern silently overwritten and lost.
        both = set(a) & set(b)
        if both:
            bad.append(f"{genre}: {', '.join(sorted(both))} -> in BOTH tiers")
        for slug in list(a) + list(b):
            kind_status = live.get(slug)
            if kind_status is None:
                bad.append(f"{genre}: {slug} -> NOT IN TAXONOMY")
            elif kind_status != ("trope", "active"):
                bad.append(f"{genre}: {slug} -> kind={kind_status[0]} status={kind_status[1]}")
    if bad:
        raise SystemExit("pattern packs reference invalid slugs:\n  " + "\n  ".join(bad))


# Some "descriptions" are not plot at all: series indexes ("**Books in this
# series** 1. [Ashley the Dragon Fairy]...") and anthology tables of contents
# ("The rocking-horse winner / D.H. Lawrence -- The professor's houses / U.K.
# LeGuin"). Matching those tags a book from its neighbours' titles.
SERIES_INDEX = re.compile(
    r"\*\*books in (this|the) series\*\*|books in this series|also in (this|the) series|"
    r"other books in", re.I)
# Numbered markdown link lists are series indexes too, with no header to key on:
# "1. [The Prophecies Begin][a] 2. [The New Prophecy][b]" tagged a Warriors book
# with `prophecy` from a sibling volume's title.
MD_LINK_LIST = re.compile(r"\[[^\]]{2,}\]\[[a-z0-9]+\]", re.I)
# Anthologies and collected editions describe themselves with a contents list,
# so any trope found belongs to a *component* story, not the book.
ANTHOLOGY_TITLE = re.compile(
    r"collected (works|stories|tales|fiction)|complete (works|tales|stories|novels)|"
    r"\banthology\b|treasury of|\bomnibus\b|book of .{0,25}(stories|tales)|"
    r"short (stories|fiction)|best of the|\bvol\.? ?[0-9ivx]+\b|volume [0-9ivx]+", re.I)
# Bibliographic / author-bio sentences are metadata, not plot: "won the Sidewise
# Award for alternate history" tagged a Ted Chiang collection.
AUTHOR_BIO = re.compile(
    r"[^.!?]*\b(is|was) a \d{4}[^.!?]*\.|"
    r"[^.!?]*\bis a [a-z\- ]{0,30}novel (written )?by[^.!?]*\.|"
    r"[^.!?]*\bwon the [^.!?]{0,60}award[^.!?]*\.|"
    r"[^.!?]*\baward for [^.!?]*\.|"
    r"[^.!?]*\bwas (born|appointed|educated|awarded)\b[^.!?]*\.", re.I)
# Marketing copy names *other* books and authors: "for fans of Akiko Higashimura
# (Princess Jellyfish)" tagged a manga as royalty. Those clauses describe the
# comparison title, never this book, so they are cut before matching.
COMP_TITLE = re.compile(
    r"(perfect |ideal |just )?for (fans|readers|lovers|admirers) of [^.!?]*[.!?]?|"
    r"in the (vein|tradition) of [^.!?]*[.!?]?|"
    r"(if you (loved|liked|enjoyed)|fans of) [^.!?]*[.!?]?|"
    r"\"[^\"]{15,}\"\s*[-—–]+\s*[A-Z][^.\n]{0,40}", re.I)


def clean_desc(desc, title=""):
    """Trim boilerplate; return None when the text isn't this book's plot.

    The two `.sub()` passes below are the pipeline's hot spot (their `[^.!?]*`
    scans cost ~20ms/desc), so each is gated behind a cheap literal check and
    only runs on the small fraction of descriptions that could possibly match.
    """
    if ANTHOLOGY_TITLE.search(title or ""):
        return None
    m = SERIES_INDEX.search(desc)
    if m:
        desc = desc[:m.start()]
    if "][" in desc:                       # markdown link list is the only source
        links = MD_LINK_LIST.search(desc)
        if links and len(MD_LINK_LIST.findall(desc)) >= 3:
            desc = desc[:links.start()]
    low = desc.lower()
    if "fans of" in low or "vein of" in low or "tradition of" in low or '"' in desc:
        desc = COMP_TITLE.sub(" ", desc)
    if "award" in low or "novel by" in low or "born" in low or "appointed" in low \
            or re.search(r"\b(is|was) a \d{4}", desc):
        desc = AUTHOR_BIO.sub(" ", desc)
    # a contents list, not a blurb (" -- " and " · " are the usual separators)
    if desc.count(" -- ") >= 2 or desc.count(" · ") >= 2:
        return None
    return desc.strip() or None


def context(desc, m, pad=40):
    s = max(0, m.start() - pad)
    return "..." + " ".join(desc[s:m.end() + pad].split()) + "..."


def match(desc, comp):
    out = []
    for slug, (rx, tier) in comp.items():
        m = rx.search(desc)
        if m:
            out.append((slug, tier, m.group(0), context(desc, m)))
    return out


def run(genre, out=None, src="both", limit_per_book=8):
    tier_a, tier_b, gate = PACKS[genre]
    comp = {k: (re.compile(v, re.I), "A") for k, v in tier_a.items()}
    comp.update({k: (re.compile(v, re.I), "B") for k, v in tier_b.items()})
    out = out or f"trope_review_{genre}.csv"

    conn = sqlite3.connect(C.DB_PATH, timeout=600)
    conn.row_factory = sqlite3.Row
    validate(conn)
    desc_expr = ("COALESCE(w.description, o.description)" if src == "both"
                 else "o.description")
    rows = conn.execute(f"""SELECT b.id, b.title, b.author, {desc_expr} AS description
        FROM books b JOIN enrichment_state s ON s.book_id=b.id
        LEFT JOIN book_metadata o ON o.book_id=b.id AND o.source='ol_dump'
        LEFT JOIN book_metadata w ON w.book_id=b.id AND w.source='wikipedia'
        WHERE {gate} AND s.book_class='fiction'
          AND (b.tropes IS NULL OR b.tropes='[]')
          AND {desc_expr} IS NOT NULL AND TRIM({desc_expr})!=''""").fetchall()
    conn.close()

    out_rows, freq, tier_books = [], Counter(), Counter()
    skipped_boilerplate = 0
    for r in rows:
        desc = clean_desc(r["description"], r["title"])
        if desc is None:
            skipped_boilerplate += 1
            continue
        ms = match(desc, comp)
        if not ms:
            continue
        ms = ms[:limit_per_book]
        tiers = {t for _, t, _, _ in ms}
        tier_books["A+B" if tiers == {"A", "B"} else next(iter(tiers))] += 1
        for slug, tier, phrase, ctx in ms:
            freq[slug] += 1
            out_rows.append({"decision(keep/blank)": "", "tier": tier, "trope": slug,
                             "matched_phrase": phrase, "book_id": r["id"],
                             "title": r["title"], "author": r["author"] or "",
                             "context": ctx})
    if skipped_boilerplate:
        print(f"{genre}: skipped {skipped_boilerplate:,} contents-list descriptions")

    if not out_rows:
        print(f"{genre}: no matches over {len(rows):,} books")
        return 0, 0
    out_rows.sort(key=lambda x: (x["tier"], x["trope"]))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    books_matched = len({r["book_id"] for r in out_rows})
    print(f"\n=== {genre} ===")
    print(f"scanned {len(rows):,} trope-less {genre} fiction with descriptions ({src})")
    print(f"books with >=1 match: {books_matched:,} ({books_matched/max(1,len(rows))*100:.0f}%)")
    print(f"total trope assignments: {len(out_rows):,} | by tier (books): {dict(tier_books)}")
    for slug, n in freq.most_common():
        print(f"   [{comp[slug][1]}] {n:>4}  {slug}")
    print(f"-> {out}")
    return books_matched, len(out_rows)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    genre = args[0] if args else "romance"
    src = "both" if "--both" in sys.argv else "ol"
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    targets = list(PACKS) if genre == "all" else [genre]
    for g in targets:
        run(g, out=out if len(targets) == 1 else None, src=src)

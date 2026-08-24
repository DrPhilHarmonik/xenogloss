# XENOGLOSS -- Roadmap

## Done

- Language generation via Ollama (qwen2.5:14b)
- Tiered artifact system with unlock thresholds
- Codex with confidence levels (guessing / probable / certain)
- LEXIS hint system with vocabulary fallback
- `:translate` records player translation, marks artifact solved
- `:mytranslation` reads back recorded translation
- `:list` shows solved status
- Hint thread guard, Ollama retry logic
- Lightweight `.meta.json` sidecar for fast campaign listing
- Shared punctuation utility, model config via env vars
- `:check` -- side-by-side translation comparison (spoiler, opt-in)
- Word validation on `certain` entries -- LEXIS warns on mismatch without revealing answer
- End-game reveal -- fires when all artifacts solved, `:reveal` shows full record

---

## Phase 2 -- Feedback Loop (complete)

---

## Phase 3 -- Codex Depth

### `:note word your notes here`
Use the currently-unused `notes` field on `CodexEntry`. Notes persist in the save file and display in the codex panel.

### `:find word`
Show which artifacts contain a given alien word. Cross-referencing is one of the core linguistics strategies -- this makes it explicit and easy.

### `:search meaning`
Search codex by English meaning. Useful when you can't remember which alien word you mapped to "water".

### Word frequency
Show how many artifacts a word appears in. High-frequency words are worth decoding early.

### Codex sort options
`:codex alpha`, `:codex confidence`, `:codex artifact` -- sort by different criteria. Right now it's always alphabetical.

---

## Phase 4 -- Content Generation

### Procedural artifact composition (done)
`engine/artifact_smith.py` composes artifacts directly from a `GrowingLanguage`'s
own lexicon and grammar instead of asking an LLM to invent text. Consistency is
structural, not hoped-for: every alien word is a real lexicon entry, and every
sentence obeys the language's word order and morphology (plural / tense /
possessive suffixes, negation prefix, adjective position). The English
translation and per-word breakdown are exact because each sentence is built from
known glosses. It runs offline with no model, and is reproducible from a `--seed`.
CLI: `python grow_language.py artifacts --id <lang> [--tier N] [--count N] [--seed N] [--json]`.
This also dissolves the "generation takes time" problem below for the procedural
path -- composition is instant, so background prefetch and `:more` are effectively
free; the Ollama generator remains available for richer, free-form flavor text.

### Background artifact generation
Tier 3/4/5 artifacts from the *LLM* generator take time to produce. Start
generating those in a background thread immediately after the initial campaign
loads, so they're ready when the player unlocks them. (Procedural artifacts need
no prefetch.)

### On-demand generation (`:more`)
Let the player request an additional artifact at their current highest unlocked
tier. With the procedural smith this is instant and offline; useful if they're
stuck and want more context for specific words.

### Lore deepening
As codex grows, LEXIS can offer civilization fragments beyond word hints -- short recovered texts, historical notes, population records. Rewards sustained play with narrative payoff.

---

## Phase 5 -- Grammar Discovery (done)

`:grammar` no longer hands over the spec. `engine/grammar_discovery.py` scores
every rule against the evidence the player actually holds.

### Progressive grammar panel (done)
Affix rules (plural, three tenses, possessive, negation) resolve on **minimal
pairs**: a base word and its inflected form both sitting in the codex. Three
pairs and the rule surfaces, with the pairs shown as its provenance. Where the
artifacts carry a `word_breakdown`, only pairs the breakdown attests are
counted, so a coincidental rhyme cannot unlock a rule the language never used;
campaigns whose artifacts carry no notes fall back to plain surface matching so
the rule stays reachable. Categories the language does not mark at all are
labelled as such rather than dangling forever.

Categories whose stem never stands bare take **paradigm pairs** instead. A verb
in a composed artifact always carries a tense suffix, so the bare stem never
reaches the codex and the three tense rules were unreachable as first shipped:
against a 37-word lexicon and 160 artifacts, fully decoded, the ceiling for past,
present, and future was 0 pairs each. They now resolve on the contrast between
two markings of one stem (`kelor` beside `kelet`), which is evidence for both
rules and is how the contrast is actually found in the field. Same attestation
gating applies to both halves. `tests/test_grammar_discovery.py` measures the
ceiling end to end against a generated corpus so a future generator change
cannot quietly make a rule unwinnable again.

Syntax rules (word order, adjective position) resolve on a different gate:
two unlocked texts of three or more words that the player has glossed end to
end -- which is what reading order off a text actually requires. Undiscovered
rules render as `???` with a progress counter.

Discovery is derived from codex + artifacts, so old saves need no migration;
the campaign persists only *which* rules have already fired, so `:forget`
cannot un-teach something LEXIS has announced. New rules are announced in the
message bar the moment the entry that resolves them lands.

### Grammar hints from LEXIS (done)
`:hint -or` / `:hint na-` route to an offline hinter instead of Ollama. It
names codex words carrying the affix whose plain form is still unlogged, or
counts how many more pairs are needed -- never the rule itself. For a rule in a
paradigm group it asks for a contrasting form rather than telling the player to
strip a suffix off a stem that never appears alone. An affix that belongs to no
rule is dismissed as part of the word.

---

## Phase 6 -- Polish & Meta

### Campaign difficulty setting
At new campaign start, offer:
- **Scholar** -- more context clues, shorter vocabulary, obvious tier 1
- **Linguist** (default) -- current balance
- **Cryptographer** -- fewer clues, abstract artifacts earlier, larger vocabulary

### New campaign intro sequence
Short narrative scene before generation begins -- sets the tone, explains the discovery. Displays while the LLM generates.

### `:progress` screen
Summary: artifacts solved vs. total, codex coverage per artifact, overall word coverage across all artifacts, estimated completion.

### Export
`:export` writes the current codex to a plain-text file. Useful for players who want to keep notes outside the game.

### Milestone messages
When a new tier unlocks, show a LEXIS-flavored announcement rather than silently adding the artifact.

---

## Stretch / Speculative

- **Multiple language families** -- at campaign start, choose a phoneme profile (consonant-heavy, vowel-rich, click-like) that shapes what the LLM generates
- **Multiplayer codex sharing** -- export/import codex files to collaborate with another player
- **Procedural civilization events** -- artifacts reference a timeline; decoding them in order reveals a narrative arc

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

### Background artifact generation
Tier 3/4/5 artifacts take time to generate. Start generating them in a background thread immediately after the initial campaign loads, so they're ready when the player unlocks them instead of forcing a wait mid-game.

### On-demand generation (`:more`)
Let the player request an additional artifact at their current highest unlocked tier. Useful if they're stuck and want more context for specific words.

### Lore deepening
As codex grows, LEXIS can offer civilization fragments beyond word hints -- short recovered texts, historical notes, population records. Rewards sustained play with narrative payoff.

---

## Phase 5 -- Grammar Discovery

Right now `:grammar` hands the player the full grammar spec immediately. Making it discoverable would add a puzzle layer.

### Progressive grammar panel
Grammar panel starts blank. Rules fill in as the player identifies patterns. Logic: once 3+ words with the same suffix are in the codex and their base forms are known, infer the rule and surface it. Requires matching `word_breakdown` grammar notes to codex entries.

### Grammar hints from LEXIS
`:hint` on a suffix or pattern (e.g., `:hint -or`) could give a grammar hint instead of a vocabulary hint.

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

# XENOGLOSS -- Alien Language Decoder

A terminal linguistics puzzle game. An alien civilization left behind artifacts. No translation exists. Decode their language from scratch.

Each new game generates a completely original alien language using a local LLM (qwen2.5:14b via Ollama), then populates the world with artifacts written in that language.

---

## Starting the game

```bash
cd xenogloss
python3 main.py          # pick an existing campaign or start new
python3 main.py --new    # force a new campaign
```

Startup takes **4-6 minutes** the first time -- the LLM is generating the language spec and 5 initial artifacts. A streaming window shows it working. Subsequent loads of the same campaign are instant.

Before generation starts, Xenogloss now checks that Ollama is reachable and that the configured language and hint models are installed. If you use non-default values, set `XENOGLOSS_OLLAMA_URL`, `XENOGLOSS_LANGUAGE_MODEL`, or `XENOGLOSS_HINT_MODEL`.

---

## The basic loop

1. **Read the artifact** -- the left panel shows alien text and context clues below it
2. **Study the context clues** -- they tell you where the artifact was found, what surrounds it, what was depicted nearby
3. **Guess word meanings** -- type `alienword meaning` into the input bar at the bottom
4. **Watch the text update** -- known words light up in color as you build your codex
5. **Unlock more artifacts** -- as your codex grows, higher-tier artifacts become available

---

## Decoding words

Type directly into the input bar (no colon prefix needed):

```
veth water
```

This adds `veth = water` to your codex at **guessing** confidence. To set confidence:

```
veth water certain
veth water probable
veth water guessing
```

Known words are highlighted in the artifact text by confidence level:
- **Green** -- certain
- **Cyan** -- probable  
- **Yellow** -- guessing

If you made a wrong guess, remove it:

```
:forget veth
```

---

## Commands

All commands start with `:`.

| Command | What it does |
|---|---|
| `:next` / `:prev` | Navigate between unlocked artifacts |
| `:find word` | Show which artifacts contain a specific alien word |
| `:search meaning` | Search your codex by guessed English meaning |
| `:hint word` | Ask LEXIS (AI) for a vague, in-character clue about a specific word |
| `:hint -suffix` | Ask LEXIS about a recurring affix (`:hint -or`, `:hint na-`) instead of a word |
| `:forget word` | Remove a word from your codex |
| `:translate your text here` | Record your full translation attempt for the current artifact |
| `:mytranslation` | Show your recorded translation for the current artifact |
| `:check` | Compare your translation to the actual translation (spoiler) |
| `:reveal` | Show all translations once every artifact is solved |
| `:grammar` | Show the grammar you have reconstructed so far, and how close the rest is |
| `:info` | Show civilization background lore |
| `:help` | Show in-game help |

---

## Tips for decoding

**Start with the obvious.** Tier 1 artifacts are designed to be solvable: a number sequence next to quantities, a color word next to a colored object, a label on a door. Look at the context clues and ask "what category of word would make sense here?"

**Grammar is discovered, not given.** `:grammar` starts almost blank. A suffix rule
resolves once your codex holds three **minimal pairs** -- a word and its inflected
form, like `nur` alongside `nurn`. Word order and adjective position resolve once
you have glossed two whole texts end to end. Until then the panel shows `???` and a
progress counter, so it tells you what to go looking for. If you see the same ending
on several words, log the plain form too: that is what turns a hunch into a rule.

**`:hint -suffix` asks about a pattern.** `:hint -or` or `:hint na-` skips the AI and
answers from your own records -- naming words that carry the affix whose plain form
you have not logged yet. It never states the rule; it points at the evidence.

**`:hint word` is your friend.** LEXIS is an in-character damaged translation AI that gives deliberately vague clues. It won't tell you the answer, but it can nudge you in the right direction. Use it when you're stuck on a specific word.

**Cross-reference artifacts.** A word that appears in artifact 1 and artifact 3 gives you two sets of context clues to triangulate from. Switch between artifacts with `:next` / `:prev`.

**Use `:find` and `:search`.** `:find alienword` shows every artifact that contains a word, and `:search meaning` finds codex entries by your guessed English translation.

**Track confidence honestly.** Mark words `certain` only when you've confirmed them across multiple contexts. A wrong `certain` entry can mislead your interpretation of everything else.

---

## Artifact tiers

New artifacts unlock as your codex grows.

| Tier | Unlock threshold | What to expect |
|---|---|---|
| 1 | Always available | 4-6 words, obvious context (labels, numbers, colors) |
| 2 | 8 words decoded | Simple present-tense sentences |
| 3 | 20 words decoded | Grammar patterns emerge, tense and plurals visible |
| 4 | 40 words decoded | Abstract nouns, complex sentences, indirect clues |
| 5 | 65 words decoded | Poetry or philosophy -- requires a near-complete codex |

---

## Saves

Each campaign is saved automatically after every codex change. Save files live in `data/saves/`. You can run multiple campaigns (different alien languages) simultaneously.

---

## Growing a language over time

Xenogloss also includes a separate CLI for building a persistent conlang that adds new vocabulary over time using your local Ollama model.

```bash
cd xenogloss
python3 grow_language.py init
python3 grow_language.py status
python3 grow_language.py grow --id YOUR_LANGUAGE_ID
python3 grow_language.py export --id YOUR_LANGUAGE_ID --output my-language.json
```

Default behavior:
- `init` creates a new language with 24 seed words
- `grow` adds 8 new words
- the target lexicon size is 1000 words
- only one growth batch is allowed per day unless you pass `--force`

Useful options:
- `python3 grow_language.py init --seed-words 40 --daily-words 12 --target-size 2500`
- `python3 grow_language.py grow --id YOUR_LANGUAGE_ID --date 2026-04-14`
- `python3 grow_language.py grow --id YOUR_LANGUAGE_ID --words 20 --force`
- `python3 grow_language.py status --id YOUR_LANGUAGE_ID --words 20`

The growing-language saves live in `data/growing_languages/`.

### Daily automation

For a simple cron job that grows one language every day at 9:00 AM:

```cron
0 9 * * * cd /home/god/projects/xenogloss && /usr/bin/python3 grow_language.py grow --id YOUR_LANGUAGE_ID >> /home/god/projects/xenogloss/data/growing_languages/growth.log 2>&1
```

Model selection is inherited from the same environment variable used by the main game:
- `XENOGLOSS_LANGUAGE_MODEL`
- `XENOGLOSS_OLLAMA_URL`

For separate models in the growing-language workflow:
- `XENOGLOSS_SEED_MODEL` for `grow_language.py init`
- `XENOGLOSS_GROWTH_MODEL` for `grow_language.py grow`
- `XENOGLOSS_SEED_TIMEOUT` for slow `init` models
- `XENOGLOSS_GROWTH_TIMEOUT` for daily growth calls

Example:

```bash
export XENOGLOSS_SEED_MODEL=qwen3:14b
export XENOGLOSS_GROWTH_MODEL=qwen2.5:14b
export XENOGLOSS_SEED_TIMEOUT=900
python3 grow_language.py init
```

Or use the included repo-local shell snippet:

```bash
source /home/god/projects/xenogloss/models.env.sh
python3 grow_language.py init
```

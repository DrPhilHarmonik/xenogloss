"""Procedural artifact generation (Phase 4).

The LLM generator (``engine.generator``) asks a model to invent alien text and
hopes it matches the language. This module instead *composes* artifacts from a
``GrowingLanguage``'s own lexicon and grammar, so consistency is structural:
every alien word is a real lexicon entry, and every sentence obeys the
language's word order and morphology (plural / tense / possessive suffixes,
negation prefix, adjective position). No network, no model, fully offline, and
reproducible from a seed.

Because we build each sentence from known glosses, the English translation and
the per-word breakdown are exact rather than guessed.
"""
from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass, field

from .artifacts import Artifact, WordBreakdown
from .growth_language import GrowingLanguage, LexiconEntry
from .language import GrammarRules

# Artifact kinds we can compose per tier. Mirrors the LLM generator's tiers but
# only lists what the procedural composer knows how to build.
ARTIFACT_TYPES_BY_TIER = {
    1: ["label", "sign", "inscription"],
    2: ["inscription", "dialogue", "notice"],
    3: ["journal", "law", "letter"],
    4: ["letter", "law", "speech"],
    5: ["poem", "prayer", "saying"],
}

# Artifact kinds that read best as a single clause (subject/verb/object) rather
# than a bare noun phrase.
_CLAUSE_TYPES = {"inscription", "dialogue", "notice", "journal", "letter", "speech", "saying"}
_NEGATED_TYPES = {"law"}  # laws read as prohibitions: "not touch stone"

_IRREGULAR_PAST = {
    "see": "saw", "go": "went", "eat": "ate", "make": "made", "take": "took",
    "give": "gave", "know": "knew", "come": "came", "find": "found", "hold": "held",
    "speak": "spoke", "build": "built", "run": "ran", "fall": "fell", "rise": "rose",
    "be": "was", "have": "had", "do": "did", "say": "said", "keep": "kept",
}


@dataclass
class _Tok:
    """One surface token: the alien form the player reads, its base gloss, and a
    short note describing any grammar applied (shown in the word breakdown)."""
    alien: str
    gloss: str
    note: str = ""
    content: bool = False  # nouns/verbs -- the words worth learning from this artifact


def _clean_affix(marker: str) -> str:
    """Turn a grammar marker like '-n', 'na-', or '?' into bare letters ('n', 'na', '')."""
    if not marker or marker.strip() in ("?", "-", ""):
        return ""
    return marker.strip().strip("-").strip()


def _suffix(word: str, marker: str) -> str:
    return word + _clean_affix(marker)


def _prefix(word: str, marker: str) -> str:
    return _clean_affix(marker) + word


def _parse_word_order(raw: str) -> list[str]:
    """Parse a grammar word-order string into an ordered list of 'S','O','V'.

    Handles both spelled-out ('Subject-Object-Verb') and abbreviated ('SOV')
    forms. Anything missing is appended in the canonical S,O,V order so the
    result always covers all three roles.
    """
    order: list[str] = []
    tokens = [t for t in re.split(r"[^A-Za-z]+", raw or "") if t]
    source = [t[0].upper() for t in tokens] if len(tokens) >= 2 else list((raw or "").upper())
    for ch in source:
        if ch in "SOV" and ch not in order:
            order.append(ch)
    for ch in "SOV":
        if ch not in order:
            order.append(ch)
    return order[:3]


def _pluralize_en(word: str) -> str:
    if re.search(r"(s|x|ch|sh)$", word):
        return word + "es"
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    return word + "s"


def _verb_base(gloss: str) -> str:
    """'to see' -> 'see'."""
    return re.sub(r"^to\s+", "", gloss.strip(), flags=re.IGNORECASE)


def _conjugate_en(gloss: str, tense: str) -> str:
    base = _verb_base(gloss)
    if tense == "past":
        if base in _IRREGULAR_PAST:
            return _IRREGULAR_PAST[base]
        if base.endswith("e"):
            return base + "d"
        if re.search(r"[^aeiou]y$", base):
            return base[:-1] + "ied"
        return base + "ed"
    if tense == "future":
        return "will " + base
    return base


@dataclass
class _Phrase:
    """A built fragment: its alien tokens (in alien order) and its English reading."""
    tokens: list[_Tok] = field(default_factory=list)
    english: str = ""


class ArtifactSmith:
    """Composes ``Artifact`` objects from a grown language's lexicon + grammar."""

    def __init__(self, language: GrowingLanguage, seed: int | None = None):
        self.language = language
        self.grammar: GrammarRules = language.grammar
        self.rng = random.Random(seed)
        self.word_order = _parse_word_order(self.grammar.word_order)
        self.adj_before = "before" in (self.grammar.adjective_position or "").lower()
        self._bucket()

    # -- lexicon buckets ------------------------------------------------------

    def _bucket(self) -> None:
        self.nouns: list[LexiconEntry] = []
        self.verbs: list[LexiconEntry] = []
        self.pronouns: list[LexiconEntry] = []
        self.adjectives: list[LexiconEntry] = []
        self.adverbs: list[LexiconEntry] = []
        self.others: list[LexiconEntry] = []
        for entry in self.language.words:
            if not entry.alien or not entry.english:
                continue
            pos = (entry.part_of_speech or "").lower()
            # Order matters: 'adverb' contains 'verb', 'pronoun' contains 'noun',
            # so test the more specific labels first.
            if "pron" in pos:
                self.pronouns.append(entry)
            elif "adv" in pos:
                self.adverbs.append(entry)
            elif "adj" in pos:
                self.adjectives.append(entry)
            elif "verb" in pos:
                self.verbs.append(entry)
            elif "noun" in pos:
                self.nouns.append(entry)
            else:
                self.others.append(entry)

    def can_compose(self) -> bool:
        """True if there is at least one usable content word."""
        return bool(self.nouns or self.verbs or self.others)

    def _pick(self, pool: list[LexiconEntry]) -> LexiconEntry | None:
        return self.rng.choice(pool) if pool else None

    def _any_noun(self) -> LexiconEntry | None:
        return self._pick(self.nouns) or self._pick(self.others)

    # -- phrase builders ------------------------------------------------------

    def _noun_phrase(self, *, allow_adj=True, allow_plural=True, allow_possessor=True) -> _Phrase | None:
        noun = self._any_noun()
        if noun is None:
            return None
        tokens: list[_Tok] = []
        eng_parts: list[str] = []

        possessor = None
        if allow_possessor and _clean_affix(self.grammar.possessive_suffix) and len(self.nouns) >= 2 and self.rng.random() < 0.35:
            possessor = self._pick([n for n in self.nouns if n.alien != noun.alien])
        if possessor is not None:
            tokens.append(_Tok(
                _suffix(possessor.alien, self.grammar.possessive_suffix),
                possessor.english,
                f"possessive (-{_clean_affix(self.grammar.possessive_suffix)})",
                content=True,
            ))
            eng_parts.append(possessor.english + "'s")

        adj = self._pick(self.adjectives) if (allow_adj and self.adjectives and self.rng.random() < 0.5) else None
        plural = allow_plural and bool(_clean_affix(self.grammar.plural_suffix)) and self.rng.random() < 0.35

        noun_alien = noun.alien
        note = ""
        if plural:
            noun_alien = _suffix(noun_alien, self.grammar.plural_suffix)
            note = f"plural (-{_clean_affix(self.grammar.plural_suffix)})"
        noun_tok = _Tok(noun_alien, noun.english, note, content=True)
        adj_tok = _Tok(adj.alien, adj.english, content=False) if adj else None

        if adj_tok and self.adj_before:
            tokens.append(adj_tok)
        tokens.append(noun_tok)
        if adj_tok and not self.adj_before:
            tokens.append(adj_tok)

        core = _pluralize_en(noun.english) if plural else noun.english
        if adj_tok:
            core = f"{adj.english} {core}"
        eng_parts.append(core)
        return _Phrase(tokens, " ".join(eng_parts))

    def _tense(self) -> str:
        choices = []
        if _clean_affix(self.grammar.present_suffix):
            choices.append("present")
        if _clean_affix(self.grammar.past_suffix):
            choices.append("past")
        if _clean_affix(self.grammar.future_suffix):
            choices.append("future")
        return self.rng.choice(choices) if choices else "present"

    def _verb_token(self, verb: LexiconEntry, tense: str, negate: bool) -> _Tok:
        suffix_marker = {
            "present": self.grammar.present_suffix,
            "past": self.grammar.past_suffix,
            "future": self.grammar.future_suffix,
        }.get(tense, "")
        surface = _suffix(verb.alien, suffix_marker)
        notes = []
        if _clean_affix(suffix_marker):
            notes.append(f"{tense} tense (-{_clean_affix(suffix_marker)})")
        if negate and _clean_affix(self.grammar.negation_prefix):
            surface = _prefix(surface, self.grammar.negation_prefix)
            notes.append(f"negation ({_clean_affix(self.grammar.negation_prefix)}-)")
        return _Tok(surface, verb.english, "; ".join(notes), content=True)

    def _clause(self, *, negate=False) -> _Phrase | None:
        verb = self._pick(self.verbs)
        if verb is None:
            return None
        subject_entry = self._pick(self.pronouns) or self._any_noun()
        if subject_entry is None:
            return None

        tense = self._tense()
        verb_tok = self._verb_token(verb, tense, negate)

        subj_tok = _Tok(subject_entry.alien, subject_entry.english,
                        content="pron" not in (subject_entry.part_of_speech or "").lower())
        obj_phrase = self._noun_phrase(allow_possessor=False) if (self.nouns and self.rng.random() < 0.85) else None

        roles: dict[str, list[_Tok]] = {"S": [subj_tok], "V": [verb_tok], "O": obj_phrase.tokens if obj_phrase else []}
        alien_tokens: list[_Tok] = []
        for role in self.word_order:
            alien_tokens.extend(roles.get(role, []))

        # English is rendered in plain SVO for readability.
        subj_en = "I" if "pron" in (subject_entry.part_of_speech or "").lower() and subject_entry.english in ("i/me", "i", "me") else subject_entry.english
        verb_en = _conjugate_en(verb.english, tense)
        if negate:
            verb_en = "not " + verb_en
        english = subj_en + " " + verb_en
        if obj_phrase:
            english += " " + obj_phrase.english
        return _Phrase(alien_tokens, english)

    # -- assembly -------------------------------------------------------------

    def _compose(self, artifact_type: str) -> _Phrase | None:
        if artifact_type in _NEGATED_TYPES:
            return self._clause(negate=True) or self._noun_phrase()
        if artifact_type in _CLAUSE_TYPES:
            first = self._clause()
            if first is None:
                return self._noun_phrase()
            # Longer forms get a second short line/clause.
            if artifact_type in {"journal", "letter", "speech", "dialogue"}:
                second = self._clause() or self._noun_phrase()
                if second is not None:
                    joined_tokens = first.tokens + second.tokens
                    return _Phrase(joined_tokens, first.english + ". " + second.english)
            return first
        if artifact_type in {"poem", "prayer", "saying"}:
            a = self._noun_phrase()
            b = self._noun_phrase()
            if a and b:
                return _Phrase(a.tokens + b.tokens, a.english + " -- " + b.english)
            return a or b
        # label / sign and anything else: a bare noun phrase.
        return self._noun_phrase()

    def make(self, tier: int = 1, artifact_type: str | None = None, artifact_id: str | None = None) -> Artifact | None:
        if not self.can_compose():
            return None
        if artifact_type is None:
            artifact_type = self.rng.choice(ARTIFACT_TYPES_BY_TIER.get(tier, ["label"]))
        phrase = self._compose(artifact_type)
        if phrase is None or not phrase.tokens:
            return None

        alien_text = " ".join(t.alien for t in phrase.tokens)
        breakdown = [WordBreakdown(alien=t.alien, english=t.gloss, grammar_note=t.note) for t in phrase.tokens]
        # Content words (nouns/verbs), de-duplicated, are what the artifact teaches.
        key_words: list[str] = []
        for t in phrase.tokens:
            if t.content and t.alien not in key_words:
                key_words.append(t.alien)

        if artifact_id is None:
            artifact_id = f"proc_{uuid.uuid4().hex[:8]}"
        title = f"{artifact_type.replace('_', ' ').title()} ({self.language.language_name})"

        return Artifact(
            id=artifact_id,
            title=title,
            artifact_type=artifact_type,
            alien_text=alien_text,
            english_translation=phrase.english,
            context_clues=[f"A {artifact_type} in {self.language.language_name}."],
            visual_description=f"A {artifact_type} of the {self.language.species_name}.",
            key_words=key_words,
            tier=tier,
            word_breakdown=breakdown,
            unlocked=(tier == 1),
        )


def generate_artifacts(language: GrowingLanguage, counts_by_tier: dict[int, int] | None = None,
                       seed: int | None = None) -> list[Artifact]:
    """Compose a batch of artifacts across tiers from a grown language.

    Returns whatever could be composed (may be shorter than requested if the
    lexicon is too small for a given tier's forms).
    """
    counts_by_tier = counts_by_tier or {1: 3, 2: 2}
    smith = ArtifactSmith(language, seed=seed)
    out: list[Artifact] = []
    for tier in sorted(counts_by_tier):
        for _ in range(counts_by_tier[tier]):
            artifact = smith.make(tier=tier)
            if artifact is not None:
                out.append(artifact)
    return out

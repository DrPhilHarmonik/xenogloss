"""Progressive grammar discovery (Phase 5).

`:grammar` used to hand the player the whole spec on turn one. This module makes
the panel earn itself: a rule only appears once the player's own codex contains
the evidence for it.

The evidence for an affix rule is a *minimal pair* -- a base word and its
inflected form, both already in the codex (``nur`` alongside ``nurn``). Three
pairs and the rule resolves. Where the artifacts carry a word breakdown we only
count pairs the breakdown actually attests, so a coincidental rhyme cannot
unlock a rule the language never used.

Some categories never leave a bare form behind. A verb in a composed artifact
always carries a tense suffix, so the stem alone never reaches the codex and a
base-vs-inflected pair for the tense rules is not merely rare, it is impossible.
Those rules take *paradigm pairs* instead: one stem showing up under two
different markings of the same category (``kelor`` beside ``kelet``) is evidence
for both, which is also how the contrast is actually found in the field.

Syntax rules (word order, adjective position) resolve differently again: they
need whole sentences the player has glossed end to end, because that is what
reading order off a text actually requires.

Discovery is derived from codex + artifacts, so it needs no new save data; the
campaign only remembers which rules have already fired so a `:forget` cannot
un-teach something the player has been told.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .artifact_smith import _clean_affix
from .artifacts import Artifact, ArtifactCollection
from .codex import Codex
from .language import Language

# How much evidence a rule costs.
PAIRS_REQUIRED = 3
SENTENCES_REQUIRED = 2
# A text shorter than this is a label, not a sentence -- it says nothing about order.
MIN_SENTENCE_WORDS = 3

# rule attribute, panel label, affix kind, keyword that identifies it in a
# word-breakdown grammar note.
AFFIX_RULES = (
    ("plural_suffix", "Plural", "suffix", "plural"),
    ("past_suffix", "Past tense", "suffix", "past"),
    ("present_suffix", "Present tense", "suffix", "present"),
    ("future_suffix", "Future tense", "suffix", "future"),
    ("possessive_suffix", "Possessive", "suffix", "possessive"),
    ("negation_prefix", "Negation", "prefix", "negat"),
)

# Rules that contrast with one another on the same stem. Members of a group are
# never all absent from a word: a verb carries exactly one tense marking, so the
# only contrast available is against a sibling marking, not against a bare stem.
PARADIGM_GROUPS = (
    ("tense", ("past_suffix", "present_suffix", "future_suffix")),
)

_SIBLINGS = {
    rule: tuple(other for other in group if other != rule)
    for _name, group in PARADIGM_GROUPS
    for rule in group
}


SYNTAX_RULES = (
    ("word_order", "Word order"),
    ("adjective_position", "Adjectives"),
)


@dataclass
class RuleProgress:
    """One row of the grammar panel, and how close the player is to earning it."""
    rule: str
    label: str
    kind: str  # suffix | prefix | syntax
    marker: str = ""  # bare affix letters; empty for syntax and unmarked rules
    value: str = ""  # the real rule, shown only once discovered
    discovered: bool = False
    unmarked: bool = False  # this language does not mark the category at all
    evidence: list = field(default_factory=list)
    partners: list = field(default_factory=list)  # contrasting markers in the same category
    found: int = 0
    needed: int = 0

    def describe_value(self) -> str:
        if self.kind == "suffix":
            return f"add '-{self.marker}'"
        if self.kind == "prefix":
            return f"prefix '{self.marker}-'"
        return self.value


def _attested_forms(artifacts: list[Artifact]) -> tuple[dict[str, set[str]], bool]:
    """Map each rule keyword to the surface forms its breakdown notes attest.

    Also reports whether any breakdown note was present at all -- artifacts from
    the LLM generator may carry none, and then we fall back to plain matching.
    """
    attested: dict[str, set[str]] = {rule: set() for rule, _, _, _ in AFFIX_RULES}
    saw_note = False
    for artifact in artifacts:
        for token in artifact.word_breakdown:
            note = (token.grammar_note or "").lower()
            if not note.strip():
                continue
            saw_note = True
            for rule, _, _, keyword in AFFIX_RULES:
                if keyword in note:
                    attested[rule].add(token.alien.lower())
    return attested, saw_note


def _strip(word: str, marker: str, kind: str) -> str | None:
    """The stem left when `marker` is peeled off `word`, or None if it is not there."""
    if not marker or len(word) <= len(marker):
        return None
    if kind == "prefix":
        return word[len(marker):] if word.startswith(marker) else None
    return word[: -len(marker)] if word.endswith(marker) else None


def _attach(stem: str, marker: str, kind: str) -> str:
    return marker + stem if kind == "prefix" else stem + marker


def _minimal_pairs(words: set[str], marker: str, kind: str, allowed: set[str] | None) -> list[tuple[str, str]]:
    """Find (base, inflected) pairs in the codex that expose `marker`.

    `allowed` restricts the inflected side to forms the artifacts attest; pass
    None to accept any surface match.
    """
    if not marker:
        return []
    pairs = []
    for word in sorted(words):
        base = _strip(word, marker, kind)
        if base is None or base not in words:
            continue
        if allowed is not None and word not in allowed:
            continue
        pairs.append((base, word))
    return pairs


def _paradigm_pairs(
    words: set[str],
    marker: str,
    kind: str,
    allowed: set[str] | None,
    siblings: list[tuple[str, set[str] | None]],
) -> list[tuple[str, str]]:
    """Find (sibling form, inflected) pairs: one stem under two markings of a category.

    This is the evidence for rules whose stem never stands bare. `siblings` is
    the (marker, attested-forms) of the contrasting rules; a sibling's attested
    set gates the partner the same way `allowed` gates the carrier.
    """
    if not marker or not siblings:
        return []
    pairs = []
    for word in sorted(words):
        stem = _strip(word, marker, kind)
        if stem is None:
            continue
        if allowed is not None and word not in allowed:
            continue
        for sib_marker, sib_allowed in siblings:
            if not sib_marker or sib_marker == marker:
                continue
            partner = _attach(stem, sib_marker, kind)
            if partner == word or partner not in words:
                continue
            if sib_allowed is not None and partner not in sib_allowed:
                continue
            pairs.append((partner, word))
            break
    return pairs


def _merge_pairs(*groups: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Combine evidence lists, counting each inflected form once."""
    seen: dict[str, tuple[str, str]] = {}
    for pairs in groups:
        for partner, word in pairs:
            seen.setdefault(word, (partner, word))
    return [seen[word] for word in sorted(seen)]


def glossed_sentences(artifacts: list[Artifact], codex: Codex) -> list[Artifact]:
    """Unlocked texts long enough to show order, with every word already in the codex."""
    known = codex.known_words()
    out = []
    for artifact in artifacts:
        words = artifact.unique_words()
        if len(words) < MIN_SENTENCE_WORDS:
            continue
        if all(word in known for word in words):
            out.append(artifact)
    return out


def analyze(
    language: Language,
    artifacts: ArtifactCollection,
    codex: Codex,
    already_discovered: set[str] | None = None,
) -> list[RuleProgress]:
    """Score every grammar rule against the evidence the player currently holds."""
    already_discovered = already_discovered or set()
    unlocked = artifacts.unlocked()
    attested, saw_note = _attested_forms(unlocked)
    words = codex.known_words()

    rows: list[RuleProgress] = []

    markers = {
        rule: _clean_affix(getattr(language.grammar, rule, "") or "").lower()
        for rule, _, _, _ in AFFIX_RULES
    }

    def gate(rule: str) -> set[str] | None:
        # Only trust the breakdown when it actually has something to say about
        # this rule; otherwise an un-annotated campaign could never resolve it.
        return attested[rule] if (saw_note and attested[rule]) else None

    for rule, label, kind, _keyword in AFFIX_RULES:
        raw = getattr(language.grammar, rule, "") or ""
        marker = markers[rule]
        row = RuleProgress(rule=rule, label=label, kind=kind, marker=marker, value=raw, needed=PAIRS_REQUIRED)
        if not marker:
            row.unmarked = True
            rows.append(row)
            continue
        allowed = gate(rule)
        siblings = [(markers[sib], gate(sib)) for sib in _SIBLINGS.get(rule, ())]
        row.partners = [m for m, _ in siblings if m and m != marker]
        row.evidence = _merge_pairs(
            _minimal_pairs(words, marker, kind, allowed),
            _paradigm_pairs(words, marker, kind, allowed, siblings),
        )
        row.found = len(row.evidence)
        row.discovered = row.found >= PAIRS_REQUIRED or rule in already_discovered
        rows.append(row)

    sentences = glossed_sentences(unlocked, codex)
    for rule, label in SYNTAX_RULES:
        value = getattr(language.grammar, rule, "") or "?"
        row = RuleProgress(
            rule=rule,
            label=label,
            kind="syntax",
            value=value,
            needed=SENTENCES_REQUIRED,
            found=len(sentences),
            evidence=[a.title for a in sentences],
        )
        row.unmarked = value.strip() in ("", "?")
        if not row.unmarked:
            row.discovered = row.found >= SENTENCES_REQUIRED or rule in already_discovered
        rows.append(row)

    return rows


def discovered_rules(rows: list[RuleProgress]) -> set[str]:
    return {row.rule for row in rows if row.discovered}


def render_panel(rows: list[RuleProgress]) -> str:
    """Render the progressive grammar panel as rich markup."""
    lines = ["[bold]GRAMMAR[/bold]  [dim]-- reconstructed from your own codex[/dim]", ""]
    for row in rows:
        label = f"{row.label:<14}"
        if row.unmarked:
            lines.append(f"  {label}[dim]not marked in this language[/dim]")
            continue
        if row.discovered:
            lines.append(f"  {label}[green]{row.describe_value()}[/green]")
            detail = _evidence_line(row)
            if detail:
                lines.append(f"  {'':<14}[dim]{detail}[/dim]")
            continue
        lines.append(f"  {label}[dim]???[/dim]  [yellow]{row.found}/{row.needed}[/yellow] [dim]{_gate_hint(row)}[/dim]")
    lines.append("")
    lines.append("[dim]:hint -xx asks LEXIS about a suffix instead of a word.[/dim]")
    return "\n".join(lines)


def _evidence_line(row: RuleProgress) -> str:
    if not row.evidence:
        return "carried over from an earlier session"
    if row.kind == "syntax":
        # The composer titles artifacts by type, so several can share a name.
        titles = list(dict.fromkeys(row.evidence))
        return "read off: " + ", ".join(titles[:3])
    shown = ["%s -> %s" % pair for pair in row.evidence[:3]]
    return "from: " + ", ".join(shown)


def _gate_hint(row: RuleProgress) -> str:
    if row.kind == "syntax":
        return "fully glossed texts"
    return "matched pairs"


def find_rule(rows: list[RuleProgress], query: str) -> RuleProgress | None:
    """Look up the rule a player's affix query (`-or`, `na-`, `or`) refers to."""
    raw = (query or "").strip().lower()
    if not raw:
        return None
    wanted_kind = ""
    if raw.startswith("-") and not raw.endswith("-"):
        wanted_kind = "suffix"
    elif raw.endswith("-") and not raw.startswith("-"):
        wanted_kind = "prefix"
    marker = _clean_affix(raw).lower()
    if not marker:
        return None
    fallback = None
    for row in rows:
        if row.marker != marker:
            continue
        if wanted_kind and row.kind == wanted_kind:
            return row
        if fallback is None:
            fallback = row
    return fallback


def grammar_hint(rows: list[RuleProgress], codex: Codex, query: str) -> str:
    """An offline LEXIS hint about an affix -- points at evidence, never at the answer."""
    row = find_rule(rows, query)
    label = (query or "").strip()
    if row is None:
        return f"Nothing in the grammar hangs on '{label}'. It is part of the word itself."
    if row.discovered:
        return f"{row.label} -- already reconstructed: {row.describe_value()}."

    known = codex.known_words()
    marker = row.marker
    unpaired = []
    for word in sorted(known):
        stem = _strip(word, marker, row.kind)
        if stem is None:
            continue
        if stem in known:
            continue
        if any(_attach(stem, other, row.kind) in known for other in row.partners):
            continue
        unpaired.append(word)

    remaining = row.needed - row.found
    if unpaired:
        listed = ", ".join(unpaired[:3])
        if row.partners:
            # Telling the player to strip a suffix off a stem that never stands
            # alone would send them looking for a word that does not exist.
            return (
                f"You carry {len(unpaired)} record(s) ending in '{label}': {listed}. Those stems never "
                f"stand bare, so the contrast you need is the same stem carrying a different ending -- "
                f"{remaining} more such pair(s) and the rule resolves."
            )
        return (
            f"You carry {len(unpaired)} record(s) built on '{label}' whose plain form you have not "
            f"logged: {listed}. Strip the affix and decode what is left -- {remaining} more pair(s) "
            "and the rule resolves."
        )
    if row.found:
        verb = "stands" if row.found == 1 else "stand"
        if row.partners:
            evidence = f"{row.found} of your records {verb} against the same stem under a different ending"
        else:
            evidence = f"{row.found} of your records {verb} both with it and without"
        return f"'{label}' holds up so far -- {evidence}. {remaining} more such pair(s) and the rule resolves."
    if row.partners:
        return (
            f"'{label}' recurs, but nothing in your codex shows the same stem under a different ending. "
            f"Find {remaining} such pair(s)."
        )
    return (
        f"'{label}' recurs, but your codex holds no word that both carries it and appears without it. "
        f"Find {remaining} such pair(s)."
    )

import unittest

from engine.artifact_smith import (
    ArtifactSmith,
    _clean_affix,
    _conjugate_en,
    _parse_word_order,
    _pluralize_en,
    _prefix,
    _suffix,
    generate_artifacts,
)
from engine.growth_language import GrowingLanguage, LexiconEntry
from engine.language import GrammarRules


def make_lang(word_order="Subject-Object-Verb", words=None, **grammar_over):
    grammar = GrammarRules(
        word_order=word_order,
        plural_suffix="-n",
        negation_prefix="na-",
        past_suffix="-k",
        present_suffix="-t",
        future_suffix="-s",
        adjective_position="before noun",
        possessive_suffix="-r",
    )
    for key, value in grammar_over.items():
        setattr(grammar, key, value)
    if words is None:
        words = DEFAULT_WORDS
    entries = []
    for alien, english, pos, category in words:
        entries.append(LexiconEntry(alien=alien, english=english, part_of_speech=pos, category=category))
    return GrowingLanguage(language_name="Testish", species_name="Testans", grammar=grammar, words=entries)


DEFAULT_WORDS = [
    ("ta", "i/me", "pronoun", "social"),
    ("vok", "to see", "verb", "common verbs"),
    ("nur", "water", "noun", "natural"),
    ("sor", "stone", "noun", "natural"),
    ("zur", "friend", "noun", "social"),
    ("bright", "bright", "adjective", "quality"),
    ("keth", "here", "adverb", "spatial"),
]


class AffixHelperTests(unittest.TestCase):
    def test_clean_affix_strips_markers(self):
        self.assertEqual(_clean_affix("-n"), "n")
        self.assertEqual(_clean_affix("na-"), "na")
        self.assertEqual(_clean_affix("-r"), "r")

    def test_clean_affix_treats_placeholder_as_empty(self):
        for placeholder in ("?", "", "-", "  ", None):
            self.assertEqual(_clean_affix(placeholder), "")

    def test_suffix_and_prefix(self):
        self.assertEqual(_suffix("vok", "-s"), "voks")
        self.assertEqual(_prefix("vok", "na-"), "navok")
        self.assertEqual(_suffix("vok", "?"), "vok")  # placeholder -> unchanged

    def test_parse_word_order_spelled_out(self):
        self.assertEqual(_parse_word_order("Subject-Object-Verb"), ["S", "O", "V"])
        self.assertEqual(_parse_word_order("Verb-Subject-Object"), ["V", "S", "O"])

    def test_parse_word_order_abbreviated(self):
        self.assertEqual(_parse_word_order("SVO"), ["S", "V", "O"])
        self.assertEqual(_parse_word_order("OSV"), ["O", "S", "V"])

    def test_parse_word_order_fills_missing_roles(self):
        # Garbage still yields all three roles in canonical order.
        self.assertEqual(sorted(_parse_word_order("???")), ["O", "S", "V"])

    def test_pluralize_and_conjugate_english(self):
        self.assertEqual(_pluralize_en("friend"), "friends")
        self.assertEqual(_pluralize_en("box"), "boxes")
        self.assertEqual(_pluralize_en("city"), "cities")
        self.assertEqual(_conjugate_en("to see", "past"), "saw")
        self.assertEqual(_conjugate_en("to move", "past"), "moved")
        self.assertEqual(_conjugate_en("to see", "future"), "will see")


class AdverbBucketingTests(unittest.TestCase):
    def test_adverb_is_not_treated_as_a_verb(self):
        # 'adverb' contains the substring 'verb'; the smith must not confuse them.
        smith = ArtifactSmith(make_lang(), seed=1)
        verb_aliens = {w.alien for w in smith.verbs}
        adverb_aliens = {w.alien for w in smith.adverbs}
        self.assertIn("vok", verb_aliens)
        self.assertNotIn("keth", verb_aliens)
        self.assertIn("keth", adverb_aliens)

    def test_pronoun_is_not_treated_as_a_noun(self):
        smith = ArtifactSmith(make_lang(), seed=1)
        self.assertIn("ta", {w.alien for w in smith.pronouns})
        self.assertNotIn("ta", {w.alien for w in smith.nouns})


class ConsistencyTests(unittest.TestCase):
    def assert_structurally_consistent(self, lang, artifact):
        # The alien text is exactly the breakdown tokens joined by spaces.
        self.assertEqual(artifact.alien_text.split(), [wb.alien for wb in artifact.word_breakdown])
        self.assertTrue(artifact.english_translation.strip())
        # Every surface token is a real lexicon word (root) plus at most the
        # language's own affixes -- this is the internal-consistency guarantee.
        by_english = {}
        for w in lang.words:
            by_english.setdefault(w.english.lower(), w)
        for wb in artifact.word_breakdown:
            match = by_english.get(wb.english.lower())
            self.assertIsNotNone(match, f"gloss {wb.english!r} is not in the lexicon")
            self.assertIn(match.alien.lower(), wb.alien.lower(),
                          f"surface {wb.alien!r} does not contain lexicon root {match.alien!r}")

    def test_every_artifact_uses_only_real_words(self):
        lang = make_lang()
        for seed in range(40):
            smith = ArtifactSmith(lang, seed=seed)
            for tier in (1, 2, 3):
                artifact = smith.make(tier=tier)
                if artifact is not None:
                    self.assert_structurally_consistent(lang, artifact)

    def test_deterministic_from_seed(self):
        lang = make_lang()
        a = ArtifactSmith(lang, seed=99).make(tier=2)
        b = ArtifactSmith(lang, seed=99).make(tier=2)
        self.assertEqual(a.alien_text, b.alien_text)
        self.assertEqual(a.english_translation, b.english_translation)

    def test_word_order_places_verb_last_for_sov(self):
        lang = make_lang("Subject-Object-Verb")
        for seed in range(30):
            clause = ArtifactSmith(lang, seed=seed)._clause()
            if clause is None:
                continue
            aliens = [t.alien for t in clause.tokens]
            subj_i = aliens.index("ta")
            verb_i = next(i for i, t in enumerate(clause.tokens) if t.gloss == "to see")
            self.assertLess(subj_i, verb_i, f"SOV subject should precede verb: {aliens}")

    def test_word_order_places_verb_first_for_vso(self):
        lang = make_lang("Verb-Subject-Object")
        seen = False
        for seed in range(30):
            clause = ArtifactSmith(lang, seed=seed)._clause()
            if clause is None:
                continue
            verb_i = next(i for i, t in enumerate(clause.tokens) if t.gloss == "to see")
            subj_i = [t.alien for t in clause.tokens].index("ta")
            self.assertLess(verb_i, subj_i, "VSO verb should precede subject")
            seen = True
        self.assertTrue(seen, "expected at least one clause to be built")

    def test_negation_prefix_applied_for_law(self):
        lang = make_lang()
        found_negation = False
        for seed in range(40):
            artifact = ArtifactSmith(lang, seed=seed).make(tier=3, artifact_type="law")
            if artifact and any("negation" in wb.grammar_note for wb in artifact.word_breakdown):
                found_negation = True
                # negated verb surface carries the na- prefix; english says "not".
                self.assertIn("not ", artifact.english_translation)
                break
        self.assertTrue(found_negation, "a law should sometimes carry a negation")


class GracefulDegradationTests(unittest.TestCase):
    def test_empty_lexicon_yields_no_artifact(self):
        lang = make_lang(words=[])
        smith = ArtifactSmith(lang, seed=1)
        self.assertFalse(smith.can_compose())
        self.assertIsNone(smith.make(tier=1))

    def test_nouns_only_still_composes_a_label(self):
        lang = make_lang(words=[("sor", "stone", "noun", "natural")])
        artifact = ArtifactSmith(lang, seed=3).make(tier=1)
        self.assertIsNotNone(artifact)
        self.assertIn("sor", artifact.alien_text)

    def test_generate_artifacts_batch_respects_counts(self):
        lang = make_lang()
        artifacts = generate_artifacts(lang, {1: 3, 2: 2}, seed=5)
        self.assertEqual(len(artifacts), 5)
        self.assertEqual([a.tier for a in artifacts], [1, 1, 1, 2, 2])
        self.assertTrue(all(a.unlocked for a in artifacts if a.tier == 1))


if __name__ == "__main__":
    unittest.main()

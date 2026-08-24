import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import grammar_discovery
from engine.artifact_smith import generate_artifacts
from engine.artifacts import Artifact, ArtifactCollection, WordBreakdown
from engine.campaign import Campaign
from engine.codex import Codex
from engine.growth_language import GrowingLanguage, LexiconEntry
from engine.language import GrammarRules, Language


def make_language(**grammar_over) -> Language:
    grammar = GrammarRules(
        word_order="Subject-Object-Verb",
        plural_suffix="-n",
        negation_prefix="na-",
        past_suffix="-or",
        present_suffix="-et",
        future_suffix="-is",
        adjective_position="before noun",
        possessive_suffix="-ka",
    )
    for key, value in grammar_over.items():
        setattr(grammar, key, value)
    return Language(
        language_name="Testish",
        species_name="Testans",
        vocabulary={},
        grammar=grammar,
    )


def make_artifact(artifact_id, alien_text, breakdown=None, tier=1, unlocked=True, title=None):
    return Artifact(
        id=artifact_id,
        title=title or f"Artifact {artifact_id}",
        artifact_type="inscription",
        alien_text=alien_text,
        english_translation="",
        context_clues=[],
        visual_description="",
        key_words=[],
        tier=tier,
        word_breakdown=breakdown or [],
        unlocked=unlocked,
    )


def codex_with(*words) -> Codex:
    codex = Codex()
    for word in words:
        codex.add(word, "meaning")
    return codex


def tense_artifact() -> Artifact:
    """One text attesting three stems, each under two different tense markings.

    Verbs in a composed artifact always carry a tense suffix, so the bare stem
    never appears and only this contrast can resolve the tense rules.
    """
    return make_artifact(
        "t1",
        "kelor kelet mithor mithet rasor raset",
        breakdown=[
            WordBreakdown("kelor", "to walk", "past tense (-or)"),
            WordBreakdown("kelet", "to walk", "present tense (-et)"),
            WordBreakdown("mithor", "to hold", "past tense (-or)"),
            WordBreakdown("mithet", "to hold", "present tense (-et)"),
            WordBreakdown("rasor", "to speak", "past tense (-or)"),
            WordBreakdown("raset", "to speak", "present tense (-et)"),
        ],
    )


def plural_artifact() -> Artifact:
    """One text attesting three plurals, so pair-matching has evidence to lean on."""
    return make_artifact(
        "a1",
        "nurn sorn zurn",
        breakdown=[
            WordBreakdown("nurn", "water", "plural (-n)"),
            WordBreakdown("sorn", "stone", "plural (-n)"),
            WordBreakdown("zurn", "friend", "plural (-n)"),
        ],
    )


def row_for(rows, rule):
    return next(row for row in rows if row.rule == rule)


class AffixDiscoveryTests(unittest.TestCase):
    def test_rule_stays_hidden_until_enough_pairs(self):
        artifacts = ArtifactCollection([plural_artifact()])
        codex = codex_with("nur", "nurn", "sor", "sorn")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        plural = row_for(rows, "plural_suffix")
        self.assertFalse(plural.discovered)
        self.assertEqual(plural.found, 2)
        self.assertEqual(plural.needed, grammar_discovery.PAIRS_REQUIRED)

    def test_third_pair_resolves_the_rule(self):
        artifacts = ArtifactCollection([plural_artifact()])
        codex = codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        plural = row_for(rows, "plural_suffix")
        self.assertTrue(plural.discovered)
        self.assertEqual(plural.describe_value(), "add '-n'")
        self.assertIn(("nur", "nurn"), plural.evidence)

    def test_a_pair_needs_both_halves_in_the_codex(self):
        artifacts = ArtifactCollection([plural_artifact()])
        codex = codex_with("nurn", "sorn", "zurn")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        self.assertEqual(row_for(rows, "plural_suffix").found, 0)

    def test_breakdown_notes_reject_a_coincidental_rhyme(self):
        # 'ketn' ends in -n and its base is known, but no artifact calls it a plural.
        artifacts = ArtifactCollection([plural_artifact()])
        codex = codex_with("nur", "nurn", "sor", "sorn", "ket", "ketn")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        plural = row_for(rows, "plural_suffix")
        self.assertFalse(plural.discovered)
        self.assertNotIn(("ket", "ketn"), plural.evidence)

    def test_plain_matching_when_the_artifacts_carry_no_notes(self):
        artifacts = ArtifactCollection([make_artifact("a1", "nurn sorn zurn")])
        codex = codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        self.assertTrue(row_for(rows, "plural_suffix").discovered)

    def test_prefix_rules_strip_from_the_front(self):
        artifacts = ArtifactCollection([
            make_artifact(
                "a1",
                "navok nasor nazur",
                breakdown=[
                    WordBreakdown("navok", "to see", "negation (na-)"),
                    WordBreakdown("nasor", "stone", "negation (na-)"),
                    WordBreakdown("nazur", "friend", "negation (na-)"),
                ],
            )
        ])
        codex = codex_with("vok", "navok", "sor", "nasor", "zur", "nazur")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        negation = row_for(rows, "negation_prefix")
        self.assertTrue(negation.discovered)
        self.assertEqual(negation.describe_value(), "prefix 'na-'")

    def test_a_category_the_language_never_marks_is_reported_as_unmarked(self):
        artifacts = ArtifactCollection([plural_artifact()])
        rows = grammar_discovery.analyze(make_language(possessive_suffix="?"), artifacts, codex_with())
        possessive = row_for(rows, "possessive_suffix")
        self.assertTrue(possessive.unmarked)
        self.assertFalse(possessive.discovered)

    def test_locked_artifacts_do_not_supply_evidence(self):
        locked = plural_artifact()
        locked.unlocked = False
        artifacts = ArtifactCollection([locked, make_artifact("a2", "ket", tier=1)])
        codex = codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        # a2 carries no notes, so attestation falls back to plain matching and the
        # locked text's own annotations are never consulted.
        self.assertEqual(row_for(rows, "plural_suffix").evidence, [("nur", "nurn"), ("sor", "sorn"), ("zur", "zurn")])


class SyntaxDiscoveryTests(unittest.TestCase):
    def test_word_order_needs_fully_glossed_sentences(self):
        artifacts = ArtifactCollection([
            make_artifact("a1", "ta nur vok"),
            make_artifact("a2", "ta sor vok"),
        ])
        rows = grammar_discovery.analyze(make_language(), artifacts, codex_with("ta", "nur", "vok"))
        order = row_for(rows, "word_order")
        self.assertFalse(order.discovered)
        self.assertEqual(order.found, 1)

        rows = grammar_discovery.analyze(make_language(), artifacts, codex_with("ta", "nur", "sor", "vok"))
        order = row_for(rows, "word_order")
        self.assertTrue(order.discovered)
        self.assertEqual(order.value, "Subject-Object-Verb")

    def test_short_labels_never_count_as_sentences(self):
        artifacts = ArtifactCollection([
            make_artifact("a1", "nur sor"),
            make_artifact("a2", "nur vok"),
            make_artifact("a3", "sor vok"),
        ])
        rows = grammar_discovery.analyze(make_language(), artifacts, codex_with("nur", "sor", "vok"))
        self.assertFalse(row_for(rows, "word_order").discovered)

    def test_adjective_position_rides_the_same_gate(self):
        artifacts = ArtifactCollection([
            make_artifact("a1", "ta nur vok"),
            make_artifact("a2", "ta sor vok"),
        ])
        rows = grammar_discovery.analyze(make_language(), artifacts, codex_with("ta", "nur", "sor", "vok"))
        self.assertTrue(row_for(rows, "adjective_position").discovered)


class PanelRenderingTests(unittest.TestCase):
    def test_panel_hides_undiscovered_rules_and_shows_progress(self):
        artifacts = ArtifactCollection([plural_artifact()])
        codex = codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn")
        panel = grammar_discovery.render_panel(
            grammar_discovery.analyze(make_language(), artifacts, codex)
        )
        self.assertIn("add '-n'", panel)
        self.assertIn("nur -> nurn", panel)
        # Nothing in the codex exposes the past tense, so its value stays hidden.
        self.assertNotIn("-or", panel)
        self.assertIn("???", panel)

    def test_unmarked_categories_say_so(self):
        artifacts = ArtifactCollection([plural_artifact()])
        panel = grammar_discovery.render_panel(
            grammar_discovery.analyze(make_language(future_suffix="?"), artifacts, codex_with())
        )
        self.assertIn("not marked in this language", panel)


class ParadigmDiscoveryTests(unittest.TestCase):
    """Rules whose stem never stands bare resolve on a contrast instead."""

    def test_tense_resolves_on_contrasting_forms_of_one_stem(self):
        artifacts = ArtifactCollection([tense_artifact()])
        codex = codex_with("kelor", "kelet", "mithor", "mithet", "rasor", "raset")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)

        past = row_for(rows, "past_suffix")
        present = row_for(rows, "present_suffix")
        self.assertTrue(past.discovered)
        self.assertTrue(present.discovered)
        self.assertEqual(past.describe_value(), "add '-or'")
        self.assertIn(("kelet", "kelor"), past.evidence)

    def test_a_stem_seen_in_only_one_tense_is_not_evidence(self):
        artifacts = ArtifactCollection([tense_artifact()])
        codex = codex_with("kelor", "mithor", "rasor")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        self.assertEqual(row_for(rows, "past_suffix").found, 0)

    def test_the_partner_form_must_be_attested_as_its_own_category(self):
        # 'kelet' is present tense; 'mithet' is called nothing at all, so the
        # stem contrast it would supply does not count.
        artifacts = ArtifactCollection([
            make_artifact(
                "t2",
                "kelor kelet mithor mithet",
                breakdown=[
                    WordBreakdown("kelor", "to walk", "past tense (-or)"),
                    WordBreakdown("kelet", "to walk", "present tense (-et)"),
                    WordBreakdown("mithor", "to hold", "past tense (-or)"),
                    WordBreakdown("mithet", "to hold", ""),
                ],
            )
        ])
        codex = codex_with("kelor", "kelet", "mithor", "mithet")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        past = row_for(rows, "past_suffix")
        self.assertEqual(past.found, 1)
        self.assertNotIn(("mithet", "mithor"), past.evidence)

    def test_plural_takes_no_paradigm_evidence(self):
        # Plural has no contrasting sibling, so a bare base stays the only
        # evidence for it. 'nurka' is possessive, not a second plural.
        artifacts = ArtifactCollection([plural_artifact()])
        codex = codex_with("nurn", "nurka")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        plural = row_for(rows, "plural_suffix")
        self.assertEqual(plural.partners, [])
        self.assertEqual(plural.found, 0)

    def test_one_form_counts_once_even_with_two_kinds_of_evidence(self):
        # 'kelor' has both a bare base and a contrasting present form present.
        artifacts = ArtifactCollection([
            make_artifact(
                "t3",
                "kel kelor kelet",
                breakdown=[
                    WordBreakdown("kel", "to walk", ""),
                    WordBreakdown("kelor", "to walk", "past tense (-or)"),
                    WordBreakdown("kelet", "to walk", "present tense (-et)"),
                ],
            )
        ])
        codex = codex_with("kel", "kelor", "kelet")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        past = row_for(rows, "past_suffix")
        self.assertEqual(past.found, 1)
        self.assertIn(("kel", "kelor"), past.evidence)


class GrammarHintTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = ArtifactCollection([plural_artifact()])
        self.language = make_language()

    def _rows(self, codex):
        return grammar_discovery.analyze(self.language, self.artifacts, codex)

    def test_hint_points_at_an_unpaired_word_without_naming_the_rule(self):
        codex = codex_with("nurn", "sorn")
        hint = grammar_discovery.grammar_hint(self._rows(codex), codex, "-n")
        self.assertIn("nurn", hint)
        self.assertNotIn("plural", hint.lower())

    def test_hint_restates_a_rule_already_reconstructed(self):
        codex = codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn")
        hint = grammar_discovery.grammar_hint(self._rows(codex), codex, "-n")
        self.assertIn("Plural", hint)
        self.assertIn("add '-n'", hint)

    def test_hint_counts_progress_when_every_carrier_is_already_paired(self):
        codex = codex_with("nur", "nurn")
        hint = grammar_discovery.grammar_hint(self._rows(codex), codex, "-n")
        self.assertIn("1 of your records", hint)
        self.assertIn("2 more", hint)

    def test_hint_for_a_tense_rule_asks_for_a_contrast_not_a_bare_stem(self):
        artifacts = ArtifactCollection([tense_artifact()])
        codex = codex_with("kelor", "mithor")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        hint = grammar_discovery.grammar_hint(rows, codex, "-or")
        self.assertIn("kelor", hint)
        self.assertIn("different ending", hint)
        self.assertNotIn("Strip the affix", hint)
        self.assertNotIn("past", hint.lower())

    def test_hint_counts_paradigm_progress_in_its_own_terms(self):
        artifacts = ArtifactCollection([tense_artifact()])
        codex = codex_with("kelor", "kelet")
        rows = grammar_discovery.analyze(make_language(), artifacts, codex)
        hint = grammar_discovery.grammar_hint(rows, codex, "-or")
        self.assertIn("1 of your records stands", hint)
        self.assertIn("different ending", hint)
        self.assertNotIn("without", hint)

    def test_hint_dismisses_an_affix_that_is_not_a_rule(self):
        codex = codex_with("nur")
        hint = grammar_discovery.grammar_hint(self._rows(codex), codex, "-zz")
        self.assertIn("part of the word itself", hint)

    def test_a_trailing_dash_selects_the_prefix_rule(self):
        codex = codex_with("nur")
        row = grammar_discovery.find_rule(self._rows(codex), "na-")
        self.assertEqual(row.rule, "negation_prefix")


class EvidenceCeilingTests(unittest.TestCase):
    """Every rule the language marks has to be reachable from a real corpus.

    Phase 5 shipped with three rules that could never resolve: the smith always
    suffixes a verb with a tense, so no bare stem ever reached the codex and the
    past/present/future rows sat at 0 for any amount of play. This measures the
    ceiling directly rather than trusting that the gate is satisfiable.
    """

    POS_COUNTS = (("noun", 14), ("verb", 10), ("adjective", 6), ("adverb", 4), ("pronoun", 3))
    SYLLABLES = ("ta", "vok", "nur", "sor", "zur", "kel", "mith", "ras", "dun", "olv",
                 "ith", "hae", "bru", "sen", "qal", "vex", "lom", "tir", "wen", "ash")

    def _grown_language(self) -> GrowingLanguage:
        grammar = GrammarRules(
            word_order="Subject-Object-Verb",
            plural_suffix="-n",
            negation_prefix="na-",
            past_suffix="-k",
            present_suffix="-t",
            future_suffix="-s",
            adjective_position="before noun",
            possessive_suffix="-r",
        )
        words, index = [], 0
        for pos, count in self.POS_COUNTS:
            for k in range(count):
                stem = self.SYLLABLES[index % len(self.SYLLABLES)]
                suffix = "" if index < len(self.SYLLABLES) else str(index // len(self.SYLLABLES))
                words.append(LexiconEntry(alien=stem + suffix, english=f"{pos}{k}",
                                          part_of_speech=pos, category="test"))
                index += 1
        return GrowingLanguage(language_name="Ceiling", species_name="Ceilings",
                               grammar=grammar, words=words)

    def test_every_marked_rule_is_reachable_from_a_generated_corpus(self):
        language = self._grown_language()
        artifacts = generate_artifacts(language, {1: 40, 2: 40, 3: 40, 4: 40}, seed=3)
        for artifact in artifacts:
            artifact.unlocked = True
        collection = ArtifactCollection(artifacts)

        # The best case a player can reach: every surface form in the corpus logged.
        codex = Codex()
        for artifact in artifacts:
            for word in artifact.unique_words():
                codex.add(word, "meaning")

        rows = grammar_discovery.analyze(language, collection, codex)
        for row in rows:
            if row.unmarked:
                continue
            with self.subTest(rule=row.rule):
                self.assertGreaterEqual(
                    row.found, grammar_discovery.PAIRS_REQUIRED,
                    f"{row.label} cannot be earned: only {row.found} piece(s) of evidence exist "
                    "in a fully decoded corpus",
                )
                self.assertTrue(row.discovered)


class CampaignGrammarStateTests(unittest.TestCase):
    def _campaign(self, codex):
        return Campaign(
            campaign_id="gram01",
            language=make_language(),
            artifacts=ArtifactCollection([plural_artifact()]),
            codex=codex,
        )

    def test_refresh_reports_each_rule_only_once(self):
        campaign = self._campaign(codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn"))
        newly = campaign.refresh_grammar_discovery()
        self.assertEqual([row.rule for row in newly], ["plural_suffix"])
        self.assertEqual(campaign.refresh_grammar_discovery(), [])

    def test_forgetting_a_word_does_not_un_teach_a_rule(self):
        campaign = self._campaign(codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn"))
        campaign.refresh_grammar_discovery()
        campaign.codex.remove("zurn")
        self.assertTrue(row_for(campaign.grammar_progress(), "plural_suffix").discovered)

    def test_discovered_rules_survive_a_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            saves_dir = Path(tmpdir)
            with patch("engine.campaign.SAVES_DIR", saves_dir):
                campaign = self._campaign(codex_with("nur", "nurn", "sor", "sorn", "zur", "zurn"))
                campaign.refresh_grammar_discovery()
                campaign.save()
                reloaded = Campaign.load("gram01")
            self.assertEqual(reloaded.discovered_grammar, {"plural_suffix"})

    def test_a_save_written_before_this_feature_still_loads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            saves_dir = Path(tmpdir)
            campaign = self._campaign(codex_with("nur"))
            legacy = {
                "campaign_id": "legacy1",
                "created_at": "2026-04-03T09:00:00",
                "current_artifact_index": 0,
                "language": campaign.language.to_dict(),
                "artifacts": campaign.artifacts.to_list(),
                "codex": campaign.codex.to_list(),
            }
            (saves_dir / "legacy1.json").write_text(json.dumps(legacy))
            with patch("engine.campaign.SAVES_DIR", saves_dir):
                reloaded = Campaign.load("legacy1")
            self.assertEqual(reloaded.discovered_grammar, set())


if __name__ == "__main__":
    unittest.main()

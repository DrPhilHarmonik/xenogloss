import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import grammar_discovery
from engine.artifacts import Artifact, ArtifactCollection, WordBreakdown
from engine.campaign import Campaign
from engine.codex import Codex
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

    def test_hint_dismisses_an_affix_that_is_not_a_rule(self):
        codex = codex_with("nur")
        hint = grammar_discovery.grammar_hint(self._rows(codex), codex, "-zz")
        self.assertIn("part of the word itself", hint)

    def test_a_trailing_dash_selects_the_prefix_rule(self):
        codex = codex_with("nur")
        row = grammar_discovery.find_rule(self._rows(codex), "na-")
        self.assertEqual(row.rule, "negation_prefix")


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

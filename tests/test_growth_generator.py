import unittest
from pathlib import Path
from unittest.mock import patch

from engine.growth_generator import (
    GrowthValidationError,
    _dedupe_words,
    _fit_to_count,
    _min_multisyllabic,
    _missing_words_prompt,
    _prune_seed_batch,
    _repair_request_size,
    _repair_word_batch,
    _seed_shape_gaps,
    _trim_short_roots,
)
from engine.growth_language import LexiconEntry


def make_word(alien: str, english: str) -> LexiconEntry:
    return LexiconEntry(
        alien=alien,
        english=english,
        part_of_speech="noun",
        category="test",
        created_on="2026-04-15",
        source="seed",
    )


class GrowthRepairTests(unittest.TestCase):
    def test_dedupe_words_keeps_first_unique_pairs(self):
        words = [
            make_word("lor", "person"),
            make_word("lor", "human"),
            make_word("sor", "person"),
            make_word("vau", "water"),
        ]

        unique = _dedupe_words(words)

        self.assertEqual([(word.alien, word.english) for word in unique], [("lor", "person"), ("vau", "water")])

    def test_repair_word_batch_fills_missing_unique_entries(self):
        initial = [
            make_word("lor", "person"),
            make_word("lor", "human"),
            make_word("sor", "person"),
        ]
        repair_payload = {
            "seed_words": [
                {
                    "alien": "vau",
                    "english": "water",
                    "part_of_speech": "noun",
                    "category": "natural elements",
                    "notes": "",
                    "example_alien": "vau lor",
                    "example_english": "person water",
                },
                {
                    "alien": "rai",
                    "english": "eat",
                    "part_of_speech": "verb",
                    "category": "common verbs",
                    "notes": "",
                    "example_alien": "lor rai",
                    "example_english": "person eats",
                },
            ]
        }

        with patch("engine.growth_generator._generate_structured_json", return_value=repair_payload):
            repaired = _repair_word_batch(
                prompt="seed prompt",
                schema_name="seed language",
                list_key="seed_words",
                expected_count=3,
                candidates=initial,
                created_on="2026-04-15",
                source="seed",
                retries=1,
            )

        self.assertEqual([(word.alien, word.english) for word in repaired], [("lor", "person"), ("vau", "water"), ("rai", "eat")])


def make_seed_word(alien: str, english: str, category: str, part_of_speech: str = "noun") -> LexiconEntry:
    return LexiconEntry(
        alien=alien,
        english=english,
        part_of_speech=part_of_speech,
        category=category,
        created_on="2026-04-15",
        source="seed",
    )


class SeedShapeRepairTests(unittest.TestCase):
    def test_seed_prompt_quota_matches_validator(self):
        prompt = Path(__file__).parent.parent / "prompts" / "growth_init.txt"
        self.assertIn("At least {MIN_MULTISYLLABIC} of the {SEED_WORD_COUNT}", prompt.read_text())
        self.assertEqual(_min_multisyllabic(24), 14)
        self.assertEqual(_min_multisyllabic(5), 2)

    def test_trim_short_roots_makes_room_for_quota(self):
        words = [
            make_seed_word("ka", "i", "pronouns", "pronoun"),
            make_seed_word("tu", "you", "pronouns", "pronoun"),
            make_seed_word("vek", "water", "natural elements"),
            make_seed_word("sol", "stone", "natural elements"),
            make_seed_word("rin", "hand", "body"),
            make_seed_word("mek", "foot", "body"),
            make_seed_word("dal", "fire", "natural elements"),
            make_seed_word("pom", "cup", "tools"),
        ]

        kept = _trim_short_roots(words, expected_count=8)

        aliens = [word.alien for word in kept]
        self.assertEqual(8 - len(kept), _min_multisyllabic(8))
        self.assertIn("ka", aliens)
        self.assertIn("tu", aliens)
        self.assertIn("vek", aliens)
        self.assertIn("rin", aliens)

    def test_prune_seed_batch_drops_calque_glosses(self):
        words = [
            make_seed_word("ka", "i", "pronouns", "pronoun"),
            make_seed_word("velora", "water", "natural elements"),
            make_seed_word("nasoru", "not speak", "common verbs", "verb"),
            make_seed_word("timesh", "stone", "natural elements"),
        ]

        pruned = _prune_seed_batch(words, expected_count=4)

        self.assertEqual([word.alien for word in pruned], ["ka", "velora", "timesh"])

    def test_trim_short_roots_leaves_valid_sets_alone(self):
        words = [
            make_seed_word("ka", "i", "pronouns", "pronoun"),
            make_seed_word("velora", "water", "natural elements"),
            make_seed_word("timesh", "stone", "natural elements"),
        ]

        self.assertEqual(_trim_short_roots(words, expected_count=3), words)

    def test_seed_shape_gaps_lists_missing_requirements(self):
        words = [
            make_seed_word("ka", "i", "pronouns", "pronoun"),
            make_seed_word("vek", "water", "natural elements"),
            make_seed_word("sorun", "eat", "common verbs", "verb"),
        ]

        gaps = _seed_shape_gaps(words, expected_count=24)

        self.assertIn("at least 13 words of 2-3 syllables", gaps)
        self.assertIn('at least 1 word(s) with category "pronouns"', gaps)
        self.assertIn('at least 2 word(s) with category "numbers"', gaps)
        self.assertIn("at least 3 more verb(s)", gaps)
        self.assertFalse(any("natural elements" in gap for gap in gaps))

    def test_missing_words_prompt_includes_requirements(self):
        prompt = _missing_words_prompt(
            count=4,
            existing_words=[make_seed_word("ka", "i", "pronouns", "pronoun")],
            schema_name="seed language",
            list_key="seed_words",
            base_prompt="seed prompt",
            requirements=["at least 2 words of 2-3 syllables"],
        )

        self.assertIn("The 4 new entries must together include:\n- at least 2 words of 2-3 syllables", prompt)

    def test_repair_word_batch_passes_requirements_to_prompt(self):
        initial = [make_word("lor", "person")]
        repair_payload = {"seed_words": [{"alien": "velora", "english": "water", "part_of_speech": "noun", "category": "test"}]}

        with patch("engine.growth_generator._generate_structured_json", return_value=repair_payload) as generate:
            _repair_word_batch(
                prompt="seed prompt",
                schema_name="seed language",
                list_key="seed_words",
                expected_count=2,
                candidates=initial,
                created_on="2026-04-15",
                source="seed",
                retries=0,
                requirements_fn=lambda batch: ["at least 1 words of 2-3 syllables"],
            )

        self.assertIn("- at least 1 words of 2-3 syllables", generate.call_args.args[0])

    def test_repair_requests_extra_entries(self):
        self.assertEqual(_repair_request_size(1), 3)
        self.assertEqual(_repair_request_size(10), 15)

        with patch("engine.growth_generator._generate_structured_json", return_value={"seed_words": []}) as generate:
            with self.assertRaises(GrowthValidationError):
                _repair_word_batch(
                    prompt="seed prompt",
                    schema_name="seed language",
                    list_key="seed_words",
                    expected_count=4,
                    candidates=[make_word("lor", "person")],
                    created_on="2026-04-15",
                    source="seed",
                    retries=0,
                )

        self.assertIn("return 5 new seed_words", generate.call_args.args[0])

    def test_fit_to_count_keeps_entries_that_close_gaps(self):
        words = [
            make_seed_word("ka", "i", "pronouns", "pronoun"),
            make_seed_word("velora", "water", "natural elements"),
            make_seed_word("sorun", "river", "natural elements"),
            make_seed_word("tu", "you", "pronouns", "pronoun"),
            make_seed_word("mirav", "stone", "natural elements"),
        ]

        def requirements(batch):
            pronouns = sum(1 for word in batch if word.part_of_speech == "pronoun")
            return [] if pronouns >= 2 else ["at least 2 pronouns"]

        fitted = _fit_to_count(words, expected_count=3, requirements_fn=requirements)

        self.assertEqual([word.alien for word in fitted], ["ka", "velora", "tu"])


if __name__ == "__main__":
    unittest.main()

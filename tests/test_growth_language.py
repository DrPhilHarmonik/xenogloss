import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from engine.growth_generator import (
    GrowthValidationError,
    _seed_prompt_for_archetype,
    _seed_prompt_variant,
    _validate_seed_language_shape,
    days_to_target,
    generate_daily_growth,
    generate_seed_language,
)
from engine.growth_language import GrowingLanguage, LexiconEntry


class GrowingLanguagePersistenceTests(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            language = GrowingLanguage(
                language_id="lang123",
                language_name="Talune",
                species_name="Motes",
                growth_words_per_day=5,
                target_lexicon_size=50,
                words=[LexiconEntry(alien="vek", english="water", created_on="2026-04-14")],
            )

            with patch("engine.growth_language.GROWING_LANGUAGES_DIR", Path(tmpdir)):
                language.save()
                loaded = GrowingLanguage.load("lang123")

            self.assertEqual(loaded.language_name, "Talune")
            self.assertEqual(loaded.words[0].alien, "vek")

    def test_add_words_blocks_duplicate_day_without_force(self):
        language = GrowingLanguage(last_growth_on="2026-04-14")

        with self.assertRaisesRegex(ValueError, "already grew"):
            language.add_words(
                [LexiconEntry(alien="vek", english="water")],
                growth_day=date(2026, 4, 14),
            )

    def test_add_words_skips_duplicate_alien_and_english(self):
        language = GrowingLanguage(
            words=[LexiconEntry(alien="vek", english="water", created_on="2026-04-13")]
        )

        added = language.add_words(
            [
                LexiconEntry(alien="vek", english="river"),
                LexiconEntry(alien="tora", english="water"),
                LexiconEntry(alien="soral", english="stone"),
            ],
            growth_day=date(2026, 4, 14),
            force=True,
        )

        self.assertEqual([word.alien for word in added], ["soral"])


class GrowthGeneratorTests(unittest.TestCase):
    def test_generate_seed_language_retries_after_malformed_json(self):
        payload = {
            "language_name": "Talune",
            "species_name": "Motes",
            "civilization_name": "Aster Reach",
            "setting_description": "Test setting",
            "phoneme_notes": "Test phonemes",
            "development_notes": "Test notes",
            "grammar": {
                "word_order": "SOV",
                "plural_suffix": "-in",
                "negation_prefix": "va-",
                "past_suffix": "-ra",
                "present_suffix": "-na",
                "future_suffix": "-to",
                "adjective_position": "before noun",
                "possessive_suffix": "-li",
            },
            "seed_words": [
                {"alien": "vek", "english": "water", "part_of_speech": "noun", "category": "nature"},
                {"alien": "talora", "english": "stone", "part_of_speech": "noun", "category": "nature"},
            ],
        }

        with patch("engine.growth_generator.preflight_ollama"), patch(
            "engine.growth_generator._ollama",
            side_effect=["{bad json", json.dumps(payload)],
        ):
            language = generate_seed_language(seed_word_count=2, candidate_count=1)

        self.assertEqual(language.language_name, "Talune")
        self.assertEqual([word.alien for word in language.words], ["vek", "talora"])

    def test_generate_seed_language_retries_after_duplicate_entries(self):
        invalid_payload = {
            "language_name": "Talune",
            "species_name": "Motes",
            "civilization_name": "Aster Reach",
            "setting_description": "Test setting",
            "phoneme_notes": "Test phonemes",
            "development_notes": "Test notes",
            "grammar": {
                "word_order": "SOV",
                "plural_suffix": "-in",
                "negation_prefix": "va-",
                "past_suffix": "-ra",
                "present_suffix": "-na",
                "future_suffix": "-to",
                "adjective_position": "before noun",
                "possessive_suffix": "-li",
            },
            "seed_words": [
                {"alien": "vek", "english": "water", "part_of_speech": "noun", "category": "nature"},
                {"alien": "vek", "english": "river", "part_of_speech": "noun", "category": "nature"},
            ],
        }
        valid_payload = {
            **invalid_payload,
            "seed_words": [
                {"alien": "vek", "english": "water", "part_of_speech": "noun", "category": "nature"},
                {"alien": "talora", "english": "river", "part_of_speech": "noun", "category": "nature"},
            ],
        }

        with patch("engine.growth_generator.preflight_ollama"), patch(
            "engine.growth_generator._ollama",
            side_effect=[json.dumps(invalid_payload), json.dumps(valid_payload)],
        ):
            language = generate_seed_language(seed_word_count=2, candidate_count=1)

        self.assertEqual([word.alien for word in language.words], ["vek", "talora"])

    def test_generate_seed_language_retries_after_hollow_lexicon_shape(self):
        invalid_payload = {
            "language_name": "Lorath",
            "species_name": "Lorathi",
            "civilization_name": "Lorathia",
            "setting_description": "Test setting",
            "phoneme_notes": "Test phonemes",
            "development_notes": "Test notes",
            "grammar": {
                "word_order": "SOV",
                "plural_suffix": "-s",
                "negation_prefix": "na-",
                "past_suffix": "-ed",
                "present_suffix": "-ing",
                "future_suffix": "-to",
                "adjective_position": "before noun",
                "possessive_suffix": "-'s",
            },
            "seed_words": [
                {"alien": "lor", "english": "person", "part_of_speech": "noun", "category": "social"},
                {"alien": "tir", "english": "see", "part_of_speech": "verb", "category": "common verbs"},
                {"alien": "zor", "english": "eat", "part_of_speech": "verb", "category": "common verbs"},
                {"alien": "mor", "english": "water", "part_of_speech": "noun", "category": "nature"},
                {"alien": "dar", "english": "day", "part_of_speech": "noun", "category": "time"},
            ],
        }
        valid_payload = {
            **invalid_payload,
            "grammar": {
                "word_order": "SOV",
                "plural_suffix": "-in",
                "negation_prefix": "va-",
                "past_suffix": "-ra",
                "present_suffix": "-na",
                "future_suffix": "-to",
                "adjective_position": "before noun",
                "possessive_suffix": "-li",
            },
            "seed_words": [
                {"alien": "lor", "english": "person", "part_of_speech": "noun", "category": "social"},
                {"alien": "talora", "english": "see", "part_of_speech": "verb", "category": "common verbs"},
                {"alien": "zorin", "english": "eat", "part_of_speech": "verb", "category": "common verbs"},
                {"alien": "moru", "english": "water", "part_of_speech": "noun", "category": "nature"},
                {"alien": "darena", "english": "day", "part_of_speech": "noun", "category": "time"},
            ],
        }

        with patch("engine.growth_generator.preflight_ollama"), patch(
            "engine.growth_generator._ollama",
            side_effect=[json.dumps(invalid_payload), json.dumps(valid_payload)],
        ):
            language = generate_seed_language(seed_word_count=5, candidate_count=1)

        self.assertEqual([word.alien for word in language.words], ["lor", "talora", "zorin", "moru", "darena"])

    def test_generate_seed_language_selects_best_candidate(self):
        weaker_words = [
            LexiconEntry(alien="lor", english="i", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="mor", english="you", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="lorva", english="person", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="lorvi", english="hand", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="loret", english="eat", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="loren", english="drink", part_of_speech="verb", category="common verbs"),
        ]
        stronger_words = [
            LexiconEntry(alien="ka", english="i", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="tesu", english="you", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="moral", english="person", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="siven", english="hand", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="daru", english="eat", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="ovira", english="drink", part_of_speech="verb", category="common verbs"),
        ]
        weak_data = {
            "language_name": "Weaklang",
            "species_name": "Motes",
            "civilization_name": "Aster Reach",
            "setting_description": "Test setting",
            "phoneme_notes": "Test phonemes",
            "development_notes": "Test notes",
            "grammar": {
                "word_order": "SOV",
                "plural_suffix": "-in",
                "negation_prefix": "va-",
                "past_suffix": "-ra",
                "present_suffix": "-na",
                "future_suffix": "-to",
                "adjective_position": "before noun",
                "possessive_suffix": "-li",
            },
        }
        strong_data = {**weak_data, "language_name": "Stronglang"}

        with patch("engine.growth_generator.preflight_ollama"), patch(
            "engine.growth_generator._generate_seed_payload",
            side_effect=[(weak_data, weaker_words), (strong_data, stronger_words)],
        ):
            language = generate_seed_language(seed_word_count=6, candidate_count=2)

        self.assertEqual(language.language_name, "Stronglang")
        self.assertEqual([word.alien for word in language.words], [word.alien for word in stronger_words])

    def test_seed_prompt_variant_rotates_archetypes(self):
        base_prompt = "BASE"

        first = _seed_prompt_variant(base_prompt, 0, 5)
        second = _seed_prompt_variant(base_prompt, 1, 5)

        self.assertIn("Archetype:", first)
        self.assertIn("Archetype:", second)
        self.assertNotEqual(first, second)

    def test_seed_prompt_for_archetype_includes_requested_name(self):
        prompt = _seed_prompt_for_archetype("BASE", "basaltic")

        self.assertIn("Archetype: basaltic.", prompt)

    def test_generate_daily_growth_filters_existing_duplicates(self):
        language = GrowingLanguage(
            language_name="Talune",
            words=[LexiconEntry(alien="vek", english="water", created_on="2026-04-13")],
        )
        payload = {
            "new_words": [
                {"alien": "vek", "english": "river"},
                {"alien": "soral", "english": "stone", "part_of_speech": "noun", "category": "material"},
                {"alien": "luma", "english": "stone"},
            ]
        }

        valid_payload = {
            "new_words": [
                {"alien": "soral", "english": "stone", "part_of_speech": "noun", "category": "material"},
                {"alien": "luma", "english": "river", "part_of_speech": "noun", "category": "water"},
                {"alien": "mira", "english": "path", "part_of_speech": "noun", "category": "space"},
            ]
        }

        with patch("engine.growth_generator.preflight_ollama"), patch(
            "engine.growth_generator._ollama",
            side_effect=[json.dumps(payload), json.dumps(valid_payload)],
        ):
            words = generate_daily_growth(language, growth_day=date(2026, 4, 14), words_to_add=3)

        self.assertEqual([word.alien for word in words], ["soral", "luma", "mira"])

    def test_days_to_target_rounds_up(self):
        language = GrowingLanguage(
            growth_words_per_day=8,
            target_lexicon_size=100,
            words=[LexiconEntry(alien=f"w{i}", english=f"e{i}") for i in range(85)],
        )

        self.assertEqual(days_to_target(language), 2)

    def test_validate_seed_language_rejects_flat_root_families(self):
        words = [
            LexiconEntry(alien="lor", english="i", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="mor", english="you", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="lorva", english="person", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="lorvi", english="hand", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="loret", english="eat", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="loren", english="drink", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="loras", english="go", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="lorak", english="water", part_of_speech="noun", category="natural elements"),
            LexiconEntry(alien="lorum", english="stone", part_of_speech="noun", category="natural elements"),
            LexiconEntry(alien="loris", english="friend", part_of_speech="noun", category="social words"),
            LexiconEntry(alien="loron", english="enemy", part_of_speech="noun", category="social words"),
            LexiconEntry(alien="lorad", english="path", part_of_speech="noun", category="spatial words"),
            LexiconEntry(alien="lorok", english="home", part_of_speech="noun", category="spatial words"),
            LexiconEntry(alien="loria", english="day", part_of_speech="noun", category="time words"),
            LexiconEntry(alien="lorai", english="night", part_of_speech="noun", category="time words"),
            LexiconEntry(alien="sena", english="one", part_of_speech="number", category="numbers"),
            LexiconEntry(alien="tavo", english="two", part_of_speech="number", category="numbers"),
        ]
        data = {
            "grammar": {
                "plural_suffix": "-in",
                "negation_prefix": "va-",
                "past_suffix": "-ra",
                "present_suffix": "-na",
                "future_suffix": "-to",
                "possessive_suffix": "-li",
            }
        }

        with self.assertRaisesRegex(GrowthValidationError, "root family"):
            _validate_seed_language_shape(data, words, expected_count=len(words))

    def test_validate_seed_language_rejects_english_inflection_glosses(self):
        words = [
            LexiconEntry(alien="lor", english="i", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="mor", english="you", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="talora", english="person", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="vekin", english="eat (past tense)", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="moru", english="water", part_of_speech="noun", category="natural elements"),
            LexiconEntry(alien="sarela", english="friend", part_of_speech="noun", category="social words"),
            LexiconEntry(alien="doni", english="path", part_of_speech="noun", category="spatial words"),
            LexiconEntry(alien="avena", english="day", part_of_speech="noun", category="time words"),
            LexiconEntry(alien="sena", english="one", part_of_speech="number", category="numbers"),
            LexiconEntry(alien="tavo", english="two", part_of_speech="number", category="numbers"),
        ]
        data = {
            "grammar": {
                "plural_suffix": "-in",
                "negation_prefix": "va-",
                "past_suffix": "-ra",
                "present_suffix": "-na",
                "future_suffix": "-to",
                "possessive_suffix": "-li",
            }
        }

        with self.assertRaisesRegex(GrowthValidationError, "core lexemes"):
            _validate_seed_language_shape(data, words, expected_count=len(words))

    def test_validate_seed_language_rejects_too_many_ultra_short_forms(self):
        words = [
            LexiconEntry(alien="na", english="i", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="ta", english="you", part_of_speech="pronoun", category="pronouns"),
            LexiconEntry(alien="va", english="person", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="ma", english="hand", part_of_speech="noun", category="body or person terms"),
            LexiconEntry(alien="laru", english="eat", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="remo", english="drink", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="kavi", english="go", part_of_speech="verb", category="common verbs"),
            LexiconEntry(alien="sanu", english="water", part_of_speech="noun", category="natural elements"),
            LexiconEntry(alien="doma", english="stone", part_of_speech="noun", category="natural elements"),
            LexiconEntry(alien="peli", english="friend", part_of_speech="noun", category="social words"),
            LexiconEntry(alien="garo", english="home", part_of_speech="noun", category="spatial words"),
            LexiconEntry(alien="zanu", english="day", part_of_speech="noun", category="time words"),
            LexiconEntry(alien="sena", english="one", part_of_speech="number", category="numbers"),
            LexiconEntry(alien="tavo", english="two", part_of_speech="number", category="numbers"),
        ]
        data = {
            "grammar": {
                "plural_suffix": "-in",
                "negation_prefix": "va-",
                "past_suffix": "-ra",
                "present_suffix": "-na",
                "future_suffix": "-to",
                "possessive_suffix": "-li",
            }
        }

        with self.assertRaisesRegex(GrowthValidationError, "ultra-short"):
            _validate_seed_language_shape(data, words, expected_count=len(words))


if __name__ == "__main__":
    unittest.main()

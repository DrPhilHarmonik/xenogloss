import unittest
from unittest.mock import patch

from engine.growth_generator import _dedupe_words, _repair_word_batch
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


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.artifacts import Artifact, ArtifactCollection
from engine.campaign import Campaign
from engine.codex import Codex
from engine.language import Language


def make_artifact(
    artifact_id: str,
    title: str,
    alien_text: str,
    tier: int = 1,
    unlocked: bool = True,
) -> Artifact:
    return Artifact(
        id=artifact_id,
        title=title,
        artifact_type="inscription",
        alien_text=alien_text,
        english_translation="",
        context_clues=[],
        visual_description="",
        key_words=[],
        tier=tier,
        unlocked=unlocked,
    )


class CampaignSaveDiscoveryTests(unittest.TestCase):
    def test_list_saves_recovers_campaigns_without_meta_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            saves_dir = Path(tmpdir)
            campaign = Campaign(
                campaign_id="abc123",
                language=Language(language_name="Ilya", species_name="Motes"),
                artifacts=ArtifactCollection([make_artifact("a1", "Artifact", "vek tora")]),
                codex=Codex(),
                created_at="2026-04-03T09:00:00",
            )
            save_data = {
                "campaign_id": campaign.campaign_id,
                "created_at": campaign.created_at,
                "current_artifact_index": 0,
                "language": campaign.language.to_dict(),
                "artifacts": campaign.artifacts.to_list(),
                "codex": campaign.codex.to_list(),
            }
            (saves_dir / "abc123.json").write_text(json.dumps(save_data))

            with patch("engine.campaign.SAVES_DIR", saves_dir):
                saves = Campaign.list_saves()

            self.assertEqual(len(saves), 1)
            self.assertEqual(saves[0]["campaign_id"], "abc123")
            self.assertEqual(saves[0]["language_name"], "Ilya")
            self.assertTrue((saves_dir / "abc123.meta.json").exists())


class SearchHelperTests(unittest.TestCase):
    def test_codex_search_by_guess_matches_substrings_case_insensitively(self):
        codex = Codex()
        codex.add("veth", "Fresh Water", "certain", "a1")
        codex.add("soral", "stone gate", "guessing", "a2")

        matches = codex.search_by_guess("water")

        self.assertEqual([entry.alien_word for entry in matches], ["veth"])

    def test_artifact_collection_finds_word_ignoring_punctuation(self):
        artifacts = ArtifactCollection(
            [
                make_artifact("a1", "Door Plate", "vek, tora!"),
                make_artifact("a2", "Journal", "soral ven", unlocked=False),
            ]
        )

        matches = artifacts.find_by_word("tora")

        self.assertEqual([artifact.id for artifact in matches], ["a1"])


if __name__ == "__main__":
    unittest.main()

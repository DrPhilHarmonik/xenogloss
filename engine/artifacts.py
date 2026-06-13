from dataclasses import dataclass, field
from typing import Optional

from .codex import strip_punctuation


@dataclass
class WordBreakdown:
    alien: str
    english: str
    grammar_note: str = ""

    def to_dict(self) -> dict:
        return {"alien": self.alien, "english": self.english, "grammar_note": self.grammar_note}

    @classmethod
    def from_dict(cls, d: dict) -> "WordBreakdown":
        return cls(alien=d["alien"], english=d["english"], grammar_note=d.get("grammar_note", ""))


@dataclass
class Artifact:
    id: str
    title: str
    artifact_type: str  # sign, journal, law, poem, map_label, dialogue, inscription
    alien_text: str
    english_translation: str  # hidden from player
    context_clues: list[str]
    visual_description: str
    key_words: list[str]  # alien words especially learnable from this artifact
    tier: int
    word_breakdown: list[WordBreakdown] = field(default_factory=list)
    unlocked: bool = False
    player_translation: str = ""
    solved: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "artifact_type": self.artifact_type,
            "alien_text": self.alien_text,
            "english_translation": self.english_translation,
            "context_clues": self.context_clues,
            "visual_description": self.visual_description,
            "key_words": self.key_words,
            "tier": self.tier,
            "word_breakdown": [w.to_dict() for w in self.word_breakdown],
            "unlocked": self.unlocked,
            "player_translation": self.player_translation,
            "solved": self.solved,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Artifact":
        return cls(
            id=d["id"],
            title=d["title"],
            artifact_type=d.get("artifact_type", "inscription"),
            alien_text=d["alien_text"],
            english_translation=d["english_translation"],
            context_clues=d.get("context_clues", []),
            visual_description=d.get("visual_description", ""),
            key_words=d.get("key_words", []),
            tier=d.get("tier", 1),
            word_breakdown=[WordBreakdown.from_dict(w) for w in d.get("word_breakdown", [])],
            unlocked=d.get("unlocked", False),
            player_translation=d.get("player_translation", ""),
            solved=d.get("solved", False),
        )

    def unique_words(self) -> list[str]:
        seen = set()
        words = []
        for raw in self.alien_text.split():
            w = strip_punctuation(raw).lower()
            if w and w not in seen:
                seen.add(w)
                words.append(w)
        return words


# How many unique codex entries unlock the next tier
UNLOCK_THRESHOLDS = {
    1: 0,   # tier 1 always unlocked
    2: 8,   # need 8 codex words to unlock tier 2
    3: 20,
    4: 40,
    5: 65,
}


class ArtifactCollection:
    def __init__(self, artifacts: list[Artifact] = None):
        self.artifacts: list[Artifact] = artifacts or []
        self._index: dict[str, Artifact] = {a.id: a for a in self.artifacts}

    def add(self, artifact: Artifact):
        self.artifacts.append(artifact)
        self._index[artifact.id] = artifact

    def by_id(self, artifact_id: str) -> Optional[Artifact]:
        return self._index.get(artifact_id)

    def unlocked(self) -> list[Artifact]:
        return [a for a in self.artifacts if a.unlocked]

    def word_frequency(self) -> dict[str, int]:
        """Count how many artifacts each alien word appears in (across all artifacts)."""
        freq: dict[str, int] = {}
        for artifact in self.artifacts:
            for word in artifact.unique_words():
                freq[word] = freq.get(word, 0) + 1
        return freq

    def find_by_word(self, alien_word: str, unlocked_only: bool = False) -> list[Artifact]:
        """Return artifacts whose alien text contains the given word."""
        needle = strip_punctuation(alien_word).lower().strip()
        if not needle:
            return []
        artifacts = self.unlocked() if unlocked_only else self.artifacts
        return [artifact for artifact in artifacts if needle in artifact.unique_words()]

    def check_unlocks(self, codex_size: int):
        """Unlock artifacts based on current codex size."""
        for artifact in self.artifacts:
            if artifact.tier in UNLOCK_THRESHOLDS:
                if codex_size >= UNLOCK_THRESHOLDS[artifact.tier]:
                    artifact.unlocked = True

    def tiers_present(self) -> list[int]:
        return sorted(set(a.tier for a in self.artifacts))

    def to_list(self) -> list[dict]:
        return [a.to_dict() for a in self.artifacts]

    @classmethod
    def from_list(cls, data: list[dict]) -> "ArtifactCollection":
        return cls([Artifact.from_dict(d) for d in data])

from dataclasses import dataclass, field
from typing import Optional


CONFIDENCE_LEVELS = ("guessing", "probable", "certain")
_STRIP_CHARS = ".,!?;:\"'()[]"


def strip_punctuation(word: str) -> str:
    """Strip surrounding punctuation from an alien word token."""
    return word.strip(_STRIP_CHARS)
CONFIDENCE_COLORS = {
    "guessing": "yellow",
    "probable": "cyan",
    "certain": "green",
}


@dataclass
class CodexEntry:
    alien_word: str
    player_guess: str
    confidence: str = "guessing"  # guessing | probable | certain
    first_seen_in: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "alien_word": self.alien_word,
            "player_guess": self.player_guess,
            "confidence": self.confidence,
            "first_seen_in": self.first_seen_in,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CodexEntry":
        return cls(
            alien_word=d["alien_word"],
            player_guess=d["player_guess"],
            confidence=d.get("confidence", "guessing"),
            first_seen_in=d.get("first_seen_in", ""),
            notes=d.get("notes", ""),
        )


class Codex:
    def __init__(self):
        self.entries: dict[str, CodexEntry] = {}  # alien_word -> entry

    def add(self, alien_word: str, guess: str, confidence: str = "guessing", artifact_id: str = "") -> CodexEntry:
        alien_word = alien_word.lower().strip()
        if confidence not in CONFIDENCE_LEVELS:
            confidence = "guessing"
        entry = CodexEntry(
            alien_word=alien_word,
            player_guess=guess,
            confidence=confidence,
            first_seen_in=artifact_id,
        )
        self.entries[alien_word] = entry
        return entry

    def get(self, alien_word: str) -> Optional[CodexEntry]:
        return self.entries.get(alien_word.lower().strip())

    def remove(self, alien_word: str):
        self.entries.pop(alien_word.lower().strip(), None)

    def known_words(self) -> set[str]:
        return set(self.entries.keys())

    def coverage(self, alien_text: str) -> tuple[int, int]:
        """Return (known_count, total_count) of unique words in alien_text."""
        words = {strip_punctuation(w).lower() for w in alien_text.split()}
        words = {w for w in words if w}
        known = words & self.known_words()
        return len(known), len(words)

    def search_by_guess(self, query: str) -> list[CodexEntry]:
        """Return entries whose guessed meaning contains the query substring."""
        needle = query.lower().strip()
        if not needle:
            return []
        return [
            entry
            for entry in sorted(self.entries.values(), key=lambda e: e.alien_word)
            if needle in entry.player_guess.lower()
        ]

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in sorted(self.entries.values(), key=lambda e: e.alien_word)]

    @classmethod
    def from_list(cls, data: list[dict]) -> "Codex":
        codex = cls()
        for d in data:
            entry = CodexEntry.from_dict(d)
            codex.entries[entry.alien_word] = entry
        return codex

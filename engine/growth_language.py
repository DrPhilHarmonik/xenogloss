import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .language import GrammarRules

GROWING_LANGUAGES_DIR = Path(__file__).parent.parent / "data" / "growing_languages"


@dataclass
class LexiconEntry:
    alien: str
    english: str
    part_of_speech: str = ""
    category: str = ""
    notes: str = ""
    example_alien: str = ""
    example_english: str = ""
    created_on: str = ""
    source: str = "seed"

    @classmethod
    def from_dict(cls, data: dict) -> "LexiconEntry":
        return cls(
            alien=data.get("alien", ""),
            english=data.get("english", ""),
            part_of_speech=data.get("part_of_speech", ""),
            category=data.get("category", ""),
            notes=data.get("notes", ""),
            example_alien=data.get("example_alien", ""),
            example_english=data.get("example_english", ""),
            created_on=data.get("created_on", ""),
            source=data.get("source", "seed"),
        )

    def to_dict(self) -> dict:
        return {
            "alien": self.alien,
            "english": self.english,
            "part_of_speech": self.part_of_speech,
            "category": self.category,
            "notes": self.notes,
            "example_alien": self.example_alien,
            "example_english": self.example_english,
            "created_on": self.created_on,
            "source": self.source,
        }


@dataclass
class GrowingLanguage:
    language_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_growth_on: str = ""
    growth_words_per_day: int = 8
    target_lexicon_size: int = 1000
    language_name: str = "Unknown"
    species_name: str = "Unknown"
    civilization_name: str = "Unknown"
    setting_description: str = ""
    phoneme_notes: str = ""
    grammar: GrammarRules = field(default_factory=GrammarRules)
    development_notes: str = ""
    words: list[LexiconEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "GrowingLanguage":
        return cls(
            language_id=data.get("language_id", uuid.uuid4().hex[:12]),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            last_growth_on=data.get("last_growth_on", ""),
            growth_words_per_day=data.get("growth_words_per_day", 8),
            target_lexicon_size=data.get("target_lexicon_size", 1000),
            language_name=data.get("language_name", "Unknown"),
            species_name=data.get("species_name", "Unknown"),
            civilization_name=data.get("civilization_name", "Unknown"),
            setting_description=data.get("setting_description", ""),
            phoneme_notes=data.get("phoneme_notes", ""),
            grammar=GrammarRules.from_dict(data.get("grammar", {})),
            development_notes=data.get("development_notes", ""),
            words=[LexiconEntry.from_dict(item) for item in data.get("words", [])],
        )

    def to_dict(self) -> dict:
        return {
            "language_id": self.language_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_growth_on": self.last_growth_on,
            "growth_words_per_day": self.growth_words_per_day,
            "target_lexicon_size": self.target_lexicon_size,
            "language_name": self.language_name,
            "species_name": self.species_name,
            "civilization_name": self.civilization_name,
            "setting_description": self.setting_description,
            "phoneme_notes": self.phoneme_notes,
            "grammar": self.grammar.to_dict(),
            "development_notes": self.development_notes,
            "words": [word.to_dict() for word in self.words],
        }

    @property
    def lexicon_size(self) -> int:
        return len(self.words)

    def save_path(self) -> Path:
        GROWING_LANGUAGES_DIR.mkdir(parents=True, exist_ok=True)
        return GROWING_LANGUAGES_DIR / f"{self.language_id}.json"

    def save(self) -> None:
        self.updated_at = datetime.now().isoformat()
        self.save_path().write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, language_id: str) -> "GrowingLanguage":
        path = GROWING_LANGUAGES_DIR / f"{language_id}.json"
        return cls.from_dict(json.loads(path.read_text()))

    @classmethod
    def list_languages(cls) -> list[dict]:
        GROWING_LANGUAGES_DIR.mkdir(parents=True, exist_ok=True)
        items = []
        for path in sorted(GROWING_LANGUAGES_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                language = cls.from_dict(json.loads(path.read_text()))
            except Exception:
                continue
            items.append(
                {
                    "language_id": language.language_id,
                    "language_name": language.language_name,
                    "species_name": language.species_name,
                    "lexicon_size": language.lexicon_size,
                    "growth_words_per_day": language.growth_words_per_day,
                    "last_growth_on": language.last_growth_on,
                    "target_lexicon_size": language.target_lexicon_size,
                    "created_at": language.created_at,
                }
            )
        return items

    def existing_alien_words(self) -> set[str]:
        return {word.alien.lower() for word in self.words}

    def existing_english_glosses(self) -> set[str]:
        return {word.english.lower() for word in self.words}

    def can_grow_on(self, growth_day: date) -> bool:
        return self.last_growth_on != growth_day.isoformat()

    def add_words(self, new_words: list[LexiconEntry], growth_day: date, force: bool = False) -> list[LexiconEntry]:
        if not force and not self.can_grow_on(growth_day):
            raise ValueError(f"Language already grew on {growth_day.isoformat()}")

        existing_alien = self.existing_alien_words()
        existing_english = self.existing_english_glosses()
        added = []

        for word in new_words:
            alien_key = word.alien.lower()
            english_key = word.english.lower()
            if not alien_key or not english_key:
                continue
            if alien_key in existing_alien or english_key in existing_english:
                continue
            if not word.created_on:
                word.created_on = growth_day.isoformat()
            added.append(word)
            self.words.append(word)
            existing_alien.add(alien_key)
            existing_english.add(english_key)

        self.last_growth_on = growth_day.isoformat()
        return added

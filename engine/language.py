from dataclasses import dataclass, field


@dataclass
class GrammarRules:
    word_order: str = "?"
    plural_suffix: str = "?"
    negation_prefix: str = "?"
    past_suffix: str = "?"
    present_suffix: str = "?"
    future_suffix: str = "?"
    adjective_position: str = "?"
    possessive_suffix: str = "?"

    @classmethod
    def from_dict(cls, d: dict) -> "GrammarRules":
        return cls(
            word_order=d.get("word_order", "?"),
            plural_suffix=d.get("plural_suffix", "?"),
            negation_prefix=d.get("negation_prefix", "?"),
            past_suffix=d.get("past_suffix", "?"),
            present_suffix=d.get("present_suffix", "?"),
            future_suffix=d.get("future_suffix", "?"),
            adjective_position=d.get("adjective_position", "?"),
            possessive_suffix=d.get("possessive_suffix", "?"),
        )

    def to_dict(self) -> dict:
        return {
            "word_order": self.word_order,
            "plural_suffix": self.plural_suffix,
            "negation_prefix": self.negation_prefix,
            "past_suffix": self.past_suffix,
            "present_suffix": self.present_suffix,
            "future_suffix": self.future_suffix,
            "adjective_position": self.adjective_position,
            "possessive_suffix": self.possessive_suffix,
        }


@dataclass
class Language:
    language_name: str = ""
    species_name: str = ""
    civilization_name: str = ""
    setting_description: str = ""
    vocabulary: dict = field(default_factory=dict)  # alien -> english
    grammar: GrammarRules = field(default_factory=GrammarRules)
    phoneme_notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Language":
        return cls(
            language_name=d.get("language_name", "Unknown"),
            species_name=d.get("species_name", "Unknown"),
            civilization_name=d.get("civilization_name", "Unknown"),
            setting_description=d.get("setting_description", ""),
            vocabulary=d.get("vocabulary", {}),
            grammar=GrammarRules.from_dict(d.get("grammar", {})),
            phoneme_notes=d.get("phoneme_notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "language_name": self.language_name,
            "species_name": self.species_name,
            "civilization_name": self.civilization_name,
            "setting_description": self.setting_description,
            "vocabulary": self.vocabulary,
            "grammar": self.grammar.to_dict(),
            "phoneme_notes": self.phoneme_notes,
        }

    def grammar_summary(self) -> str:
        g = self.grammar
        lines = [
            f"Word order: {g.word_order}",
            f"Plural: add '{g.plural_suffix}'",
            f"Negation: prefix '{g.negation_prefix}'",
            f"Past tense: add '{g.past_suffix}'",
            f"Present tense: add '{g.present_suffix}'",
            f"Future tense: add '{g.future_suffix}'",
            f"Adjectives: {g.adjective_position} noun",
            f"Possessive: add '{g.possessive_suffix}'",
        ]
        return "\n".join(lines)

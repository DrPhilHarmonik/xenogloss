import json
import math
import re
import os
from datetime import date

from .generator import LANGUAGE_MODEL, _extract_json, _load_prompt, _ollama, preflight_ollama
from .growth_language import GrowingLanguage, LexiconEntry
from .language import GrammarRules


class GrowthValidationError(ValueError):
    pass


SEED_MODEL = os.environ.get("XENOGLOSS_SEED_MODEL", LANGUAGE_MODEL)
GROWTH_MODEL = os.environ.get("XENOGLOSS_GROWTH_MODEL", LANGUAGE_MODEL)
SEED_TIMEOUT = int(os.environ.get("XENOGLOSS_SEED_TIMEOUT", os.environ.get("XENOGLOSS_OLLAMA_TIMEOUT", "900")))
GROWTH_TIMEOUT = int(os.environ.get("XENOGLOSS_GROWTH_TIMEOUT", os.environ.get("XENOGLOSS_OLLAMA_TIMEOUT", "300")))
SEED_CANDIDATE_COUNT = int(os.environ.get("XENOGLOSS_SEED_CANDIDATES", "3"))

SEED_ARCHETYPES = (
    {
        "name": "tidal",
        "description": (
            "Favor flowing, tidal phonology with open syllables, sonorants, and alternating short/long words. "
            "Culture should feel maritime, estuarial, or island-linked without defaulting to generic harmony tropes."
        ),
    },
    {
        "name": "basaltic",
        "description": (
            "Favor denser, clipped phonology with more stops, fricatives, and compact compounds. "
            "Culture should feel highland, volcanic, or stone-working, with practical vocabulary and sharper word shapes."
        ),
    },
    {
        "name": "canopy",
        "description": (
            "Favor airy multisyllabic forms, lighter consonant clusters, and a strong contrast between short particles and lyrical content words. "
            "Culture should feel arboreal, migratory, or ecology-centered."
        ),
    },
    {
        "name": "steppe",
        "description": (
            "Favor brisk rhythmic words, productive suffixes, and travel-oriented vocabulary growth. "
            "Culture should feel pastoral, caravan-linked, or route-based rather than sedentary."
        ),
    },
    {
        "name": "ritual",
        "description": (
            "Favor formal register contrasts, conservative roots, and a lexicon shaped by ceremony, kinship, and memory. "
            "The language should still feel practical in everyday use, not mystical by default."
        ),
    },
)


def _normalize_word(item: dict, created_on: str, source: str) -> LexiconEntry | None:
    alien = item.get("alien", "").strip().lower()
    english = item.get("english", "").strip().lower()
    if not alien or not english:
        return None

    return LexiconEntry(
        alien=alien,
        english=english,
        part_of_speech=item.get("part_of_speech", "").strip().lower(),
        category=item.get("category", "").strip().lower(),
        notes=item.get("notes", "").strip(),
        example_alien=item.get("example_alien", "").strip(),
        example_english=item.get("example_english", "").strip(),
        created_on=created_on,
        source=source,
    )


def _lexicon_snapshot(language: GrowingLanguage) -> list[dict]:
    return [
        {
            "alien": word.alien,
            "english": word.english,
            "part_of_speech": word.part_of_speech,
            "category": word.category,
        }
        for word in language.words
    ]


def _count_syllables(word: str) -> int:
    groups = re.findall(r"[aeiouy]+", word.lower())
    return max(len(groups), 1) if word else 0


def _looks_english_morphology(value: str) -> bool:
    lowered = value.strip().lower()
    banned = {
        "-s",
        "-es",
        "-ed",
        "-ing",
        "'s",
        "-'s",
        "un-",
        "re-",
    }
    return lowered in banned


def _category_key(category: str) -> str:
    lowered = category.lower()
    if "pronoun" in lowered:
        return "pronouns"
    if "body" in lowered or "person" in lowered:
        return "body_person"
    if "verb" in lowered:
        return "common_verbs"
    if "natural" in lowered or "element" in lowered or "weather" in lowered:
        return "natural_elements"
    if "social" in lowered or "kin" in lowered or "relation" in lowered:
        return "social_words"
    if "spatial" in lowered or "place" in lowered or "direction" in lowered or "location" in lowered:
        return "spatial_words"
    if "time" in lowered or "calendar" in lowered:
        return "time_words"
    if "number" in lowered or "count" in lowered:
        return "numbers"
    return "other"


def _looks_like_calque_or_inflection(gloss: str) -> bool:
    lowered = gloss.strip().lower()
    if not lowered:
        return True
    if "(" in lowered or ")" in lowered:
        return True
    if lowered.startswith("not "):
        return True
    if any(marker in lowered for marker in ("past tense", "present tense", "future tense")):
        return True
    if any(marker in lowered for marker in ("plural of ", "negative of ", "form of ")):
        return True
    if len(lowered.split()) > 3:
        return True
    return False


def _dominant_root_family(words: list[LexiconEntry]) -> tuple[str, int]:
    family_counts: dict[str, int] = {}
    roots = {word.alien for word in words if 3 <= len(word.alien) <= 4}

    for root in roots:
        count = sum(
            1
            for word in words
            if word.alien == root or word.alien.startswith(root) or word.alien.endswith(root)
        )
        family_counts[root] = count

    if not family_counts:
        return "", 0

    root, count = max(family_counts.items(), key=lambda item: item[1])
    return root, count


def _seed_prompt_variant(base_prompt: str, candidate_index: int, candidate_count: int) -> str:
    archetype = SEED_ARCHETYPES[candidate_index % len(SEED_ARCHETYPES)]
    return (
        f"{base_prompt}\n\n"
        f"Generate candidate #{candidate_index + 1} of {candidate_count}.\n"
        f"Archetype: {archetype['name']}.\n"
        f"Archetype guidance: {archetype['description']}\n"
        "Make this language clearly distinct from other plausible outputs in phonology, root shapes, and cultural framing.\n"
        "Do not converge on repetitive stem families or obvious compositional calques.\n"
        "Do not reuse placeholder stems like lor, zor, mor, nar, kor across much of the lexicon.\n"
    )


def seed_archetype_names() -> list[str]:
    return [item["name"] for item in SEED_ARCHETYPES]


def _seed_prompt_for_archetype(base_prompt: str, archetype_name: str) -> str:
    for archetype in SEED_ARCHETYPES:
        if archetype["name"] == archetype_name:
            return (
                f"{base_prompt}\n\n"
                f"Archetype: {archetype['name']}.\n"
                f"Archetype guidance: {archetype['description']}\n"
                "Do not converge on repetitive stem families or obvious compositional calques.\n"
                "Do not reuse placeholder stems like lor, zor, mor, nar, kor across much of the lexicon.\n"
            )
    raise GrowthValidationError(
        f"Unknown seed archetype '{archetype_name}'. Choose from: {', '.join(seed_archetype_names())}"
    )


def _seed_language_score(data: dict, words: list[LexiconEntry]) -> float:
    counts_by_category: dict[str, int] = {}
    for word in words:
        key = _category_key(word.category)
        counts_by_category[key] = counts_by_category.get(key, 0) + 1

    syllable_counts = [_count_syllables(word.alien) for word in words]
    distinct_syllable_counts = len(set(syllable_counts))
    multisyllabic_ratio = sum(1 for count in syllable_counts if count >= 2) / max(len(words), 1)
    root, family_size = _dominant_root_family(words)
    unique_prefixes = len({word.alien[:2] for word in words if len(word.alien) >= 2})
    unique_suffixes = len({word.alien[-2:] for word in words if len(word.alien) >= 2})
    gloss_word_lengths = sum(len(word.english.split()) == 1 for word in words)
    notes_with_signal = sum(bool(word.notes.strip()) for word in words)
    category_balance = sum(min(count, 2) for count in counts_by_category.values())
    ultrashort = sum(1 for word in words if len(word.alien) <= 2)

    score = 0.0
    score += distinct_syllable_counts * 6.0
    score += unique_prefixes * 1.5
    score += unique_suffixes * 1.5
    score += category_balance * 2.0
    score += gloss_word_lengths * 1.0
    score += notes_with_signal * 0.5
    score -= abs(multisyllabic_ratio - 0.6) * 20.0
    score -= family_size * 5.0
    score -= ultrashort * 4.0
    if root:
        score -= max(0, family_size - math.ceil(len(words) * 0.2)) * 3.0

    grammar = data.get("grammar", {})
    grammar_forms = {
        str(grammar.get("plural_suffix", "")).strip(),
        str(grammar.get("negation_prefix", "")).strip(),
        str(grammar.get("past_suffix", "")).strip(),
        str(grammar.get("present_suffix", "")).strip(),
        str(grammar.get("future_suffix", "")).strip(),
        str(grammar.get("possessive_suffix", "")).strip(),
    }
    score += len({form for form in grammar_forms if form}) * 1.0
    return score


def _generate_structured_json(
    prompt: str,
    schema_name: str,
    progress_cb=None,
    retries: int = 3,
    model: str = LANGUAGE_MODEL,
    timeout: int = 300,
) -> dict:
    last_error = None
    current_prompt = prompt

    for attempt in range(retries + 1):
        raw = _ollama(
            current_prompt,
            model=model,
            progress_cb=progress_cb,
            temperature=0.2,
            timeout=timeout,
        )
        try:
            return _extract_json(raw)
        except ValueError as exc:
            last_error = exc
            if attempt == retries:
                break
            if progress_cb:
                progress_cb(
                    f"\n[retrying {schema_name} generation after malformed JSON: attempt {attempt + 2}/{retries + 1}]\n"
                )
            current_prompt = (
                prompt
                + "\n\nYour previous response was malformed JSON."
                + f"\nReturn the full {schema_name} JSON object again from scratch."
                + "\nDo not truncate."
                + "\nDo not add commentary."
                + "\nDo not add placeholders."
            )

    raise ValueError(f"Malformed JSON in {schema_name} generation after {retries + 1} attempts") from last_error


def _validate_candidate_words(
    words: list[LexiconEntry],
    expected_count: int,
    schema_name: str,
    existing_alien: set[str] | None = None,
    existing_english: set[str] | None = None,
) -> list[LexiconEntry]:
    existing_alien = set(existing_alien or set())
    existing_english = set(existing_english or set())

    unique_words = []
    seen_alien = set(existing_alien)
    seen_english = set(existing_english)
    duplicate_alien = set()
    duplicate_english = set()

    for word in words:
        if word.alien in seen_alien:
            duplicate_alien.add(word.alien)
            continue
        if word.english in seen_english:
            duplicate_english.add(word.english)
            continue
        unique_words.append(word)
        seen_alien.add(word.alien)
        seen_english.add(word.english)

    if duplicate_alien or duplicate_english or len(unique_words) != expected_count:
        problems = []
        if duplicate_alien:
            problems.append(f"duplicate alien words: {', '.join(sorted(duplicate_alien))}")
        if duplicate_english:
            problems.append(f"duplicate english glosses: {', '.join(sorted(duplicate_english))}")
        if len(unique_words) != expected_count:
            problems.append(f"expected {expected_count} unique entries, got {len(unique_words)}")
        raise GrowthValidationError(f"Invalid {schema_name}: " + "; ".join(problems))

    return unique_words


def _validate_seed_language_shape(data: dict, words: list[LexiconEntry], expected_count: int) -> None:
    if len(words) != expected_count:
        raise GrowthValidationError(f"Invalid seed language: expected {expected_count} unique entries, got {len(words)}")

    multisyllabic = sum(1 for word in words if _count_syllables(word.alien) >= 2)
    min_multisyllabic = min(max(1, math.ceil(expected_count * 0.4)), expected_count)
    if expected_count >= 12:
        min_multisyllabic = max(min_multisyllabic, math.ceil(expected_count * 0.55))
    if multisyllabic < min_multisyllabic:
        raise GrowthValidationError(
            f"Invalid seed language: too many short roots; need at least {min_multisyllabic} multisyllabic words, got {multisyllabic}"
        )

    if expected_count >= 4 and not any(_count_syllables(word.alien) == 1 for word in words):
        raise GrowthValidationError("Invalid seed language: lexicon needs at least one short root for contrast")
    if expected_count >= 12:
        ultrashort = sum(1 for word in words if len(word.alien) <= 2)
        max_ultrashort = max(2, math.ceil(expected_count * 0.12))
        if ultrashort > max_ultrashort:
            raise GrowthValidationError(
                f"Invalid seed language: too many ultra-short forms; allow at most {max_ultrashort}, got {ultrashort}"
            )

    bad_glosses = sorted({word.english for word in words if _looks_like_calque_or_inflection(word.english)})
    if bad_glosses:
        raise GrowthValidationError(
            "Invalid seed language: glosses should be core lexemes, not phrases or inflections: "
            + ", ".join(bad_glosses[:6])
        )

    if expected_count >= 12:
        counts_by_category: dict[str, int] = {}
        for word in words:
            key = _category_key(word.category)
            counts_by_category[key] = counts_by_category.get(key, 0) + 1

        required_categories = (
            "pronouns",
            "body_person",
            "common_verbs",
            "natural_elements",
            "social_words",
            "spatial_words",
            "time_words",
            "numbers",
        )
        missing_categories = [key for key in required_categories if counts_by_category.get(key, 0) == 0]
        if missing_categories:
            raise GrowthValidationError(
                "Invalid seed language: missing semantic coverage for "
                + ", ".join(missing_categories)
            )

        if counts_by_category.get("numbers", 0) < 2:
            raise GrowthValidationError("Invalid seed language: include at least two number words in the seed lexicon")
        if counts_by_category.get("pronouns", 0) < 2:
            raise GrowthValidationError("Invalid seed language: include at least two pronouns in the seed lexicon")
        if sum(1 for word in words if word.part_of_speech == "verb") < max(3, math.ceil(expected_count * 0.15)):
            raise GrowthValidationError("Invalid seed language: seed lexicon needs more basic verbs")

        root, family_size = _dominant_root_family(words)
        max_family_size = max(4, math.ceil(expected_count * 0.25))
        if root and family_size > max_family_size:
            raise GrowthValidationError(
                f"Invalid seed language: too many forms belong to the same root family ({root}-..., size {family_size})"
            )

    grammar = data.get("grammar", {})
    for key in (
        "plural_suffix",
        "negation_prefix",
        "past_suffix",
        "present_suffix",
        "future_suffix",
        "possessive_suffix",
    ):
        value = str(grammar.get(key, "")).strip()
        if not value:
            raise GrowthValidationError(f"Invalid seed language: missing grammar value for {key}")
        if _looks_english_morphology(value):
            raise GrowthValidationError(f"Invalid seed language: grammar value {key} looks too English-derived ({value})")


def _normalize_words_from_data(data: dict, list_key: str, created_on: str, source: str) -> list[LexiconEntry]:
    candidates = []
    for item in data.get(list_key, []):
        word = _normalize_word(item, created_on=created_on, source=source)
        if word:
            candidates.append(word)
    return candidates


def _dedupe_words(
    words: list[LexiconEntry],
    *,
    existing_alien: set[str] | None = None,
    existing_english: set[str] | None = None,
) -> list[LexiconEntry]:
    """Keep the first valid occurrence of each alien form and English gloss."""
    seen_alien = set(existing_alien or set())
    seen_english = set(existing_english or set())
    unique_words: list[LexiconEntry] = []

    for word in words:
        if word.alien in seen_alien or word.english in seen_english:
            continue
        unique_words.append(word)
        seen_alien.add(word.alien)
        seen_english.add(word.english)

    return unique_words


def _missing_words_prompt(
    *,
    count: int,
    existing_words: list[LexiconEntry],
    schema_name: str,
    list_key: str,
    base_prompt: str,
) -> str:
    existing_snapshot = json.dumps(
        [
            {
                "alien": word.alien,
                "english": word.english,
                "part_of_speech": word.part_of_speech,
                "category": word.category,
            }
            for word in existing_words
        ],
        indent=2,
    )
    item_name = "seed_words" if list_key == "seed_words" else "new_words"
    return (
        f"{base_prompt}\n\n"
        "Your previous response contained some valid entries and some duplicates or invalid items.\n"
        f"Keep the language profile exactly consistent and return only the missing {count} {item_name}.\n"
        "Do not repeat any previously accepted entry.\n"
        f"Already accepted {schema_name} entries:\n{existing_snapshot}\n\n"
        "Return valid JSON only using this exact schema:\n"
        "{\n"
        f'  "{list_key}": [\n'
        "    {\n"
        '      "alien": "string",\n'
        '      "english": "string",\n'
        '      "part_of_speech": "noun|verb|adjective|adverb|pronoun|particle|number",\n'
        '      "category": "semantic domain",\n'
        '      "notes": "short note about nuance, derivation, or register",\n'
        '      "example_alien": "short phrase or sentence",\n'
        '      "example_english": "translation of the example"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _repair_word_batch(
    *,
    prompt: str,
    schema_name: str,
    list_key: str,
    expected_count: int,
    candidates: list[LexiconEntry],
    created_on: str,
    source: str,
    progress_cb=None,
    existing_alien: set[str] | None = None,
    existing_english: set[str] | None = None,
    model: str = LANGUAGE_MODEL,
    timeout: int = 300,
    retries: int = 2,
) -> list[LexiconEntry]:
    repaired = _dedupe_words(
        candidates,
        existing_alien=existing_alien,
        existing_english=existing_english,
    )
    if len(repaired) >= expected_count:
        return repaired[:expected_count]

    current_prompt = _missing_words_prompt(
        count=expected_count - len(repaired),
        existing_words=repaired,
        schema_name=schema_name,
        list_key=list_key,
        base_prompt=prompt,
    )

    for attempt in range(retries + 1):
        if progress_cb:
            progress_cb(
                f"\n[repairing {schema_name}: need {expected_count - len(repaired)} more unique entries"
                f" (attempt {attempt + 1}/{retries + 1})]\n"
            )

        data = _generate_structured_json(
            current_prompt,
            schema_name=f"{schema_name} repair batch",
            progress_cb=progress_cb,
            retries=2,
            model=model,
            timeout=timeout,
        )
        new_candidates = _normalize_words_from_data(data, list_key=list_key, created_on=created_on, source=source)
        repaired = _dedupe_words(
            repaired + new_candidates,
            existing_alien=existing_alien,
            existing_english=existing_english,
        )
        if len(repaired) >= expected_count:
            return repaired[:expected_count]

        current_prompt = _missing_words_prompt(
            count=expected_count - len(repaired),
            existing_words=repaired,
            schema_name=schema_name,
            list_key=list_key,
            base_prompt=prompt,
        )

    raise GrowthValidationError(
        f"Invalid {schema_name}: expected {expected_count} unique entries after repair, got {len(repaired)}"
    )


def _generate_validated_words(
    prompt: str,
    schema_name: str,
    list_key: str,
    expected_count: int,
    created_on: str,
    source: str,
    progress_cb=None,
    existing_alien: set[str] | None = None,
    existing_english: set[str] | None = None,
    retries: int = 3,
    initial_data: dict | None = None,
    model: str = LANGUAGE_MODEL,
    timeout: int = 300,
) -> list[LexiconEntry]:
    last_error = None
    current_prompt = prompt

    for attempt in range(retries + 1):
        if attempt == 0 and initial_data is not None:
            data = initial_data
        else:
            data = _generate_structured_json(
                current_prompt,
                schema_name=schema_name,
                progress_cb=progress_cb,
                retries=3,
                model=model,
                timeout=timeout,
            )
        candidates = _normalize_words_from_data(data, list_key=list_key, created_on=created_on, source=source)

        try:
            return _validate_candidate_words(
                candidates,
                expected_count=expected_count,
                schema_name=schema_name,
                existing_alien=existing_alien,
                existing_english=existing_english,
            )
        except GrowthValidationError as exc:
            last_error = exc
            if attempt == retries:
                break
            if progress_cb:
                progress_cb(f"\n[retrying {schema_name} generation after invalid lexicon batch: {exc}]\n")
            current_prompt = (
                prompt
                + "\n\nYour previous response was invalid."
                + f"\nProblem: {exc}"
                + f"\nReturn exactly {expected_count} unique entries."
                + "\nNo alien word may repeat."
                + "\nNo English gloss may repeat."
                + "\nDo not reuse any previously listed item."
                + "\nRewrite the entire JSON object from scratch."
            )

    raise GrowthValidationError(
        f"Invalid {schema_name} after {retries + 1} attempts: {last_error}"
    ) from last_error


def _generate_seed_payload(
    prompt: str,
    seed_word_count: int,
    progress_cb=None,
    retries: int = 3,
    model: str = SEED_MODEL,
    timeout: int = SEED_TIMEOUT,
) -> tuple[dict, list[LexiconEntry]]:
    last_error = None
    current_prompt = prompt
    created_on = date.today().isoformat()

    for attempt in range(retries + 1):
        data = _generate_structured_json(
            current_prompt,
            schema_name="seed language",
            progress_cb=progress_cb,
            retries=3,
            model=model,
            timeout=timeout,
        )
        words = _normalize_words_from_data(data, list_key="seed_words", created_on=created_on, source="seed")
        try:
            words = _repair_word_batch(
                prompt=prompt,
                schema_name="seed language",
                list_key="seed_words",
                expected_count=seed_word_count,
                candidates=words,
                created_on=created_on,
                source="seed",
                progress_cb=progress_cb,
                model=model,
                timeout=timeout,
            )
            data["seed_words"] = [word.to_dict() for word in words]
            words = _validate_candidate_words(
                words,
                expected_count=seed_word_count,
                schema_name="seed language",
            )
            _validate_seed_language_shape(data, words, expected_count=seed_word_count)
            return data, words
        except GrowthValidationError as exc:
            last_error = exc
            if attempt == retries:
                break
            if progress_cb:
                progress_cb(f"\n[retrying seed language generation after invalid language shape: {exc}]\n")
            current_prompt = (
                prompt
                + "\n\nYour previous response was invalid."
                + f"\nProblem: {exc}"
                + "\nReturn a more natural-looking lexicon shape with both short roots and many 2-3 syllable everyday words."
                + "\nDo not use English-looking affixes such as -s, -ed, -ing, or 's."
                + "\nRewrite the full JSON object from scratch."
            )

    raise GrowthValidationError(f"Invalid seed language after {retries + 1} attempts: {last_error}") from last_error


def generate_seed_language(
    seed_word_count: int = 24,
    growth_words_per_day: int = 8,
    target_lexicon_size: int = 1000,
    candidate_count: int = SEED_CANDIDATE_COUNT,
    archetype: str | None = None,
    progress_cb=None,
) -> GrowingLanguage:
    preflight_ollama(required_models=(SEED_MODEL,))

    base_prompt = (
        _load_prompt("growth_init.txt")
        .replace("{SEED_WORD_COUNT}", str(seed_word_count))
        .replace("{GROWTH_WORDS_PER_DAY}", str(growth_words_per_day))
        .replace("{TARGET_LEXICON_SIZE}", str(target_lexicon_size))
    )
    candidate_count = max(1, candidate_count)
    best_data = None
    best_words = None
    best_score = float("-inf")

    for candidate_index in range(candidate_count):
        if progress_cb:
            progress_cb(f"\n[seed candidate {candidate_index + 1}/{candidate_count}]\n")
        if archetype:
            prompt = _seed_prompt_for_archetype(base_prompt, archetype)
        else:
            prompt = _seed_prompt_variant(base_prompt, candidate_index, candidate_count)
        data, normalized = _generate_seed_payload(
            prompt,
            seed_word_count=seed_word_count,
            progress_cb=progress_cb,
            model=SEED_MODEL,
            timeout=SEED_TIMEOUT,
        )
        score = _seed_language_score(data, normalized)
        if progress_cb:
            progress_cb(f"\n[candidate {candidate_index + 1} score: {score:.1f}]\n")
        if score > best_score:
            best_data = data
            best_words = normalized
            best_score = score

    data = best_data or {}
    normalized = best_words or []

    language = GrowingLanguage(
        growth_words_per_day=growth_words_per_day,
        target_lexicon_size=target_lexicon_size,
        language_name=data.get("language_name", "Unknown"),
        species_name=data.get("species_name", "Unknown"),
        civilization_name=data.get("civilization_name", "Unknown"),
        setting_description=data.get("setting_description", ""),
        phoneme_notes=data.get("phoneme_notes", ""),
        grammar=GrammarRules.from_dict(data.get("grammar", {})),
        development_notes=data.get("development_notes", ""),
    )

    language.add_words(normalized, growth_day=date.today(), force=True)
    return language


def generate_daily_growth(language: GrowingLanguage, growth_day: date, words_to_add: int | None = None, progress_cb=None) -> list[LexiconEntry]:
    words_to_add = words_to_add or language.growth_words_per_day
    remaining = max(language.target_lexicon_size - language.lexicon_size, 0)
    if remaining == 0:
        return []

    batch_size = min(words_to_add, remaining)
    prompt = (
        _load_prompt("growth_daily.txt")
        .replace("{GROWTH_DAY}", growth_day.isoformat())
        .replace("{WORDS_TO_ADD}", str(batch_size))
        .replace("{TARGET_LEXICON_SIZE}", str(language.target_lexicon_size))
        .replace("{CURRENT_LEXICON_SIZE}", str(language.lexicon_size))
        .replace("{LANGUAGE_SPEC}", json.dumps(language.to_dict(), indent=2))
        .replace("{LEXICON_SNAPSHOT}", json.dumps(_lexicon_snapshot(language), indent=2))
    )

    preflight_ollama(required_models=(GROWTH_MODEL,))

    return _generate_validated_words(
        prompt,
        schema_name="daily growth",
        list_key="new_words",
        expected_count=batch_size,
        created_on=growth_day.isoformat(),
        source=f"growth:{growth_day.isoformat()}",
        progress_cb=progress_cb,
        existing_alien=language.existing_alien_words(),
        existing_english=language.existing_english_glosses(),
        model=GROWTH_MODEL,
        timeout=GROWTH_TIMEOUT,
    )


def days_to_target(language: GrowingLanguage) -> int:
    remaining = max(language.target_lexicon_size - language.lexicon_size, 0)
    if remaining == 0:
        return 0
    return math.ceil(remaining / max(language.growth_words_per_day, 1))

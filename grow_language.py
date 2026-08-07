#!/usr/bin/env python3
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from engine.artifact_smith import ArtifactSmith, generate_artifacts
from engine.growth_generator import days_to_target, generate_daily_growth, generate_seed_language, seed_archetype_names
from engine.growth_language import GrowingLanguage


def _parse_day(raw: str | None) -> date:
    if not raw:
        return date.today()
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _print_language_summary(language: GrowingLanguage) -> None:
    print(f"{language.language_name} [{language.language_id}]")
    print(f"Species: {language.species_name}")
    print(f"Civilization: {language.civilization_name}")
    print(f"Lexicon: {language.lexicon_size}/{language.target_lexicon_size}")
    print(f"Daily growth: {language.growth_words_per_day} words")
    print(f"Last growth: {language.last_growth_on or 'never'}")
    print(f"ETA to target: {days_to_target(language)} day(s)")


def _make_progress_reporter(verbose_llm: bool):
    def report(token: str) -> None:
        if verbose_llm:
            print(token, end="", flush=True)
            return

        stripped = token.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            print(stripped)
            sys.stdout.flush()

    return report


def cmd_init(args: argparse.Namespace) -> int:
    language = generate_seed_language(
        seed_word_count=args.seed_words,
        growth_words_per_day=args.daily_words,
        target_lexicon_size=args.target_size,
        candidate_count=args.candidates,
        archetype=args.archetype,
        progress_cb=_make_progress_reporter(args.verbose_llm),
    )
    print()
    language.save()
    _print_language_summary(language)
    print(f"Saved to {language.save_path()}")
    return 0


def cmd_grow(args: argparse.Namespace) -> int:
    language = GrowingLanguage.load(args.id)
    growth_day = _parse_day(args.date)
    if not args.force and not language.can_grow_on(growth_day):
        print(f"{language.language_name} already grew on {growth_day.isoformat()}. Use --force to add another batch.")
        return 1

    new_words = generate_daily_growth(
        language,
        growth_day=growth_day,
        words_to_add=args.words,
        progress_cb=_make_progress_reporter(args.verbose_llm),
    )
    print()
    added = language.add_words(new_words, growth_day=growth_day, force=args.force)
    language.save()

    print(f"Added {len(added)} word(s) on {growth_day.isoformat()} to {language.language_name}.")
    for word in added:
        print(f"- {word.alien} = {word.english} [{word.part_of_speech or 'unknown'} | {word.category or 'uncategorized'}]")
    print(f"Lexicon size: {language.lexicon_size}/{language.target_lexicon_size}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if args.id:
        language = GrowingLanguage.load(args.id)
        _print_language_summary(language)
        print(f"Storage: {language.save_path()}")
        if args.words:
            print()
            for word in language.words[-args.words:]:
                print(f"- {word.alien} = {word.english} [{word.part_of_speech or 'unknown'} | {word.category or 'uncategorized'}]")
        return 0

    languages = GrowingLanguage.list_languages()
    if not languages:
        print("No growing languages found.")
        return 0

    for item in languages:
        print(
            f"{item['language_name']} [{item['language_id']}]  "
            f"{item['lexicon_size']}/{item['target_lexicon_size']} words  "
            f"daily={item['growth_words_per_day']}  last={item['last_growth_on'] or 'never'}"
        )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    language = GrowingLanguage.load(args.id)
    output = {
        "language_id": language.language_id,
        "language_name": language.language_name,
        "species_name": language.species_name,
        "civilization_name": language.civilization_name,
        "setting_description": language.setting_description,
        "phoneme_notes": language.phoneme_notes,
        "grammar": language.grammar.to_dict(),
        "development_notes": language.development_notes,
        "words": [word.to_dict() for word in language.words],
    }
    if args.output:
        path = Path(args.output)
        path.write_text(json.dumps(output, indent=2))
        print(f"Wrote {path}")
        return 0

    print(json.dumps(output, indent=2))
    return 0


def cmd_artifacts(args: argparse.Namespace) -> int:
    language = GrowingLanguage.load(args.id)
    smith = ArtifactSmith(language, seed=args.seed)
    if not smith.can_compose():
        print(f"{language.language_name} has no usable words yet -- grow it first.")
        return 1

    if args.tier:
        artifacts = []
        for _ in range(args.count):
            artifact = smith.make(tier=args.tier)
            if artifact is not None:
                artifacts.append(artifact)
    else:
        artifacts = generate_artifacts(language, {1: args.count, 2: max(1, args.count // 2)}, seed=args.seed)

    if not artifacts:
        print("Could not compose any artifacts from the current lexicon.")
        return 1

    if args.json:
        print(json.dumps([a.to_dict() for a in artifacts], indent=2))
        return 0

    print(f"{language.language_name} [{language.language_id}] -- {len(artifacts)} procedural artifact(s)\n")
    for artifact in artifacts:
        print(f"  [{artifact.artifact_type}] tier {artifact.tier}  {artifact.title}")
        print(f"    {artifact.alien_text}")
        print(f"    = {artifact.english_translation}")
        parts = []
        for wb in artifact.word_breakdown:
            parts.append(f"{wb.alien}={wb.english}" + (f" ({wb.grammar_note})" if wb.grammar_note else ""))
        print(f"    glosses: {'  '.join(parts)}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Grow a conlang over time using Ollama.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new growing language.")
    init_parser.add_argument("--seed-words", type=int, default=24)
    init_parser.add_argument("--daily-words", type=int, default=8)
    init_parser.add_argument("--target-size", type=int, default=1000)
    init_parser.add_argument("--candidates", type=int, default=3)
    init_parser.add_argument("--archetype", choices=seed_archetype_names())
    init_parser.add_argument("--verbose-llm", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    grow_parser = subparsers.add_parser("grow", help="Add a batch of new words.")
    grow_parser.add_argument("--id", required=True)
    grow_parser.add_argument("--date")
    grow_parser.add_argument("--words", type=int)
    grow_parser.add_argument("--force", action="store_true")
    grow_parser.add_argument("--verbose-llm", action="store_true")
    grow_parser.set_defaults(func=cmd_grow)

    status_parser = subparsers.add_parser("status", help="Show language status.")
    status_parser.add_argument("--id")
    status_parser.add_argument("--words", type=int, default=10)
    status_parser.set_defaults(func=cmd_status)

    export_parser = subparsers.add_parser("export", help="Export a language to JSON.")
    export_parser.add_argument("--id", required=True)
    export_parser.add_argument("--output")
    export_parser.set_defaults(func=cmd_export)

    artifacts_parser = subparsers.add_parser(
        "artifacts", help="Compose procedural artifacts from a language (offline, no LLM).")
    artifacts_parser.add_argument("--id", required=True)
    artifacts_parser.add_argument("--count", type=int, default=4, help="artifacts to compose")
    artifacts_parser.add_argument("--tier", type=int, help="fix all artifacts to this tier (1-5)")
    artifacts_parser.add_argument("--seed", type=int, help="seed for reproducible composition")
    artifacts_parser.add_argument("--json", action="store_true", help="emit artifacts as JSON")
    artifacts_parser.set_defaults(func=cmd_artifacts)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

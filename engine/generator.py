import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

from .language import Language
from .artifacts import Artifact, WordBreakdown, ArtifactCollection

# Override via environment variables if needed:
#   XENOGLOSS_OLLAMA_URL, XENOGLOSS_LANGUAGE_MODEL, XENOGLOSS_HINT_MODEL
OLLAMA_URL = os.environ.get("XENOGLOSS_OLLAMA_URL", "http://localhost:11434/api/generate")
LANGUAGE_MODEL = os.environ.get("XENOGLOSS_LANGUAGE_MODEL", "qwen2.5:14b")
HINT_MODEL = os.environ.get("XENOGLOSS_HINT_MODEL", "llama3.1:8b-instruct-q4_K_M")
OLLAMA_REQUEST_TIMEOUT = int(os.environ.get("XENOGLOSS_OLLAMA_TIMEOUT", "300"))

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

ARTIFACT_TYPES_BY_TIER = {
    1: ["sign", "inscription", "map_label"],
    2: ["dialogue", "journal", "inscription"],
    3: ["journal", "law", "letter"],
    4: ["letter", "law", "speech"],
    5: ["poem", "philosophy", "prayer"],
}


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text()


def _ollama_tags_url() -> str:
    parsed = urlparse(OLLAMA_URL)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(
            f"Invalid Ollama URL '{OLLAMA_URL}'. Set XENOGLOSS_OLLAMA_URL to a full http://host:port/api/generate URL."
        )
    return f"{parsed.scheme}://{parsed.netloc}/api/tags"


def _available_model_names(payload: dict) -> set[str]:
    names = set()
    for model in payload.get("models", []):
        name = model.get("name", "").strip()
        if name:
            names.add(name)
    return names


def _model_matches(available: set[str], requested: str) -> bool:
    if requested in available:
        return True
    requested_base = requested.split(":", 1)[0]
    for candidate in available:
        candidate_base = candidate.split(":", 1)[0]
        if candidate_base == requested_base:
            return True
    return False


def preflight_ollama(required_models: tuple[str, ...] = (LANGUAGE_MODEL, HINT_MODEL)) -> dict:
    """Verify Ollama is reachable and the configured models are installed."""
    tags_url = _ollama_tags_url()
    try:
        response = requests.get(tags_url, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {tags_url}. Start Ollama and confirm the configured URL is correct."
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON from {tags_url}.") from exc

    available = _available_model_names(payload)
    missing = [model for model in required_models if not _model_matches(available, model)]
    if missing:
        installed = ", ".join(sorted(available)) if available else "none"
        missing_text = ", ".join(missing)
        raise RuntimeError(
            f"Ollama is running, but required model(s) are missing: {missing_text}. Installed models: {installed}."
        )

    return {
        "tags_url": tags_url,
        "available_models": sorted(available),
    }


def available_ollama_models() -> list[str]:
    return preflight_ollama(required_models=())["available_models"]


def _ollama(
    prompt: str,
    model: str = LANGUAGE_MODEL,
    progress_cb=None,
    retries: int = 2,
    temperature: float = 0.7,
    timeout: int = OLLAMA_REQUEST_TIMEOUT,
) -> str:
    """Call Ollama and return the full response text. Streams internally."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": temperature},
    }
    last_exc = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(OLLAMA_URL, json=payload, stream=True, timeout=timeout)
            response.raise_for_status()
            parts = []
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("response", "")
                parts.append(token)
                if progress_cb and token:
                    progress_cb(token)
            return "".join(parts)
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt < retries:
                import time
                time.sleep(2 ** attempt)  # 1s, 2s backoff
                if progress_cb:
                    progress_cb(f"\n[retrying after error: {exc}]\n")
    raise last_exc


def _extract_json(text: str) -> dict:
    """Extract JSON from LM output, handling markdown code fences."""
    # Strip markdown fences if present
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the outermost { ... } block
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LM response")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise ValueError("Malformed JSON in LM response")


def generate_language(progress_cb=None) -> Language:
    prompt = _load_prompt("language_gen.txt")
    raw = _ollama(prompt, model=LANGUAGE_MODEL, progress_cb=progress_cb)
    data = _extract_json(raw)
    return Language.from_dict(data)


def generate_artifact(language: Language, tier: int, artifact_id: str = None, progress_cb=None) -> Artifact:
    if artifact_id is None:
        artifact_id = f"artifact_{uuid.uuid4().hex[:8]}"

    import random
    artifact_type = random.choice(ARTIFACT_TYPES_BY_TIER.get(tier, ["inscription"]))

    template = _load_prompt("artifact_gen.txt")
    lang_spec = json.dumps(language.to_dict(), indent=2)
    prompt = (
        template
        .replace("{LANGUAGE_SPEC}", lang_spec)
        .replace("{ARTIFACT_TYPE}", artifact_type)
        .replace("{TIER}", str(tier))
        .replace("{ARTIFACT_ID}", artifact_id)
    )

    raw = _ollama(prompt, model=LANGUAGE_MODEL, progress_cb=progress_cb)
    data = _extract_json(raw)

    word_breakdown = [
        WordBreakdown.from_dict(w) for w in data.get("word_breakdown", [])
    ]

    return Artifact(
        id=data.get("id", artifact_id),
        title=data.get("title", f"Artifact {artifact_id}"),
        artifact_type=data.get("artifact_type", artifact_type),
        alien_text=data.get("alien_text", ""),
        english_translation=data.get("english_translation", ""),
        context_clues=data.get("context_clues", []),
        visual_description=data.get("visual_description", ""),
        key_words=data.get("key_words", []),
        tier=data.get("tier", tier),
        word_breakdown=word_breakdown,
        unlocked=tier == 1,
    )


def generate_hint(language: Language, artifact: Artifact, alien_word: str) -> str:
    """Generate a vague in-character hint about a specific word."""
    word_key = alien_word.lower()

    # Try word_breakdown first (has grammar notes), fall back to vocabulary
    breakdown = {w.alien: w for w in artifact.word_breakdown}
    entry = breakdown.get(word_key)

    if entry:
        english = entry.english
    else:
        english = language.vocabulary.get(word_key)

    if english:
        prompt = (
            f"You are LEXIS, a damaged alien translation system with partial records. "
            f"A researcher asks about the word '{alien_word}' from this text: '{artifact.alien_text}'. "
            f"The word means '{english}' but your records are incomplete. "
            f"Give a vague, atmospheric hint -- a single sentence -- that helps without revealing the answer. "
            f"Do not say the English meaning directly. Sound like a half-broken machine."
        )
    else:
        prompt = (
            f"You are LEXIS, a damaged alien translation system with partial records. "
            f"A researcher asks about the word '{alien_word}'. "
            f"You have no clear record of this word. "
            f"Respond with a single atmospheric sentence that sounds like a corrupted database entry."
        )

    return _ollama(prompt, model=HINT_MODEL).strip()


def generate_initial_campaign(progress_cb=None) -> tuple[Language, ArtifactCollection]:
    """Generate language + 3 tier-1 and 2 tier-2 artifacts for a new campaign."""
    if progress_cb:
        progress_cb("status", "Checking Ollama connection...")
    preflight_ollama()

    if progress_cb:
        progress_cb("status", "Generating alien language...")
    language = generate_language(progress_cb=lambda t: progress_cb("token", t) if progress_cb else None)

    collection = ArtifactCollection()
    tier1_count = 3
    tier2_count = 2

    for i in range(tier1_count):
        if progress_cb:
            progress_cb("status", f"Generating artifact {i + 1} of {tier1_count + tier2_count}...")
        artifact = generate_artifact(language, tier=1, progress_cb=lambda t: progress_cb("token", t) if progress_cb else None)
        collection.add(artifact)

    for i in range(tier2_count):
        if progress_cb:
            progress_cb("status", f"Generating artifact {tier1_count + i + 1} of {tier1_count + tier2_count}...")
        artifact = generate_artifact(language, tier=2, progress_cb=lambda t: progress_cb("token", t) if progress_cb else None)
        collection.add(artifact)

    # Unlock tier 1 artifacts
    collection.check_unlocks(0)

    return language, collection

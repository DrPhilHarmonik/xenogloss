import json
import uuid
from datetime import datetime
from pathlib import Path

from .language import Language
from .codex import Codex
from .artifacts import ArtifactCollection
from . import grammar_discovery

SAVES_DIR = Path(__file__).parent.parent / "data" / "saves"


class Campaign:
    def __init__(
        self,
        campaign_id: str = None,
        language: Language = None,
        artifacts: ArtifactCollection = None,
        codex: Codex = None,
        current_artifact_index: int = 0,
        created_at: str = None,
        discovered_grammar: list[str] = None,
    ):
        self.campaign_id = campaign_id or uuid.uuid4().hex[:12]
        self.language = language or Language()
        self.artifacts = artifacts or ArtifactCollection()
        self.codex = codex or Codex()
        self.current_artifact_index = current_artifact_index
        self.created_at = created_at or datetime.now().isoformat()
        # Rules the player has already been shown. Kept so that pruning a codex
        # entry cannot un-teach a rule LEXIS has announced.
        self.discovered_grammar: set[str] = set(discovered_grammar or [])

    @property
    def current_artifact(self):
        unlocked = self.artifacts.unlocked()
        if not unlocked:
            return None
        idx = min(self.current_artifact_index, len(unlocked) - 1)
        return unlocked[idx]

    def next_artifact(self) -> bool:
        unlocked = self.artifacts.unlocked()
        if self.current_artifact_index < len(unlocked) - 1:
            self.current_artifact_index += 1
            return True
        return False

    def prev_artifact(self) -> bool:
        if self.current_artifact_index > 0:
            self.current_artifact_index -= 1
            return True
        return False

    def on_codex_update(self):
        """Call after any codex change to trigger artifact unlocks."""
        self.artifacts.check_unlocks(len(self.codex.entries))

    def grammar_progress(self) -> list:
        """Score every grammar rule against the evidence in the current codex."""
        return grammar_discovery.analyze(
            self.language, self.artifacts, self.codex, self.discovered_grammar
        )

    def refresh_grammar_discovery(self) -> list:
        """Fold newly earned rules into the campaign; return the ones that just fired."""
        rows = self.grammar_progress()
        newly = [row for row in rows if row.discovered and row.rule not in self.discovered_grammar]
        self.discovered_grammar.update(row.rule for row in newly)
        return newly

    def save_path(self) -> Path:
        SAVES_DIR.mkdir(parents=True, exist_ok=True)
        return SAVES_DIR / f"{self.campaign_id}.json"

    def meta_path(self) -> Path:
        return SAVES_DIR / f"{self.campaign_id}.meta.json"

    def save(self):
        data = {
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "current_artifact_index": self.current_artifact_index,
            "language": self.language.to_dict(),
            "artifacts": self.artifacts.to_list(),
            "codex": self.codex.to_list(),
            "discovered_grammar": sorted(self.discovered_grammar),
        }
        self.save_path().write_text(json.dumps(data, indent=2))
        # Keep a lightweight sidecar so list_saves doesn't need to parse the full file
        meta = self.to_meta()
        self.meta_path().write_text(json.dumps(meta))

    def to_meta(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "language_name": self.language.language_name,
            "species_name": self.language.species_name,
            "codex_size": len(self.codex.entries),
        }

    @classmethod
    def load(cls, campaign_id: str) -> "Campaign":
        path = SAVES_DIR / f"{campaign_id}.json"
        data = json.loads(path.read_text())
        campaign = cls(
            campaign_id=data["campaign_id"],
            language=Language.from_dict(data["language"]),
            artifacts=ArtifactCollection.from_list(data["artifacts"]),
            codex=Codex.from_list(data["codex"]),
            current_artifact_index=data.get("current_artifact_index", 0),
            created_at=data.get("created_at", ""),
            discovered_grammar=data.get("discovered_grammar", []),
        )
        # Backfill sidecar if it was created before this feature existed
        if not campaign.meta_path().exists():
            campaign.save()
        return campaign

    @classmethod
    def list_saves(cls) -> list[dict]:
        SAVES_DIR.mkdir(parents=True, exist_ok=True)
        saves_by_id: dict[str, dict] = {}

        for path in sorted(SAVES_DIR.glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                meta = json.loads(path.read_text())
                campaign_id = meta.get("campaign_id")
                if campaign_id:
                    saves_by_id[campaign_id] = meta
            except Exception:
                continue

        for path in sorted(SAVES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.name.endswith(".meta.json"):
                continue
            campaign_id = path.stem
            if campaign_id in saves_by_id:
                continue
            try:
                campaign = cls.load(campaign_id)
                saves_by_id[campaign_id] = campaign.to_meta()
            except Exception:
                continue

        return sorted(
            saves_by_id.values(),
            key=lambda save: save.get("created_at", ""),
            reverse=True,
        )

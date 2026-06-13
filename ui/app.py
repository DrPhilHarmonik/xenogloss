from __future__ import annotations

import threading
from typing import Optional

from rich.text import Text, Text as RichText
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, LoadingIndicator, RichLog, Static

from engine.campaign import Campaign
from engine.codex import CONFIDENCE_COLORS, CONFIDENCE_LEVELS, strip_punctuation
from engine.generator import generate_hint, generate_initial_campaign


# ---------------------------------------------------------------------------
# Artifact display
# ---------------------------------------------------------------------------

class ArtifactPanel(ScrollableContainer):
    DEFAULT_CSS = """
    ArtifactPanel {
        width: 2fr;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ArtifactPanel #artifact-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    ArtifactPanel #artifact-type-badge {
        color: $text-muted;
        margin-bottom: 1;
    }
    ArtifactPanel #artifact-visual {
        color: $text-muted;
        margin-bottom: 1;
    }
    ArtifactPanel #artifact-alien-text {
        margin-bottom: 1;
    }
    ArtifactPanel #context-header {
        color: $warning;
        text-style: bold;
        margin-top: 1;
    }
    ArtifactPanel #artifact-context {
        color: $text-muted;
    }
    ArtifactPanel #nav-info {
        color: $text-muted;
        margin-top: 1;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("", id="artifact-title")
        yield Label("", id="artifact-type-badge")
        yield Static("", id="artifact-visual")
        yield Static("", id="artifact-alien-text")
        yield Label("", id="artifact-coverage")
        yield Label("CONTEXT CLUES", id="context-header")
        yield Static("", id="artifact-context")
        yield Label("", id="nav-info")

    def update(self, campaign: Campaign):
        artifact = campaign.current_artifact
        if artifact is None:
            self.query_one("#artifact-title", Label).update("No artifacts unlocked")
            return

        unlocked = campaign.artifacts.unlocked()
        idx = campaign.current_artifact_index
        nav = f"Artifact {idx + 1} of {len(unlocked)}  |  Tier {artifact.tier}  |  :next / :prev to navigate"

        self.query_one("#artifact-title", Label).update(artifact.title)
        self.query_one("#artifact-type-badge", Label).update(f"[{artifact.artifact_type.upper()}]")
        self.query_one("#artifact-visual", Static).update(artifact.visual_description)
        self.query_one("#artifact-alien-text", Static).update(
            _render_alien_text(artifact.alien_text, campaign.codex)
        )

        known, total = campaign.codex.coverage(artifact.alien_text)
        pct = int(known / total * 100) if total else 0
        bar = ("=" * int(pct / 5)).ljust(20)
        coverage_text = f"Words decoded: {known}/{total}  [{bar}] {pct}%"
        self.query_one("#artifact-coverage", Label).update(coverage_text)

        clues = "\n".join(f"  * {c}" for c in artifact.context_clues)
        self.query_one("#artifact-context", Static).update(clues or "No context clues recorded.")
        self.query_one("#nav-info", Label).update(nav)


def _render_alien_text(alien_text: str, codex) -> Text:
    """Color-code alien words based on codex knowledge."""
    result = Text()
    tokens = alien_text.split()
    for i, raw_word in enumerate(tokens):
        stripped = strip_punctuation(raw_word).lower()
        suffix_start = len(raw_word.rstrip(".,!?;:\"'()[]"))
        punctuation_suffix = raw_word[suffix_start:]
        entry = codex.get(stripped)
        if entry:
            color = CONFIDENCE_COLORS[entry.confidence]
            result.append(raw_word[:suffix_start], style=f"bold {color}")
            if punctuation_suffix:
                result.append(punctuation_suffix)
        else:
            result.append(raw_word)
        if i < len(tokens) - 1:
            result.append(" ")
    return result


# ---------------------------------------------------------------------------
# Codex panel
# ---------------------------------------------------------------------------

class CodexPanel(ScrollableContainer):
    DEFAULT_CSS = """
    CodexPanel {
        width: 1fr;
        border: round $secondary;
        padding: 1 2;
        background: $surface;
    }
    CodexPanel #codex-header {
        color: $secondary;
        text-style: bold;
        margin-bottom: 1;
    }
    CodexPanel #codex-entries {
        height: auto;
    }
    CodexPanel #codex-empty {
        color: $text-muted;
        text-style: italic;
    }
    CodexPanel #coverage-info {
        color: $text-muted;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("CODEX", id="codex-header")
        yield Static("", id="codex-entries")
        yield Label("No entries yet.", id="codex-empty")
        yield Label("", id="coverage-info")

    def update(self, campaign: Campaign, sort_by: str = "alpha"):
        artifact_tiers = {a.id: a.tier for a in campaign.artifacts.artifacts}
        entries = campaign.codex.sorted_entries(sort_by, artifact_tiers)
        freq = campaign.artifacts.word_frequency()

        empty_label = self.query_one("#codex-empty", Label)
        entries_widget = self.query_one("#codex-entries", Static)

        if not entries:
            empty_label.display = True
            entries_widget.update("")
        else:
            empty_label.display = False
            text = Text()
            for e in entries:
                color = CONFIDENCE_COLORS[e["confidence"]]
                text.append(f"{e['alien_word']}", style=f"bold {color}")
                text.append(f" = {e['player_guess']}")
                badge = {"certain": " [C]", "probable": " [P]", "guessing": " [?]"}[e["confidence"]]
                text.append(badge, style=f"dim {color}")
                count = freq.get(e["alien_word"], 0)
                if count > 1:
                    text.append(f"  ×{count}", style="dim")
                text.append("\n")
                if e.get("notes"):
                    text.append(f"  ↳ {e['notes']}\n", style="dim italic")
            entries_widget.update(text)

        artifact = campaign.current_artifact
        if artifact:
            known, total = campaign.codex.coverage(artifact.alien_text)
            pct = int(known / total * 100) if total else 0
            self.query_one("#coverage-info", Label).update(
                f"This artifact: {known}/{total} words known ({pct}%)\n"
                f"Total codex: {len(entries)} words  |  sorted: {sort_by}"
            )


# ---------------------------------------------------------------------------
# Loading screen
# ---------------------------------------------------------------------------

class LoadingScreen(Vertical):
    DEFAULT_CSS = """
    LoadingScreen {
        align: center middle;
        background: $background;
        padding: 2 4;
    }
    LoadingScreen #loading-title {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    LoadingScreen #loading-status {
        text-align: center;
        color: $warning;
        margin-bottom: 1;
    }
    LoadingScreen LoadingIndicator {
        height: 1;
        margin-bottom: 1;
    }
    LoadingScreen #token-stream {
        height: 12;
        border: round $surface-lighten-1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("X E N O G L O S S", id="loading-title")
        yield Label("Initializing...", id="loading-status")
        yield LoadingIndicator()
        yield RichLog(id="token-stream", wrap=True, highlight=False, markup=False)

    def set_status(self, msg: str):
        self.query_one("#loading-status", Label).update(msg)
        # Clear the stream log on each new phase
        self.query_one("#token-stream", RichLog).clear()

    def append_token(self, token: str):
        log = self.query_one("#token-stream", RichLog)
        log.write(RichText(token), scroll_end=True)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

HELP_TEXT = """\
[bold]HOW TO PLAY[/bold]
  You are looking at alien text. Read the context clues on the left panel.
  When you think you know what an alien word means, type it into the box below:

    [cyan]veth water[/cyan]              -- "veth means water" (default: guessing)
    [cyan]veth water certain[/cyan]      -- mark as certain
    [cyan]veth water probable[/cyan]     -- mark as probable

  Known words highlight in the artifact text: [green]green=certain[/green] [cyan]cyan=probable[/cyan] [yellow]yellow=guessing[/yellow]
  As your codex grows, new artifacts unlock. The message bar shows your coverage.

[bold]COMMANDS[/bold]
  [cyan]:next[/cyan]  [cyan]:prev[/cyan]               Navigate between unlocked artifacts
  [cyan]:list[/cyan]                  Show all artifacts and unlock progress
  [cyan]:find word[/cyan]             Show which artifacts contain a word
  [cyan]:search meaning[/cyan]        Search the codex by English meaning
  [cyan]:note word your note[/cyan]   Attach a note to a codex entry (shown below it)
  [cyan]:note word[/cyan]             Show the current note for a codex entry
  [cyan]:codex[/cyan]                 Show codex sorted by current mode
  [cyan]:codex alpha[/cyan]           Sort codex alphabetically (default)
  [cyan]:codex confidence[/cyan]      Sort codex by confidence (certain first)
  [cyan]:codex artifact[/cyan]        Sort codex by first-seen artifact tier
  [cyan]:hint word[/cyan]             Ask LEXIS (AI) for a vague clue about a word
  [cyan]:forget word[/cyan]           Remove a wrong guess from your codex
  [cyan]:translate text[/cyan]        Record your full translation attempt for this artifact
  [cyan]:mytranslation[/cyan]         Show your recorded translation for this artifact
  [cyan]:check[/cyan]                 Compare your translation to the actual (spoiler)
  [cyan]:reveal[/cyan]                Show all translations when every artifact is solved
  [cyan]:grammar[/cyan]               Show grammar rules (word order, suffixes, etc.)
  [cyan]:info[/cyan]                  Show civilization background lore
  [cyan]:help[/cyan]                  Show this message
"""


class XenoglossApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #content {
        layout: horizontal;
        height: 1fr;
    }
    #command-bar {
        dock: bottom;
        height: 3;
        border: round $accent;
        padding: 0 1;
    }
    #message-bar {
        height: auto;
        max-height: 8;
        padding: 0 1;
        color: $warning;
        background: $surface;
        border-top: dashed $surface-lighten-2;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+n", "next_artifact", "Next"),
        Binding("ctrl+p", "prev_artifact", "Prev"),
    ]

    loading = reactive(True)

    def __init__(self, existing_campaign: Optional[Campaign] = None, **kwargs):
        super().__init__(**kwargs)
        self.campaign: Optional[Campaign] = existing_campaign
        self._hint_in_progress: bool = False
        self._codex_sort: str = "alpha"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield LoadingScreen(id="loading-screen")
        with Container(id="content"):
            yield ArtifactPanel(id="artifact-panel")
            yield CodexPanel(id="codex-panel")
        yield Static("", id="message-bar", markup=True)
        yield Input(placeholder=":help for commands   |   word meaning [certain|probable]", id="command-bar")
        yield Footer()

    def on_mount(self):
        self.title = "XENOGLOSS -- Alien Language Decoder"
        self.query_one("#content").display = False
        self.query_one("#message-bar").display = False
        self.query_one("#command-bar").display = False
        self._start_generation()

    def _start_generation(self):
        if self.campaign is not None:
            self._finish_loading()
            return
        thread = threading.Thread(target=self._generate_campaign, daemon=True)
        thread.start()

    def _generate_campaign(self):
        def progress(kind, value):
            if kind == "status":
                self.call_from_thread(self._set_loading_status, value)
            elif kind == "token":
                self.call_from_thread(self._append_loading_token, value)

        try:
            language, artifacts = generate_initial_campaign(progress_cb=progress)
            campaign = Campaign(language=language, artifacts=artifacts)
            campaign.save()
            self.campaign = campaign
            self.call_from_thread(self._finish_loading)
        except Exception as e:
            self.call_from_thread(
                self._set_loading_status,
                f"Startup check failed: {e}\nSet XENOGLOSS_OLLAMA_URL / XENOGLOSS_LANGUAGE_MODEL / XENOGLOSS_HINT_MODEL if needed.",
            )

    def _set_loading_status(self, msg: str):
        self.query_one(LoadingScreen).set_status(msg)

    def _append_loading_token(self, token: str):
        self.query_one(LoadingScreen).append_token(token)

    def _finish_loading(self):
        self.query_one(LoadingScreen).display = False
        self.query_one("#content").display = True
        self.query_one("#message-bar").display = True
        self.query_one("#command-bar").display = True
        self.loading = False
        self._refresh_panels()
        self.query_one("#command-bar", Input).focus()

        lang = self.campaign.language
        self._show_message(
            f"Language loaded: [bold]{lang.language_name}[/bold] "
            f"(spoken by the [italic]{lang.species_name}[/italic]). "
            f"Begin decoding."
        )

    def _refresh_panels(self):
        if self.campaign is None:
            return
        self.query_one(ArtifactPanel).update(self.campaign)
        self.query_one(CodexPanel).update(self.campaign, self._codex_sort)

    def _show_message(self, msg: str):
        self.query_one("#message-bar", Static).update(msg)

    # ------------------------------------------------------------------
    # Command parsing
    # ------------------------------------------------------------------

    @on(Input.Submitted, "#command-bar")
    def handle_command(self, event: Input.Submitted):
        raw = event.value.strip()
        self.query_one("#command-bar", Input).clear()

        if not raw or self.campaign is None:
            return

        if raw.startswith(":"):
            self._handle_colon_command(raw[1:])
        else:
            self._handle_define(raw)

    def _handle_colon_command(self, cmd: str):
        parts = cmd.strip().split(None, 1)
        verb = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if verb in ("next", "n"):
            self.action_next_artifact()
        elif verb in ("prev", "p"):
            self.action_prev_artifact()
        elif verb == "forget":
            self._handle_forget(arg)
        elif verb == "translate":
            self._handle_translate(arg)
        elif verb == "mytranslation":
            self._handle_show_translation()
        elif verb == "check":
            self._handle_check()
        elif verb == "reveal":
            if arg.strip().lower() == "confirm":
                self._handle_reveal_confirmed()
            else:
                self._handle_reveal()
        elif verb == "hint":
            self._handle_hint(arg)
        elif verb == "find":
            self._handle_find(arg)
        elif verb == "search":
            self._handle_search(arg)
        elif verb == "note":
            self._handle_note(arg)
        elif verb == "codex":
            self._handle_codex_sort(arg)
        elif verb == "grammar":
            self._show_message(self.campaign.language.grammar_summary())
        elif verb == "info":
            lang = self.campaign.language
            self._show_message(
                f"[bold]{lang.civilization_name}[/bold] -- {lang.setting_description}"
            )
        elif verb == "list":
            self._handle_list()
        elif verb == "help":
            self._show_message(HELP_TEXT)
        else:
            self._show_message(f"Unknown command: :{verb}   Type :help for commands.")

    def _handle_define(self, raw: str):
        parts = raw.split()
        if len(parts) < 2:
            self._show_message("Usage: [cyan]word meaning[/cyan] or [cyan]word meaning certain[/cyan]")
            return

        confidence = "guessing"
        if parts[-1].lower() in CONFIDENCE_LEVELS:
            confidence = parts[-1].lower()
            alien_word = parts[0].lower()
            meaning = " ".join(parts[1:-1])
        else:
            alien_word = parts[0].lower()
            meaning = " ".join(parts[1:])

        if not meaning:
            self._show_message("Please provide a meaning.")
            return

        artifact = self.campaign.current_artifact
        artifact_id = artifact.id if artifact else ""
        self.campaign.codex.add(alien_word, meaning, confidence, artifact_id)
        self.campaign.on_codex_update()
        self.campaign.save()
        self._refresh_panels()
        color = CONFIDENCE_COLORS[confidence]
        msg = f"Codex: [{color}]{alien_word}[/{color}] = {meaning}  [{confidence}]"

        if confidence == "certain":
            warning = self._validate_certain(alien_word, meaning)
            if warning:
                msg += f"\n{warning}"

        self._show_message(msg)

    def _handle_list(self):
        from engine.artifacts import UNLOCK_THRESHOLDS
        codex_size = len(self.campaign.codex.entries)
        lines = ["[bold]ARTIFACTS[/bold]"]
        for artifact in self.campaign.artifacts.artifacts:
            threshold = UNLOCK_THRESHOLDS.get(artifact.tier, 0)
            if artifact.unlocked:
                solved_tag = "  [bold green]SOLVED[/bold green]" if artifact.solved else ""
                marker = f"[green]unlocked[/green]{solved_tag}"
            else:
                needed = threshold - codex_size
                marker = f"[dim]locked -- decode {needed} more words[/dim]"
            lines.append(f"  Tier {artifact.tier}  {artifact.title}  [{artifact.artifact_type}]  {marker}")
        self._show_message("\n".join(lines))

    def _handle_forget(self, word: str):
        word = word.strip().lower()
        if not word:
            self._show_message("Usage: :forget word")
            return
        if word in self.campaign.codex.entries:
            self.campaign.codex.remove(word)
            self.campaign.save()
            self._refresh_panels()
            self._show_message(f"Removed '{word}' from codex.")
        else:
            self._show_message(f"'{word}' not in codex.")

    def _handle_find(self, word: str):
        word = word.strip().lower()
        if not word:
            self._show_message("Usage: :find alien_word")
            return

        matches = self.campaign.artifacts.find_by_word(word, unlocked_only=False)
        if not matches:
            self._show_message(f"No artifacts contain '{word}'.")
            return

        lines = [f"[bold]ARTIFACTS CONTAINING '{word}'[/bold]"]
        current = self.campaign.current_artifact
        for artifact in matches:
            status = "[green]unlocked[/green]" if artifact.unlocked else "[dim]locked[/dim]"
            solved = " [bold green]SOLVED[/bold green]" if artifact.solved else ""
            marker = " [cyan]< current[/cyan]" if current and artifact.id == current.id else ""
            lines.append(
                f"  Tier {artifact.tier}  {artifact.title}  [{artifact.artifact_type}]  {status}{solved}{marker}"
            )
        self._show_message("\n".join(lines))

    def _handle_search(self, query: str):
        query = query.strip()
        if not query:
            self._show_message("Usage: :search english_meaning")
            return

        matches = self.campaign.codex.search_by_guess(query)
        if not matches:
            self._show_message(f"No codex entries match '{query}'.")
            return

        lines = [f"[bold]CODEX MATCHES FOR '{query}'[/bold]"]
        for entry in matches:
            color = CONFIDENCE_COLORS[entry.confidence]
            origin = f"  first seen: {entry.first_seen_in}" if entry.first_seen_in else ""
            lines.append(
                f"  [{color}]{entry.alien_word}[/{color}] = {entry.player_guess}  [{entry.confidence}]{origin}"
            )
        self._show_message("\n".join(lines))

    def _handle_note(self, arg: str):
        parts = arg.strip().split(None, 1)
        if not parts:
            self._show_message("Usage: :note alien_word your note here")
            return
        word = parts[0].lower()
        if word not in self.campaign.codex.entries:
            self._show_message(f"'{word}' is not in your codex yet.")
            return
        if len(parts) == 1:
            # Show existing note
            entry = self.campaign.codex.get(word)
            if entry.notes:
                self._show_message(f"Note for [bold]{word}[/bold]: {entry.notes}")
            else:
                self._show_message(f"No note for '{word}'. Use :note {word} your text here to add one.")
            return
        notes_text = parts[1]
        self.campaign.codex.update_notes(word, notes_text)
        self.campaign.save()
        self._refresh_panels()
        self._show_message(f"Note saved for [bold]{word}[/bold]: {notes_text}")

    def _handle_codex_sort(self, arg: str):
        sort = arg.strip().lower()
        valid = ("alpha", "confidence", "artifact")
        if sort not in valid:
            if sort:
                self._show_message(f"Unknown sort: '{sort}'. Options: alpha, confidence, artifact")
            else:
                self._show_message(f"Codex sort: [bold]{self._codex_sort}[/bold]  |  Options: alpha, confidence, artifact")
            return
        self._codex_sort = sort
        self._refresh_panels()
        self._show_message(f"Codex sorted by: [bold]{sort}[/bold]")

    def _handle_translate(self, text: str):
        artifact = self.campaign.current_artifact
        if not artifact:
            return
        if not text.strip():
            self._show_message("Usage: :translate your translation here")
            return
        artifact.player_translation = text.strip()
        artifact.solved = True
        self.campaign.save()
        self._show_message(f"Translation recorded for '[bold]{artifact.title}[/bold]'. Marked as solved.")
        self._check_endgame()

    def _handle_show_translation(self):
        artifact = self.campaign.current_artifact
        if not artifact:
            self._show_message("No artifact selected.")
            return
        if not artifact.player_translation:
            self._show_message("No translation recorded yet. Use :translate your text here")
            return
        self._show_message(
            f"[bold]{artifact.title}[/bold] -- your translation:\n  {artifact.player_translation}"
        )

    def _validate_certain(self, alien_word: str, player_guess: str) -> str:
        """Check a 'certain' codex entry against the vocabulary. Returns a warning string or empty."""
        vocab = self.campaign.language.vocabulary
        if alien_word not in vocab:
            return ""  # word not in generated vocab -- possibly a suffix form, skip
        correct = vocab[alien_word].lower().strip()
        guess = player_guess.lower().strip()
        # Allow if any word in the player's guess matches any word in the correct meaning
        correct_words = set(correct.split())
        guess_words = set(guess.split())
        if guess_words & correct_words:
            return ""  # at least one overlapping word -- close enough
        return (
            "[yellow]LEXIS: Warning -- certainty flag registered, but my records show "
            "a discrepancy. You may wish to reconsider.[/yellow]"
        )

    def _handle_check(self):
        """Show player translation vs. actual translation for the current artifact."""
        artifact = self.campaign.current_artifact
        if not artifact:
            self._show_message("No artifact selected.")
            return
        if not artifact.player_translation:
            self._show_message(
                "No translation recorded yet. Use [cyan]:translate your text here[/cyan] first."
            )
            return
        self._show_message(
            f"[bold]{artifact.title}[/bold]\n"
            f"\n[cyan]Your translation:[/cyan]\n  {artifact.player_translation}"
            f"\n\n[yellow]Actual translation:[/yellow]\n  {artifact.english_translation}"
        )

    def _handle_reveal(self):
        """Show all artifact translations -- full spoiler. Warns first if not all solved."""
        artifacts = self.campaign.artifacts.unlocked()
        unsolved = [a for a in artifacts if not a.solved]
        if unsolved:
            self._show_message(
                f"[yellow]Warning:[/yellow] {len(unsolved)} artifact(s) not yet solved. "
                f"Use [cyan]:check[/cyan] for the current artifact, or type [cyan]:reveal confirm[/cyan] to see all anyway."
            )
            return
        self._show_full_reveal(artifacts)

    def _handle_reveal_confirmed(self):
        self._show_full_reveal(self.campaign.artifacts.unlocked())

    def _show_full_reveal(self, artifacts):
        lines = ["[bold]-- FULL TRANSLATION RECORD --[/bold]\n"]
        for a in artifacts:
            status = "[green]SOLVED[/green]" if a.solved else "[dim]unsolved[/dim]"
            lines.append(f"[bold]{a.title}[/bold]  {status}")
            lines.append(f"  [cyan]Yours:[/cyan]  {a.player_translation or '[dim]none recorded[/dim]'}")
            lines.append(f"  [yellow]Actual:[/yellow] {a.english_translation}")
            lines.append("")
        self._show_message("\n".join(lines))

    def _check_endgame(self):
        """Fire the end-game reveal if every unlocked artifact is now solved."""
        artifacts = self.campaign.artifacts.unlocked()
        if artifacts and all(a.solved for a in artifacts):
            self._show_message(
                "[bold green]-- ALL ARTIFACTS TRANSLATED --[/bold green]\n\n"
                "[dim]LEXIS: All records reconciled. Translation archive complete.[/dim]\n\n"
                "Use [cyan]:reveal[/cyan] to see the full translation record."
            )

    def _handle_hint(self, word: str):
        word = word.strip().lower()
        artifact = self.campaign.current_artifact
        if not artifact:
            self._show_message("No artifact selected.")
            return
        if not word:
            self._show_message("Usage: :hint word")
            return
        if self._hint_in_progress:
            self._show_message("[dim]LEXIS is still processing. Please wait...[/dim]")
            return
        self._hint_in_progress = True
        self._show_message(f"[dim]Querying LEXIS for '{word}'...[/dim]")

        def run():
            try:
                hint = generate_hint(self.campaign.language, artifact, word)
                self.call_from_thread(self._show_message, f"[dim italic]LEXIS >> {hint}[/dim italic]")
            finally:
                self.call_from_thread(setattr, self, "_hint_in_progress", False)

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_next_artifact(self):
        if self.campaign and self.campaign.next_artifact():
            self._refresh_panels()
            self._show_message("Viewing next artifact.")
        else:
            self._show_message("No more unlocked artifacts. Keep filling your codex.")

    def action_prev_artifact(self):
        if self.campaign and self.campaign.prev_artifact():
            self._refresh_panels()
            self._show_message("Viewing previous artifact.")
        else:
            self._show_message("Already at the first artifact.")

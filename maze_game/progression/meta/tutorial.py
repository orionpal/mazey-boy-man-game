"""
meta/tutorial.py
-----------------
An optional, skippable sequence of tiny practice mazes shown before a
player's first real Labyrinth run: movement (arrows/WASD), a single plain
pellet, and the goal -- no augments, no hazards, nothing to draft. Only the
final step adds a real countdown timer, so the run's core time-pressure
mechanic isn't a total surprise the first time it actually matters.

Lives under meta/ rather than as its own top-level package: its persisted
"has this player already seen it" flag (tutorial_completed) is exactly the
kind of persistent, run-preceding state meta/__init__.py already owns --
load_tutorial_completed()/save_tutorial_completed() below mirror
load_gold_total()/save_gold_total()'s (hazards.py) shape exactly, right
down to reusing a bare on-disk JSON file next to APP_ROOT.

Deliberately does NOT import progression/run.py for its TimeResource --
run.py already imports *this* package (MetaProgress seeds a fresh Build),
so a reverse import here would be circular. _CountdownTimer below is an
intentionally small, local copy of that same tick()/resync() shape instead
-- run.py's own RotationTimer already sets this precedent (see its
docstring for why reusing the shape, not the class, is the right call).

Pure state, no pygame dependency -- same pattern as every other game-mode
class (freeplay/game.py::Game, progression/run.py::LabyrinthRun).
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

from maze_game.constants import TUTORIAL_TIMED_STEP_SECONDS, APP_ROOT
from maze_game.maze import generate_maze, farthest_reachable_cell
from maze_game.player import slide

START_POS: tuple[int, int] = (1, 1)

DEFAULT_TUTORIAL_STATE_PATH = APP_ROOT / "tutorial.json"


@dataclass(frozen=True)
class TutorialStep:
    cols: int
    rows: int
    timed: bool
    message: str


TUTORIAL_STEPS: list[TutorialStep] = [
    TutorialStep(5, 5, False, "Slide with arrow keys or WASD -- you stop at walls and junctions."),
    TutorialStep(7, 7, False, "Grab the pellet, then reach the goal to clear a maze."),
    TutorialStep(7, 7, True, "Real runs are timed -- reach the goal before the clock runs out!"),
]


def load_tutorial_completed(path: Path = DEFAULT_TUTORIAL_STATE_PATH) -> bool:
    """False (not yet seen) if the file is missing, unreadable, or malformed -- mirrors hazards.py::load_gold_total()'s shape."""
    if not path.exists():
        return False
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("completed", False))


def save_tutorial_completed(value: bool, path: Path = DEFAULT_TUTORIAL_STATE_PATH) -> None:
    path.write_text(json.dumps({"completed": value}))


class _CountdownTimer:
    """
    Ticks down by real elapsed time (self-correcting via time.monotonic()),
    same tick()/resync() shape as run.py's TimeResource/RotationTimer --
    kept as a local copy here rather than a shared import to avoid a
    circular import (see module docstring).
    """

    def __init__(self, seconds: float) -> None:
        self.remaining = seconds
        self._last_tick = time.monotonic()

    def tick(self) -> None:
        now = time.monotonic()
        self.remaining -= now - self._last_tick
        self._last_tick = now

    @property
    def depleted(self) -> bool:
        return self.remaining <= 0.0


class TutorialRun:
    """
    Steps through TUTORIAL_STEPS in order. `finished` flips to True once
    every step is cleared, or the player skips early (skip()) -- the caller
    (progression/app.py::run_tutorial()) ends its loop the moment this
    happens. tutorial_completed is persisted the instant that happens too
    (inside _finish()), not left for the caller to remember to do.
    """

    def __init__(self, seed: int | None = None, state_path: Path = DEFAULT_TUTORIAL_STATE_PATH) -> None:
        self.rng = random.Random(seed)
        self.state_path = state_path
        self.step_index = 0
        self.finished = False
        self.events: list[str] = []
        self._begin_step()

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def step(self) -> TutorialStep:
        return TUTORIAL_STEPS[self.step_index]

    @property
    def is_last_step(self) -> bool:
        return self.step_index == len(TUTORIAL_STEPS) - 1

    def move(self, direction: tuple[int, int]) -> None:
        if self.finished or self.step_failed:
            return
        new_pos = slide(self.grid, self.player, direction)
        if new_pos != self.player:
            self.events.append("move")
        self.player = new_pos
        if self.pellet is not None and self.player == self.pellet:
            self.pellet = None
            self.events.append("pellet")
        if self.player == self.goal:
            self.events.append("maze_complete")
            self._advance()

    def update(self) -> None:
        """Advance the countdown on a timed step. Call once per frame; a no-op on every untimed step."""
        if self.finished or self.timer is None or self.step_failed:
            return
        self.timer.tick()
        if self.timer.depleted:
            self.step_failed = True
            self.events.append("fail")

    def retry_step(self) -> None:
        """After a timed step's countdown runs out: re-roll the same step with a fresh maze, rather than restarting the whole tutorial."""
        self._begin_step()

    def skip(self) -> None:
        """ESC at any point -- ends the tutorial immediately, same end state as clearing every step."""
        self._finish()

    # ── Private helpers ───────────────────────────────────────────────────

    def _advance(self) -> None:
        if self.is_last_step:
            self._finish()
            return
        self.step_index += 1
        self._begin_step()

    def _finish(self) -> None:
        self.finished = True
        save_tutorial_completed(True, self.state_path)

    def _begin_step(self) -> None:
        step = self.step
        self.cols, self.rows = step.cols, step.rows
        self.grid = generate_maze(step.cols, step.rows, rng=self.rng)
        self.player = START_POS
        self.goal = farthest_reachable_cell(self.grid, START_POS)
        open_cells = [
            (x, y)
            for y, row in enumerate(self.grid)
            for x, cell in enumerate(row)
            if cell == 0 and (x, y) not in (START_POS, self.goal)
        ]
        self.pellet: tuple[int, int] | None = self.rng.choice(open_cells) if open_cells else None
        self.timer = _CountdownTimer(TUTORIAL_TIMED_STEP_SECONDS) if step.timed else None
        self.step_failed = False

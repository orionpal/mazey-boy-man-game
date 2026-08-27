"""
run/model.py
------------
The small value types and pure pacing math the labyrinth progression is
built out of, split off from run/state.py so the state machine itself
stays readable:

- ``TimeResource`` -- the run's single persistent, self-correcting time
  budget (pellets add, hazards subtract, zero ends the run).
- ``FirstMazeRecord`` / ``Popup`` -- immutable-ish snapshots the renderer
  and the 3D arena interlude read.
- ``dimensions_for_maze()`` / ``is_milestone_maze()`` -- the maze-size
  ramp, including the one-off milestone spike.
- ``_breaks_due_after()`` -- which break screens a given maze index
  triggers (see run/breaks.py for how they stack).

All pure -- no pygame, no LabyrinthRun -- same "testable without a
display" rule the rest of this package follows.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from maze_game.constants import (
    LABYRINTH_TOTAL_MAZES, LABYRINTH_GROUP_SIZE,
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
    MILESTONE_INTERVAL, MILESTONE_DIMENSION_BOOST, MILESTONE_MAX_DIMENSION,
    AUGMENT_INTERVAL,
)

START_POS: tuple[int, int] = (1, 1)


@dataclass
class FirstMazeRecord:
    """
    Immutable snapshot of the very first maze of a run, captured the moment
    it is cleared (before _begin_maze() overwrites self.grid/self.trail for
    maze 2). This is what the 3D arena interlude renders against after the
    first group of 5 mazes -- same layout, same recorded route as a colour
    trail. See docs/planning/3d-rework.md.
    """

    grid: list[list[int]]
    goal: tuple[int, int]
    trail: list[tuple[int, int]]
    start: tuple[int, int]


@dataclass
class Popup:
    """A brief floating "+Xs"/"-Xs" label wherever a pellet, hazard, or speed bonus changes the time resource."""

    pos: tuple[int, int]
    text: str
    color: tuple[int, int, int]
    created_at: float


# Breaks should always coincide with (or be subsumed by) the group cadence,
# so a modifier or milestone maze is never a total surprise with zero
# preceding screen -- a pacing-predictability invariant, not strictly
# required for correctness (an unaligned interval would just show fewer
# break screens, not crash), but worth failing loudly on if retuned
# inconsistently.
assert AUGMENT_INTERVAL % LABYRINTH_GROUP_SIZE == 0
assert MILESTONE_INTERVAL % AUGMENT_INTERVAL == 0


def _breaks_due_after(completed_index: int) -> list[str]:
    """Which break screens (in order) should show after finishing `completed_index`, before the next maze begins."""
    breaks = []
    if completed_index % LABYRINTH_GROUP_SIZE == 0:
        breaks.append("shop")
    if completed_index % AUGMENT_INTERVAL == 0:
        breaks.append("augment")
    return breaks


def _random_seed() -> int:
    """
    Pick a fresh run seed. Deliberately uses the bare global `random`, not a
    `LabyrinthRun.rng` instance -- choosing *which* seed to start a run with
    is inherently a one-off, non-reproducible decision, not part of the
    reproducible sequence a seed is meant to pin down.
    """
    return random.randrange(2**32)


def is_milestone_maze(maze_index: int) -> bool:
    """Every MILESTONE_INTERVAL-th maze, and always the final maze -- see dimensions_for_maze()."""
    return maze_index % MILESTONE_INTERVAL == 0 or maze_index == LABYRINTH_TOTAL_MAZES


def dimensions_for_maze(maze_index: int) -> tuple[int, int]:
    """
    maze_index is 1-based (1..LABYRINTH_TOTAL_MAZES). Square mazes: starts
    at MIN_DIMENSION, +DIMENSION_STEP per completed group of
    LABYRINTH_GROUP_SIZE, capped at MAX_DIMENSION -- except on a milestone
    maze (is_milestone_maze()), which gets a one-off MILESTONE_DIMENSION_BOOST
    spike on top of that (capped separately at MILESTONE_MAX_DIMENSION,
    since several milestones already sit at MAX_DIMENSION under the normal
    ramp), reverting to the regular ramp on the very next maze.
    """
    group_index = (maze_index - 1) // LABYRINTH_GROUP_SIZE  # 0-based
    size = min(MIN_DIMENSION + group_index * DIMENSION_STEP, MAX_DIMENSION)
    if is_milestone_maze(maze_index):
        size = min(size + MILESTONE_DIMENSION_BOOST, MILESTONE_MAX_DIMENSION)
    return size, size


class TimeResource:
    """
    The run's single persistent time budget. Ticks down by real elapsed
    time (self-correcting via time.monotonic(), not a passed-in per-frame
    delta -- avoids both frame-timing drift and a ms/s unit mismatch with
    pygame's clock), topped up by pellets, drained by hazards.
    """

    def __init__(self, amount: float) -> None:
        self.amount = amount
        self._last_tick = time.monotonic()

    def tick(self) -> None:
        now = time.monotonic()
        self.amount = max(0.0, self.amount - (now - self._last_tick))
        self._last_tick = now

    def resync(self) -> None:
        """
        Reset the tick reference point to now. Call after any stretch where
        tick() wasn't invoked (a shop-choice break) before ticking resumes
        -- otherwise the next tick() computes its
        delta against a stale timestamp from before the pause, charging the
        *entire* paused stretch as elapsed time in one lump the instant
        play resumes.
        """
        self._last_tick = time.monotonic()

    def add(self, amount: float) -> None:
        self.amount += amount

    def spend(self, amount: float) -> None:
        self.amount = max(0.0, self.amount - amount)

    @property
    def depleted(self) -> bool:
        return self.amount <= 0.0

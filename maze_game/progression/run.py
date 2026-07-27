"""
run.py
------
The labyrinth progression mode: a sequence of LABYRINTH_TOTAL_MAZES mazes,
gradually increasing in size. Time is one persistent resource (TimeResource)
carried across the whole run rather than a per-maze budget -- pellets add
to it, enemies/the boss subtract from it, clearing a maze fast enough adds
a small bonus, and running out ends the whole run back at maze 1
(rogue-like: no retry in place, matching the project's existing "full
reset, not a retry" framing). Every LABYRINTH_GROUP_SIZE-th maze pauses
for a perk-card choice instead of a bare "continue" prompt; every
BOSS_INTERVAL-th maze replaces the goal with a boss fight.

Deliberately independent of pygame -- pure state machine, testable without a
display, same pattern as Game/history.py.
"""

import time

from maze_game.constants import (
    LABYRINTH_TOTAL_MAZES, LABYRINTH_GROUP_SIZE, LABYRINTH_START_TIME,
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
    BOSS_BASE_HP, BOSS_HP_STEP, BOSS_INTERVAL, ENEMY_UNLOCK_MAZE,
    SPEED_BONUS_TIME, SPEED_BONUS_SECONDS_PER_CELL,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, shortest_path
from maze_game.player import slide_path
from maze_game.progression.entities import resolve_contacts
from maze_game.progression.entities.hazards import spawn_pellets, spawn_enemies
from maze_game.progression.entities.boss import Boss, is_boss_maze
from maze_game.progression.perks import Build, Perk, offer_perks

START_POS: tuple[int, int] = (1, 1)


def dimensions_for_maze(maze_index: int) -> tuple[int, int]:
    """
    maze_index is 1-based (1..LABYRINTH_TOTAL_MAZES). Square mazes: starts
    at MIN_DIMENSION, +DIMENSION_STEP per completed group of
    LABYRINTH_GROUP_SIZE, capped at MAX_DIMENSION.
    """
    group_index = (maze_index - 1) // LABYRINTH_GROUP_SIZE  # 0-based
    size = min(MIN_DIMENSION + group_index * DIMENSION_STEP, MAX_DIMENSION)
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
        tick() wasn't invoked (e.g. a perk-choice break) before ticking
        resumes -- otherwise the next tick() computes its delta against a
        stale timestamp from before the pause, charging the *entire* paused
        stretch as elapsed time in one lump the instant play resumes.
        """
        self._last_tick = time.monotonic()

    def add(self, amount: float) -> None:
        self.amount += amount

    def spend(self, amount: float) -> None:
        self.amount = max(0.0, self.amount - amount)

    @property
    def depleted(self) -> bool:
        return self.amount <= 0.0


class LabyrinthRun:
    """
    Owns the full progression state machine: current maze, the persistent
    time resource, this maze's pellets/enemies/boss, the player's perk
    build, group breaks, and pass/fail.
    """

    def __init__(self) -> None:
        self.maze_index = 1
        self.on_break = False
        self.failed = False
        self.completed_run = False
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.build = Build()
        self.perk_choices: list[Perk] | None = None
        self.perk_cursor = 0
        self._begin_maze()

    # ── Public API ────────────────────────────────────────────────────────

    def update(self) -> None:
        """Advance the timer and check win/timeout. Call once per frame."""
        if self.on_break or self.failed or self.completed_run or self.finished:
            return
        self.time.tick()
        if self.time.depleted:
            self.failed = True
            return
        if self._maze_cleared():
            if time.monotonic() - self._maze_started_at <= self._par_seconds:
                self.time.add(SPEED_BONUS_TIME)
            self.finished = True
            self._advance()

    def move(self, direction: tuple[int, int], junction_stop_count: int | None = 1) -> None:
        """
        junction_stop_count follows player.slide_path(): 1 (default) is a
        normal single-press move; None is the "hold spacebar" combo (run to
        the next wall, ignoring intersections); N>1 is the "hold a number
        key" combo (blow through the first N-1 intersections, stop at the Nth).
        """
        if self.on_break or self.failed or self.completed_run or self.finished:
            return
        path = slide_path(self.grid, self.player, direction, junction_stop_count=junction_stop_count)
        if not path:
            return
        if self.boss is not None:
            self.boss.advance(self.player, self.grid)
        self.player = path[-1]
        resolve_contacts(self, path)

    def move_perk_cursor(self, delta: int) -> None:
        """Move the keyboard-selected perk card left/right (wraps); confirm with choose_perk(perk_cursor)."""
        if not self.on_break or self.perk_choices is None:
            return
        self.perk_cursor = (self.perk_cursor + delta) % len(self.perk_choices)

    def choose_perk(self, index: int) -> None:
        """Apply the chosen perk card and immediately start the next maze -- the pick IS the resume action."""
        if not self.on_break or self.perk_choices is None:
            return
        self.build.acquire(self.perk_choices[index])
        self.on_break = False
        self.perk_choices = None
        self.time.resync()  # the break paused the clock; don't charge its duration on the next tick()
        self.maze_index += 1
        self._begin_maze()

    def restart(self) -> None:
        """Start the whole run over from maze 1 (e.g. after running out of time)."""
        self.maze_index = 1
        self.on_break = False
        self.failed = False
        self.completed_run = False
        self.perk_choices = None
        self.perk_cursor = 0
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.build = Build()
        self._begin_maze()

    @property
    def group_number(self) -> int:
        """1-based group number for the current maze."""
        return (self.maze_index - 1) // LABYRINTH_GROUP_SIZE + 1

    @property
    def total_groups(self) -> int:
        return -(-LABYRINTH_TOTAL_MAZES // LABYRINTH_GROUP_SIZE)  # ceil division

    # ── Private helpers ───────────────────────────────────────────────────

    def _maze_cleared(self) -> bool:
        return self.boss.defeated if self.boss is not None else self.player == self.goal

    def _begin_maze(self) -> None:
        cols, rows = dimensions_for_maze(self.maze_index)
        self.cols, self.rows = cols, rows
        self.grid = generate_maze(cols, rows)
        self.player = START_POS

        if is_boss_maze(self.maze_index):
            self.goal = None
            boss_pos = farthest_reachable_cell(self.grid, START_POS)
            encounter_index = self.maze_index // BOSS_INTERVAL - 1
            self.boss = Boss(boss_pos, hp=BOSS_BASE_HP + BOSS_HP_STEP * encounter_index)
            self.pellets = []
            self.enemies = []
        else:
            self.goal = farthest_reachable_cell(self.grid, START_POS)
            self.boss = None
            exclude = {START_POS, self.goal}
            self.pellets = spawn_pellets(self.grid, exclude, self.build.pellet_frequency_multiplier)
            exclude = exclude | {p.pos for p in self.pellets}
            self.enemies = spawn_enemies(self.grid, exclude) if self.maze_index >= ENEMY_UNLOCK_MAZE else []

        target = self.boss.pos if self.boss is not None else self.goal
        self._par_seconds = SPEED_BONUS_SECONDS_PER_CELL * len(shortest_path(self.grid, START_POS, target))
        self._maze_started_at = time.monotonic()
        self.finished = False

    def _advance(self) -> None:
        if self.maze_index >= LABYRINTH_TOTAL_MAZES:
            self.completed_run = True
        elif self.maze_index % LABYRINTH_GROUP_SIZE == 0:
            self.on_break = True
            self.perk_choices = offer_perks()
            self.perk_cursor = 0
        else:
            self.maze_index += 1
            self._begin_maze()  # seamless -- no pause within a group

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
for a shop-card choice (a passive perk or an active item) instead of a
bare "continue" prompt; every BOSS_INTERVAL-th maze replaces the goal with
a boss fight.

Deliberately independent of pygame -- pure state machine, testable without a
display, same pattern as Game/history.py.
"""

import time

from maze_game.constants import (
    LABYRINTH_TOTAL_MAZES, LABYRINTH_GROUP_SIZE, LABYRINTH_START_TIME,
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
    BOSS_BASE_HP, BOSS_HP_STEP, BOSS_INTERVAL, ENEMY_UNLOCK_MAZE,
    SPEED_BONUS_TIME, SPEED_BONUS_SECONDS_PER_CELL, STOPWATCH_PAUSE_SECONDS,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, shortest_path
from maze_game.player import slide_path
from maze_game.progression.entities import resolve_contacts
from maze_game.progression.entities.hazards import spawn_pellets, spawn_enemies
from maze_game.progression.entities.boss import Boss, is_boss_maze
from maze_game.progression.shop import offer_shop_cards
from maze_game.progression.shop.perks import Build, Perk
from maze_game.progression.shop.items import Loadout

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


DIRECTIONS = [(0, -1), (0, 1), (-1, 0), (1, 0)]


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
        tick() wasn't invoked (a shop-choice break, or a Stopwatch pause)
        before ticking resumes -- otherwise the next tick() computes its
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


class LabyrinthRun:
    """
    Owns the full progression state machine: current maze, the persistent
    time resource, this maze's pellets/enemies/boss, the player's perk
    build and item loadout, group breaks, and pass/fail.
    """

    def __init__(self) -> None:
        self.maze_index = 1
        self.on_break = False
        self.failed = False
        self.completed_run = False
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.build = Build()
        self.loadout = Loadout()
        self.shop_choices: list | None = None
        self.shop_cursor = 0
        self.stopwatch_until: float | None = None
        self.last_squeak_at: float | None = None
        self._begin_maze()

    # ── Public API ────────────────────────────────────────────────────────

    def update(self) -> None:
        """Advance the timer and check win/timeout. Call once per frame."""
        if self.stopwatch_until is not None:
            if time.monotonic() >= self.stopwatch_until:
                self.stopwatch_until = None
                self.time.resync()  # same fix as the shop-break pause -- don't charge the pause itself
            return  # fully paused either way: no tick, no movement, no win-check
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

    def move(self, direction: tuple[int, int], junction_stop_count: int | None = 1, use_wall_breaker: bool = False) -> None:
        """
        junction_stop_count follows player.slide_path(): 1 (default) is a
        normal single-press move; None is the "hold spacebar" combo (run to
        the next wall, ignoring intersections); N>1 blows through the first
        N-1 intersections reached. use_wall_breaker forces None (Wall
        Breaker always behaves "as if holding spacebar") and additionally
        lets the slide break through one non-border wall if a charge is
        available.
        """
        if self._is_gated():
            return
        break_wall = self._try_break_wall if use_wall_breaker else None
        path = slide_path(
            self.grid, self.player, direction,
            junction_stop_count=None if use_wall_breaker else junction_stop_count,
            break_wall=break_wall,
        )
        if not path:
            return
        if self.boss is not None:
            self.boss.advance(self.player, self.grid)
        self.player = path[-1]
        resolve_contacts(self, path)

    def activate_laser(self) -> None:
        """Fire in all 4 directions from the player's position, destroying any enemy hit (1 charge)."""
        if self._is_gated() or not self.loadout.consume_charge("laser"):
            return
        hit_cells: set[tuple[int, int]] = set()
        for direction in DIRECTIONS:
            hit_cells.update(slide_path(self.grid, self.player, direction, junction_stop_count=None))
        self.enemies = [e for e in self.enemies if e.pos not in hit_cells]

    def activate_stopwatch(self) -> None:
        """Pause the clock and block movement for STOPWATCH_PAUSE_SECONDS (1 charge)."""
        if self._is_gated() or not self.loadout.consume_charge("stopwatch"):
            return
        self.stopwatch_until = time.monotonic() + STOPWATCH_PAUSE_SECONDS

    def activate_squeaky_toy(self) -> None:
        """Does nothing except leave a timestamp the renderer can flash a "Squeak!" acknowledgment from."""
        if self._is_gated():
            return
        self.last_squeak_at = time.monotonic()

    def move_shop_cursor(self, delta: int) -> None:
        """Move the keyboard-selected shop card left/right (wraps); confirm with choose_shop_card(shop_cursor)."""
        if not self.on_break or self.shop_choices is None:
            return
        self.shop_cursor = (self.shop_cursor + delta) % len(self.shop_choices)

    def choose_shop_card(self, index: int) -> None:
        """Apply the chosen card (a perk or an item) and immediately start the next maze -- the pick IS the resume action."""
        if not self.on_break or self.shop_choices is None:
            return
        card = self.shop_choices[index]
        if isinstance(card, Perk):
            self.build.acquire(card)
        else:
            self.loadout.acquire(card)
        self.on_break = False
        self.shop_choices = None
        self.time.resync()  # the break paused the clock; don't charge its duration on the next tick()
        self.maze_index += 1
        self._begin_maze()

    def restart(self) -> None:
        """Start the whole run over from maze 1 (e.g. after running out of time)."""
        self.maze_index = 1
        self.on_break = False
        self.failed = False
        self.completed_run = False
        self.shop_choices = None
        self.shop_cursor = 0
        self.stopwatch_until = None
        self.last_squeak_at = None
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.build = Build()
        self.loadout = Loadout()
        self._begin_maze()

    @property
    def group_number(self) -> int:
        """1-based group number for the current maze."""
        return (self.maze_index - 1) // LABYRINTH_GROUP_SIZE + 1

    @property
    def total_groups(self) -> int:
        return -(-LABYRINTH_TOTAL_MAZES // LABYRINTH_GROUP_SIZE)  # ceil division

    # ── Private helpers ───────────────────────────────────────────────────

    def _is_gated(self) -> bool:
        return bool(
            self.on_break or self.failed or self.completed_run or self.finished
            or self.stopwatch_until is not None
        )

    def _maze_cleared(self) -> bool:
        return self.boss.defeated if self.boss is not None else self.player == self.goal

    def _try_break_wall(self, nx: int, ny: int) -> bool:
        if nx in (0, self.cols - 1) or ny in (0, self.rows - 1):
            return False  # never break the border
        if not self.loadout.consume_charge("wall_breaker"):
            return False
        self.grid[ny][nx] = 0
        return True

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
            self.shop_choices = offer_shop_cards()
            self.shop_cursor = 0
        else:
            self.maze_index += 1
            self._begin_maze()  # seamless -- no pause within a group

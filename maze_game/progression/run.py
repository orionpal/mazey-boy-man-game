"""
run.py
------
The labyrinth progression mode: a sequence of LABYRINTH_TOTAL_MAZES mazes,
gradually increasing in size. Time is one persistent resource (TimeResource)
carried across the whole run rather than a per-maze budget -- pellets add
to it, enemies/the boss subtract from it, clearing a maze fast enough adds
a small bonus, and running out ends the whole run back at maze 1
(rogue-like: no retry in place, matching the project's existing "full
reset, not a retry" framing).

Pacing: every LABYRINTH_GROUP_SIZE-th maze pauses for a "power-up" break (a
passive perk or an active item, drawn from shop/); every AUGMENT_INTERVAL-th
maze pauses for a "modifier" break (a maze augment choice, drawn from
augments/); every BOSS_INTERVAL-th maze -- and always the
LABYRINTH_TOTAL_MAZES-th (final) maze -- replaces the goal with a boss
fight. When a maze index triggers more than one of these, the break screens
stack sequentially (e.g. maze 30: power-up screen, then modifier screen,
then that maze begins, as a boss maze) rather than one replacing another --
see _breaks_due_after()/_resume_after_break().

Deliberately independent of pygame -- pure state machine, testable without a
display, same pattern as Game/history.py.
"""

import random
import time
from dataclasses import dataclass
from pathlib import Path

from maze_game.constants import (
    LABYRINTH_TOTAL_MAZES, LABYRINTH_GROUP_SIZE, LABYRINTH_START_TIME,
    MIN_DIMENSION, MAX_DIMENSION, DIMENSION_STEP,
    BOSS_BASE_HP, BOSS_HP_STEP, BOSS_INTERVAL, AUGMENT_INTERVAL, ENEMY_UNLOCK_MAZE,
    SPEED_BONUS_TIME, SPEED_BONUS_SECONDS_PER_CELL, STOPWATCH_PAUSE_SECONDS,
    POPUP_DURATION_SECONDS, C_SPEED_BONUS,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, shortest_path
from maze_game.player import slide_path
from maze_game.progression.entities import resolve_contacts
from maze_game.progression.entities.hazards import (
    spawn_pellets, spawn_enemies, enemy_density_ramp,
    spawn_gold_pellets, load_gold_total, DEFAULT_GOLD_PATH,
)
from maze_game.progression.entities.boss import Boss, is_boss_maze, boss_encounter_index
from maze_game.progression.shop import offer_shop_cards
from maze_game.progression.shop.perks import Build, Perk
from maze_game.progression.shop.items import Loadout
from maze_game.progression.augments import AugmentBuild, run_pipeline, offer_augment_cards

START_POS: tuple[int, int] = (1, 1)


@dataclass
class Popup:
    """A brief floating "+Xs"/"-Xs" label wherever a pellet, enemy, or speed bonus changes the time resource."""

    pos: tuple[int, int]
    text: str
    color: tuple[int, int, int]
    created_at: float

# Breaks should always coincide with (or be subsumed by) the group cadence,
# so a modifier or boss maze is never a total surprise with zero preceding
# screen -- pacing-predictability invariants, not strictly required for
# correctness (an unaligned interval would just show fewer break screens,
# not crash), but worth failing loudly on if retuned inconsistently.
assert AUGMENT_INTERVAL % LABYRINTH_GROUP_SIZE == 0
assert BOSS_INTERVAL % AUGMENT_INTERVAL == 0


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

    def __init__(self, seed: int | None = None, gold_path: Path | None = None) -> None:
        self.seed = seed if seed is not None else _random_seed()
        self.rng = random.Random(self.seed)
        self.maze_index = 1
        self.break_kind: str | None = None
        self._pending_breaks: list[str] = []
        self.failed = False
        self.completed_run = False
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.build = Build()
        self.loadout = Loadout()
        self.augment_build = AugmentBuild()
        self.teleporters: list = []
        self._teleport_map: dict[tuple[int, int], tuple[int, int]] = {}
        self.shop_choices: list | None = None
        self.augment_choices: list | None = None
        self.break_cursor = 0
        self.stopwatch_until: float | None = None
        self.last_squeak_at: float | None = None
        self.popups: list[Popup] = []
        self.events: list[str] = []
        # Gold is a persistent meta-currency, unlike time -- loaded once here
        # and never reset by restart() (see restart()'s docstring/comment).
        # DEFAULT_GOLD_PATH is looked up here (not as the parameter's default
        # value) so tests can monkeypatch it and isolate every LabyrinthRun()
        # construction from the real on-disk gold.json, same as conftest.py
        # does for it.
        self.gold_path = gold_path if gold_path is not None else DEFAULT_GOLD_PATH
        self.gold = load_gold_total(self.gold_path)
        self._begin_maze()

    # ── Public API ────────────────────────────────────────────────────────

    def add_popup(self, pos: tuple[int, int], text: str, color: tuple[int, int, int]) -> None:
        """Queue a brief floating label at `pos` (a grid cell) -- see Popup/renderer._draw_popups."""
        self.popups.append(Popup(pos, text, color, time.monotonic()))

    def update(self) -> None:
        """Advance the timer and check win/timeout. Call once per frame."""
        now = time.monotonic()
        self.popups = [p for p in self.popups if now - p.created_at < POPUP_DURATION_SECONDS]
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
            self.events.append("fail")
            return
        if self._maze_cleared():
            if time.monotonic() - self._maze_started_at <= self._par_seconds:
                self.time.add(SPEED_BONUS_TIME)
                self.add_popup(self.player, f"+{SPEED_BONUS_TIME:.1f}s", C_SPEED_BONUS)
                self.events.append("speed_bonus")
            self.finished = True
            self.events.append("maze_complete")
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
        teleport = (lambda nx, ny: self._teleport_map.get((nx, ny))) if self._teleport_map else None
        path = slide_path(
            self.grid, self.player, direction,
            junction_stop_count=None if use_wall_breaker else junction_stop_count,
            break_wall=break_wall,
            teleport=teleport,
        )
        if not path:
            return
        # A teleport fired if the second-to-last cell entered maps (via
        # _teleport_map) to the last one -- slide_path() always appends the
        # entrance immediately followed by the exit and stops right there
        # (see player.py), so this pair is the exact, sufficient signature.
        teleported = len(path) >= 2 and self._teleport_map.get(path[-2]) == path[-1]
        self.events.append("teleport" if teleported else "move")
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
        self.events.append("laser")

    def activate_stopwatch(self) -> None:
        """Pause the clock and block movement for STOPWATCH_PAUSE_SECONDS (1 charge)."""
        if self._is_gated() or not self.loadout.consume_charge("stopwatch"):
            return
        self.stopwatch_until = time.monotonic() + STOPWATCH_PAUSE_SECONDS
        self.events.append("stopwatch")

    def activate_squeaky_toy(self) -> None:
        """Does nothing except leave a timestamp the renderer can flash a "Squeak!" acknowledgment from."""
        if self._is_gated():
            return
        self.last_squeak_at = time.monotonic()
        self.events.append("squeak")

    def move_break_cursor(self, delta: int) -> None:
        """Move the keyboard-selected break card left/right (wraps), for whichever break (shop or augment) is currently active."""
        choices = self._current_break_choices()
        if choices is None:
            return
        self.break_cursor = (self.break_cursor + delta) % len(choices)

    def choose_break_card(self, index: int) -> None:
        """Single entry point for confirming a break-card pick -- dispatches to whichever break is currently active."""
        if self.break_kind == "shop":
            self.choose_shop_card(index)
        elif self.break_kind == "augment":
            self.choose_augment_card(index)

    def choose_shop_card(self, index: int) -> None:
        """Apply the chosen card (a perk or an item), then resume (the next queued break, or the next maze)."""
        if self.break_kind != "shop" or self.shop_choices is None:
            return
        card = self.shop_choices[index]
        if isinstance(card, Perk):
            self.build.acquire(card)
        else:
            self.loadout.acquire(card)
        self.shop_choices = None
        self.events.append("card_select")
        self._resume_after_break()

    def choose_augment_card(self, index: int) -> None:
        """Apply the chosen maze modifier (augment), then resume (the next queued break, or the next maze)."""
        if self.break_kind != "augment" or self.augment_choices is None:
            return
        self.augment_build.acquire(self.augment_choices[index])
        self.augment_choices = None
        self.events.append("card_select")
        self._resume_after_break()

    def restart(self, same_seed: bool = False) -> None:
        """
        Start the whole run over from maze 1 (e.g. after running out of
        time). Picks a fresh seed by default -- a genuinely new run, not a
        replay -- unless `same_seed` is requested (e.g. retrying the exact
        same layout after a rough death).

        Deliberately does not touch self.gold/self.gold_path -- gold is a
        persistent meta-currency that survives death, unlike the time
        resource, which fully resets every run (see docs/progression.md).
        """
        self.seed = self.seed if same_seed else _random_seed()
        self.rng = random.Random(self.seed)
        self.maze_index = 1
        self.break_kind = None
        self._pending_breaks = []
        self.failed = False
        self.completed_run = False
        self.shop_choices = None
        self.augment_choices = None
        self.break_cursor = 0
        self.stopwatch_until = None
        self.last_squeak_at = None
        self.popups = []
        self.events = []
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.build = Build()
        self.loadout = Loadout()
        self.augment_build = AugmentBuild()
        self.teleporters = []
        self._teleport_map = {}
        self._begin_maze()

    @property
    def on_break(self) -> bool:
        return self.break_kind is not None

    @property
    def group_number(self) -> int:
        """1-based group number for the current maze."""
        return (self.maze_index - 1) // LABYRINTH_GROUP_SIZE + 1

    @property
    def total_groups(self) -> int:
        return -(-LABYRINTH_TOTAL_MAZES // LABYRINTH_GROUP_SIZE)  # ceil division

    # ── Private helpers ───────────────────────────────────────────────────

    def _current_break_choices(self) -> list | None:
        if self.break_kind == "shop":
            return self.shop_choices
        if self.break_kind == "augment":
            return self.augment_choices
        return None

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
        self.events.append("wall_break")
        return True

    def _begin_maze(self) -> None:
        cols, rows = dimensions_for_maze(self.maze_index)
        self.cols, self.rows = cols, rows
        self.grid = generate_maze(cols, rows, rng=self.rng)
        self.player = START_POS

        # Augments (e.g. teleporting squares) are a post-process over the
        # freshly-generated grid -- generate_maze() itself stays untouched.
        # Applies to boss mazes too: `ctx.goal` doubles as "the boss's
        # placement" there, same as the pre-augment target selection did.
        default_target = farthest_reachable_cell(self.grid, START_POS)
        ctx = run_pipeline(self.grid, cols, rows, START_POS, default_target, self.augment_build, self.rng)
        self.grid = ctx.grid
        self.teleporters = ctx.extra.get("teleporters", [])
        self._teleport_map = {}
        for pair in self.teleporters:
            self._teleport_map[pair.a] = pair.b
            self._teleport_map[pair.b] = pair.a

        if is_boss_maze(self.maze_index):
            self.goal = None
            boss_pos = ctx.goal
            encounter_index = boss_encounter_index(self.maze_index)
            self.boss = Boss(boss_pos, hp=BOSS_BASE_HP + BOSS_HP_STEP * encounter_index)
            self.pellets = []
            self.gold_pellets = []
            self.enemies = []
        else:
            self.goal = ctx.goal
            self.boss = None
            exclude = {START_POS, self.goal} | ctx.reserved
            self.pellets = spawn_pellets(self.grid, exclude, self.build.pellet_frequency_multiplier, rng=self.rng)
            exclude = exclude | {p.pos for p in self.pellets}
            self.gold_pellets = spawn_gold_pellets(self.grid, exclude, rng=self.rng)
            exclude = exclude | {p.pos for p in self.gold_pellets}
            if self.maze_index >= ENEMY_UNLOCK_MAZE:
                self.enemies = spawn_enemies(
                    self.grid, exclude, density_multiplier=enemy_density_ramp(self.maze_index), rng=self.rng,
                )
            else:
                self.enemies = []

        target = self.boss.pos if self.boss is not None else self.goal
        self._par_seconds = SPEED_BONUS_SECONDS_PER_CELL * len(
            shortest_path(self.grid, START_POS, target, extra_edges=self._teleport_map)
        )
        self._maze_started_at = time.monotonic()
        self.finished = False

    def _advance(self) -> None:
        if self.maze_index >= LABYRINTH_TOTAL_MAZES:
            self.completed_run = True
            return
        self._pending_breaks = _breaks_due_after(self.maze_index)
        self._resume_after_break()

    def _resume_after_break(self) -> None:
        """
        Pop the next queued break (if any) and show it; once the queue is
        empty, actually advance to the next maze. This is what makes
        multiple breaks on the same maze index stack sequentially (e.g.
        maze 30: power-up screen, then modifier screen, then maze 30
        begins) instead of one replacing another -- and, critically, only
        resyncs the clock *once* the whole queue is drained, not after each
        individual break, avoiding the exact TimeResource staleness bug
        docs/progression.md already documents once (a stale tick reference
        point charging the entire paused stretch in one lump the instant
        play resumes).
        """
        if self._pending_breaks:
            self.break_kind = self._pending_breaks.pop(0)
            self.break_cursor = 0
            if self.break_kind == "shop":
                self.shop_choices = offer_shop_cards(rng=self.rng)
            else:  # "augment"
                self.augment_choices = offer_augment_cards(self.augment_build, rng=self.rng)
            return
        self.break_kind = None
        self.time.resync()  # the break(s) paused the clock; don't charge their duration on the next tick()
        self.maze_index += 1
        self._begin_maze()  # seamless when no break was due -- no pause within a group

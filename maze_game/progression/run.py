"""
run.py
------
The labyrinth progression mode: a sequence of LABYRINTH_TOTAL_MAZES mazes,
gradually increasing in size. Time is one persistent resource (TimeResource)
carried across the whole run rather than a per-maze budget -- pellets add
to it, hazards subtract from it, clearing a maze fast enough adds a small
bonus, and running out ends the whole run back at maze 1 (rogue-like: no
retry in place, matching the project's existing "full reset, not a retry"
framing).

Pacing: every LABYRINTH_GROUP_SIZE-th maze pauses for a "power-up" break (a
passive perk, drawn from shop/); every AUGMENT_INTERVAL-th
maze pauses for a "modifier" break (a maze augment choice, drawn from
augments/); every MILESTONE_INTERVAL-th maze -- and always the
LABYRINTH_TOTAL_MAZES-th (final) maze -- gets a one-off dimension spike
(see dimensions_for_maze()), a noticeably bigger maze than the normal ramp
would give it, reverting to the regular ramp on the very next maze. When a
maze index triggers more than one of these, the break screens stack
sequentially (e.g. maze 30: power-up screen, then modifier screen, then
that maze begins, as a milestone maze) rather than one replacing another --
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
    MILESTONE_INTERVAL, MILESTONE_DIMENSION_BOOST, MILESTONE_MAX_DIMENSION,
    AUGMENT_INTERVAL, HAZARD_UNLOCK_MAZE,
    SPEED_BONUS_TIME, SPEED_BONUS_SECONDS_PER_CELL,
    POPUP_DURATION_SECONDS, C_SPEED_BONUS, C_GOLD,
    ZIP_ANIMATION_DURATION_SECONDS,
    ROTATE_INTERVAL_BASE_SECONDS, ROTATE_INTERVAL_STEP_SECONDS, ROTATE_INTERVAL_MIN_SECONDS,
    ROTATE_WARNING_LEAD_SECONDS,
)
from maze_game.maze import generate_maze, farthest_reachable_cell, shortest_path
from maze_game.player import slide_path
from maze_game.progression.entities import resolve_contacts
from maze_game.progression.entities.hazards import (
    spawn_pellets, spawn_hazards, hazard_density_ramp,
    spawn_gold_pellets, load_gold_total, save_gold_total, DEFAULT_GOLD_PATH,
)
from maze_game.progression.shop import offer_shop_cards
from maze_game.progression.augments import AugmentBuild, run_pipeline, offer_augment_cards
from maze_game.progression.augments.gating.doors import Key, DoorKeyPair
from maze_game.progression.augments.gating.teleporters import TeleporterPair
from maze_game.progression.augments.runtime.rotation import rotate_cell_cw, rotate_grid_cw
from maze_game.progression.augments.runtime.fog import visible_cells_from
from maze_game.progression.meta import MetaProgress, DEFAULT_META_UPGRADES_PATH

ROTATING_MAZE_ID = "rotating_maze"
FOG_OF_WAR_ID = "fog_of_war"

START_POS: tuple[int, int] = (1, 1)


@dataclass
class Popup:
    """A brief floating "+Xs"/"-Xs" label wherever a pellet, hazard, or speed bonus changes the time resource."""

    pos: tuple[int, int]
    text: str
    color: tuple[int, int, int]
    created_at: float


@dataclass
class TeleportAnimation:
    """
    A short visual "zip" from one cell to the next, purely presentational
    (see ZIP_ANIMATION_DURATION_SECONDS) -- renderer._draw_player()
    interpolates the on-screen position between from_cell/to_cell over the
    animation window; LabyrinthRun.player itself already updated instantly
    in move(), unaffected by this.
    """

    from_cell: tuple[int, int]
    to_cell: tuple[int, int]
    started_at: float

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


class RotationTimer:
    """
    Counts down to the rotating maze augment's next rotation. Deliberately
    mirrors TimeResource's tick()/resync() shape exactly, not a fresh
    design -- TimeResource needed resync() specifically to avoid charging
    an entire break's duration in one lump the instant ticking resumes
    (see TimeResource.resync()'s docstring); reusing the identical shape
    avoids reintroducing that same staleness bug in a second,
    differently-coded timer.
    """

    def __init__(self, interval: float) -> None:
        self.remaining = interval
        self._last_tick = time.monotonic()

    def tick(self) -> None:
        now = time.monotonic()
        self.remaining -= now - self._last_tick
        self._last_tick = now

    def resync(self) -> None:
        self._last_tick = time.monotonic()


def _rotation_interval_for_level(level: int) -> float:
    """Higher levels rotate faster, down to a floor so it never becomes literally unplayable -- see ROTATE_* constants."""
    return max(
        ROTATE_INTERVAL_MIN_SECONDS,
        ROTATE_INTERVAL_BASE_SECONDS + ROTATE_INTERVAL_STEP_SECONDS * (level - 1),
    )


class LabyrinthRun:
    """
    Owns the full progression state machine: current maze, the persistent
    time resource, this maze's pellets/hazards, the player's perk build,
    group breaks, and pass/fail.
    """

    def __init__(
        self,
        seed: int | None = None,
        gold_path: Path | None = None,
        meta_upgrades_path: Path | None = None,
    ) -> None:
        self.seed = seed if seed is not None else _random_seed()
        self.rng = random.Random(self.seed)
        self.maze_index = 1
        self.break_kind: str | None = None
        self._pending_breaks: list[str] = []
        self.failed = False
        self.completed_run = False
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.augment_build = AugmentBuild()
        self.teleporters: list = []
        self._teleport_map: dict[tuple[int, int], tuple[int, int]] = {}
        self.doors: list = []
        self.keys: list = []
        self._locked_doors: set[tuple[int, int]] = set()
        self.shop_choices: list | None = None
        self.augment_choices: list | None = None
        self.break_cursor = 0
        self.popups: list[Popup] = []
        self.teleport_animation: TeleportAnimation | None = None
        self.rotation_timer = RotationTimer(ROTATE_INTERVAL_BASE_SECONDS)
        self.events: list[str] = []
        # Gold is a persistent meta-currency, unlike time -- loaded once here
        # and never reset by restart() (see restart()'s docstring/comment).
        # DEFAULT_GOLD_PATH/DEFAULT_META_UPGRADES_PATH are looked up here
        # (not as the parameters' default values) so tests can monkeypatch
        # them and isolate every LabyrinthRun() construction from the real
        # on-disk files, same as conftest.py does for it.
        self.gold_path = gold_path if gold_path is not None else DEFAULT_GOLD_PATH
        self.gold = load_gold_total(self.gold_path)
        meta_upgrades_path = meta_upgrades_path if meta_upgrades_path is not None else DEFAULT_META_UPGRADES_PATH
        # Owned meta upgrades (purchased in the Base, between runs -- see
        # progression/meta/) seed the starting Build. Loaded from disk once
        # here, not reloaded by restart() -- meta progress can't change
        # mid-run, only the Base (which always runs before a new one
        # starts) purchases -- but restart() still reseeds self.build from
        # this same self.meta_progress, so owned upgrades keep applying to
        # every run, not just the very first one.
        self.meta_progress = MetaProgress(self.gold_path, meta_upgrades_path)
        self.build = self.meta_progress.seed_build()
        self._begin_maze()

    # ── Public API ────────────────────────────────────────────────────────

    def add_popup(self, pos: tuple[int, int], text: str, color: tuple[int, int, int]) -> None:
        """Queue a brief floating label at `pos` (a grid cell) -- see Popup/renderer._draw_popups."""
        self.popups.append(Popup(pos, text, color, time.monotonic()))

    def visible_and_discovered_cells(self) -> set[tuple[int, int]] | None:
        """
        Which cells renderer.py should draw -- `None` means "no restriction,
        draw everything" (fog of war isn't active for this build).

        PERMANENT MEMORY is the current default: self.discovered_cells only
        ever grows (accumulated in move()/_begin_maze()), so once a cell has
        been seen it stays revealed for the rest of the maze. To switch to a
        narrower default later (e.g. the player has to remember on their
        own, unless they've picked up some future "memory" item), change
        the return line below to a freshly-computed
        visible_cells_from(self.grid, self.player) instead of the
        accumulator -- everything else (the accumulation itself, and
        renderer.py's filtering against whatever this returns) stays
        unchanged.
        """
        if self.augment_build.level_of(FOG_OF_WAR_ID) <= 0:
            return None
        return self.discovered_cells

    def update(self) -> None:
        """Advance the timer and check win/timeout. Call once per frame."""
        now = time.monotonic()
        self.popups = [p for p in self.popups if now - p.created_at < POPUP_DURATION_SECONDS]
        if self.teleport_animation is not None and now - self.teleport_animation.started_at >= ZIP_ANIMATION_DURATION_SECONDS:
            self.teleport_animation = None
        if self.on_break or self.failed or self.completed_run or self.finished:
            return
        self.time.tick()
        rotation_level = self.augment_build.level_of(ROTATING_MAZE_ID)
        if rotation_level > 0:
            self.rotation_timer.tick()
            if self.rotation_timer.remaining <= 0:
                self._rotate_maze()
                self.rotation_timer.remaining = _rotation_interval_for_level(rotation_level)
        if self.time.depleted:
            self.failed = True
            self.events.append("fail")
            return
        if self._maze_cleared():
            if time.monotonic() - self._maze_started_at <= self._par_seconds:
                self.time.add(SPEED_BONUS_TIME)
                self.add_popup(self.player, f"+{SPEED_BONUS_TIME:.1f}s", C_SPEED_BONUS)
                self.events.append("speed_bonus")
                if self.build.gold_rush_bonus > 0:
                    self.gold += self.build.gold_rush_bonus
                    save_gold_total(self.gold, self.gold_path)
                    self.add_popup(self.player, f"+{self.build.gold_rush_bonus}g", C_GOLD)
                    self.events.append("gold")
            self.finished = True
            self.events.append("maze_complete")
            self._advance()

    def move(self, direction: tuple[int, int], junction_stop_count: int | None = 1) -> None:
        """
        junction_stop_count follows player.slide_path(): 1 (default) is a
        normal single-press move; None is the "hold spacebar" combo (run to
        the next wall, ignoring intersections); N>1 blows through the first
        N-1 intersections reached.
        """
        if self._is_gated():
            return
        teleport = (lambda nx, ny: self._teleport_map.get((nx, ny))) if self._teleport_map else None
        door_locked = (lambda nx, ny: (nx, ny) in self._locked_doors) if self._locked_doors else None
        path = slide_path(
            self.grid, self.player, direction,
            junction_stop_count=junction_stop_count,
            teleport=teleport,
            door_locked=door_locked,
        )
        if not path:
            return
        # A teleport fired if the second-to-last cell entered maps (via
        # _teleport_map) to the last one -- slide_path() always appends the
        # entrance immediately followed by the exit and stops right there
        # (see player.py), so this pair is the exact, sufficient signature.
        teleported = len(path) >= 2 and self._teleport_map.get(path[-2]) == path[-1]
        self.events.append("teleport" if teleported else "move")
        if teleported:
            self.teleport_animation = TeleportAnimation(path[-2], path[-1], time.monotonic())
        self.player = path[-1]
        if self.augment_build.level_of(FOG_OF_WAR_ID) > 0:
            self.discovered_cells |= visible_cells_from(self.grid, self.player)
        resolve_contacts(self, path)

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
        """Apply the chosen perk, then resume (the next queued break, or the next maze)."""
        if self.break_kind != "shop" or self.shop_choices is None:
            return
        self.build.acquire(self.shop_choices[index])
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
        self.popups = []
        self.teleport_animation = None
        self.rotation_timer = RotationTimer(ROTATE_INTERVAL_BASE_SECONDS)
        self.events = []
        self.time = TimeResource(LABYRINTH_START_TIME)
        self.build = self.meta_progress.seed_build()  # reseeded, not reset to a plain Build() -- owned upgrades persist across restarts
        self.augment_build = AugmentBuild()
        self.teleporters = []
        self._teleport_map = {}
        self.doors = []
        self.keys = []
        self._locked_doors = set()
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

    @property
    def rotation_warning_active(self) -> bool:
        """True while the rotating maze augment's warning arrow should show, shortly before each rotation fires."""
        return (
            self.augment_build.level_of(ROTATING_MAZE_ID) > 0
            and self.rotation_timer.remaining <= ROTATE_WARNING_LEAD_SECONDS
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _current_break_choices(self) -> list | None:
        if self.break_kind == "shop":
            return self.shop_choices
        if self.break_kind == "augment":
            return self.augment_choices
        return None

    def _is_gated(self) -> bool:
        return bool(self.on_break or self.failed or self.completed_run or self.finished)

    def _maze_cleared(self) -> bool:
        return self.player == self.goal

    def _begin_maze(self) -> None:
        cols, rows = dimensions_for_maze(self.maze_index)
        self.cols, self.rows = cols, rows
        self.grid = generate_maze(cols, rows, rng=self.rng)
        self.player = START_POS

        # Augments (e.g. teleporting squares) are a post-process over the
        # freshly-generated grid -- generate_maze() itself stays untouched.
        default_target = farthest_reachable_cell(self.grid, START_POS)
        ctx = run_pipeline(self.grid, cols, rows, START_POS, default_target, self.augment_build, self.rng)
        self.grid = ctx.grid
        self.teleporters = ctx.extra.get("teleporters", [])
        self._teleport_map = {}
        for pair in self.teleporters:
            self._teleport_map[pair.a] = pair.b
            self._teleport_map[pair.b] = pair.a

        self.doors = ctx.extra.get("doors", [])
        self._locked_doors = {pair.door for pair in self.doors}
        self.keys = [Key(pair.key, door_cell=pair.door) for pair in self.doors]

        self.goal = ctx.goal
        exclude = {START_POS, self.goal} | ctx.reserved
        self.pellets = spawn_pellets(self.grid, exclude, self.build.pellet_frequency_multiplier, rng=self.rng)
        exclude = exclude | {p.pos for p in self.pellets}
        self.gold_pellets = spawn_gold_pellets(self.grid, exclude, rng=self.rng)
        exclude = exclude | {p.pos for p in self.gold_pellets}
        if self.maze_index >= HAZARD_UNLOCK_MAZE:
            self.hazards = spawn_hazards(
                self.grid, exclude, density_multiplier=hazard_density_ramp(self.maze_index), rng=self.rng,
            )
        else:
            self.hazards = []

        self._par_seconds = SPEED_BONUS_SECONDS_PER_CELL * len(
            shortest_path(self.grid, START_POS, self.goal, extra_edges=self._teleport_map)
        )

        # A new maze is a wholly different layout -- discovered_cells (fog
        # of war's "memory") resets every maze, not just once per run.
        self.discovered_cells: set[tuple[int, int]] = set()
        if self.augment_build.level_of(FOG_OF_WAR_ID) > 0:
            self.discovered_cells |= visible_cells_from(self.grid, self.player)

        self._maze_started_at = time.monotonic()
        self.finished = False
        self.shield_charges_remaining = self.build.hazard_shield_charges_per_maze

    def _rotate_maze(self) -> None:
        """
        Rotate the grid and every entity position 90 degrees clockwise
        together, atomically -- see rotation.py's module docstring for why
        this is a genuine isometry (same maze, differently oriented) and
        needs no solvability re-verification.

        Relies on every maze this game generates being square
        (dimensions_for_maze() guarantees cols == rows) -- asserted here
        rather than silently corrupting state if that guarantee is ever
        broken by a future change.

        self._par_seconds is deliberately left untouched: hop-count between
        two rotated cells over a rotated grid is provably identical to the
        pre-rotation hop count (it's an isometry), so there's nothing to
        recompute.
        """
        assert self.cols == self.rows
        n = self.cols
        rot = lambda cell: rotate_cell_cw(cell, n)

        self.grid = rotate_grid_cw(self.grid)
        self.player = rot(self.player)
        self.goal = rot(self.goal)

        for entity in (*self.pellets, *self.gold_pellets, *self.hazards):
            entity.pos = rot(entity.pos)
        for key in self.keys:
            key.pos = rot(key.pos)
            key.door_cell = rot(key.door_cell)
        for popup in self.popups:
            popup.pos = rot(popup.pos)
        # Fog of war's "memory" is keyed to grid coordinates -- rotate it in
        # lockstep with everything else, or a rotation would silently
        # invalidate everywhere the player has already discovered.
        self.discovered_cells = {rot(c) for c in self.discovered_cells}

        self.teleporters = [
            TeleporterPair(a=rot(pair.a), b=rot(pair.b), mandatory=pair.mandatory, color_index=pair.color_index)
            for pair in self.teleporters
        ]
        self._teleport_map = {}
        for pair in self.teleporters:
            self._teleport_map[pair.a] = pair.b
            self._teleport_map[pair.b] = pair.a

        # _locked_doors is a set of door *cells* -- rotate it by mapping
        # each old door's pre-rotation cell to its (already-rotated)
        # replacement, preserving lock state across the transform.
        rotated_by_old_door = {pair.door: rot(pair.door) for pair in self.doors}
        still_locked = {rotated_by_old_door[door] for door in self._locked_doors}
        self.doors = [
            DoorKeyPair(door=rot(pair.door), key=rot(pair.key), mandatory=pair.mandatory, color_index=pair.color_index)
            for pair in self.doors
        ]
        self._locked_doors = still_locked

        # A <150ms animation window against a >=1s rotation interval
        # essentially never overlaps in practice; clearing is simpler than
        # reasoning about rotating an in-flight interpolation.
        self.teleport_animation = None

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
        self.rotation_timer.resync()  # same staleness class as self.time above, same fix
        self.maze_index += 1
        self._begin_maze()  # seamless when no break was due -- no pause within a group

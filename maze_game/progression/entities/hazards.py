"""
hazards.py
----------
Pellets (one-time time top-ups), gold pellets (one-time additions to the
persistent gold total -- see GoldPellet/load_gold_total/save_gold_total),
and hazards (persistent time-cost obstacles) placed in a maze at generation
time. New hazard *types* are added by subclassing Hazard and appending to
HAZARD_TYPES -- spawn_hazards() samples from that registry, so no other code
needs to change.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from maze_game.constants import (
    PELLET_TIME_VALUE, PELLET_DENSITY, PELLET_MIN_COUNT,
    PELLET_VALUE_RAMP_START_MAZE, PELLET_VALUE_RAMP_MAZES, PELLET_VALUE_RAMP_END_MULTIPLIER,
    PELLET_KIND_PLAIN, PELLET_KIND_DOUBLE, PELLET_KIND_VOLATILE, PELLET_KIND_CHAIN,
    PELLET_KIND_FREEZE, PELLET_KIND_GAMBLE, PELLET_KIND_WEIGHTS, PELLET_KIND_VALUE_MULTIPLIERS,
    PELLET_VOLATILE_EXTRA_HAZARD_COUNT, PELLET_FREEZE_DURATION_SECONDS, PELLET_CHAIN_MULTIPLIER,
    PELLET_GAMBLE_WIN_CHANCE, PELLET_GAMBLE_WIN_MULTIPLIER, PELLET_GAMBLE_LOSE_FRACTION,
    GOLD_PELLET_VALUE, GOLD_SPAWN_CHANCE, C_GOLD,
    HAZARD_TIME_PENALTY, HAZARD_DENSITY, HAZARD_MAX_COUNT,
    HAZARD_UNLOCK_MAZE, HAZARD_RAMP_MAZES, HAZARD_RAMP_START_MULTIPLIER,
    C_PELLET, C_PELLET_DOUBLE, C_PELLET_VOLATILE, C_PELLET_CHAIN, C_PELLET_FREEZE, C_PELLET_GAMBLE,
    C_SHIELD, APP_ROOT,
)
from maze_game.progression.entities import MazeEntity, apply_time_penalty

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun

DEFAULT_GOLD_PATH = APP_ROOT / "gold.json"


class Pellet(MazeEntity):
    def __init__(self, pos: tuple[int, int], value: float = PELLET_TIME_VALUE, kind: str = PELLET_KIND_PLAIN) -> None:
        super().__init__(pos)
        self.value = value
        self.kind = kind

    def on_contact(self, run: "LabyrinthRun") -> None:
        PELLET_KIND_EFFECTS[self.kind](self, run)


class GoldPellet(MazeEntity):
    """
    A one-time pickup adding to the persistent gold total (run.gold),
    separate from Pellet's time top-up. Not a Pellet subclass -- different
    resource, different persistence lifecycle (survives restart(), saved to
    disk immediately on contact rather than reset each run).
    """

    def __init__(self, pos: tuple[int, int], value: int = GOLD_PELLET_VALUE) -> None:
        super().__init__(pos)
        self.value = value

    def on_contact(self, run: "LabyrinthRun") -> None:
        run.gold += self.value
        run.add_popup(self.pos, f"+{self.value}g", C_GOLD)
        run.events.append("gold")
        save_gold_total(run.gold, run.gold_path)


class Hazard(MazeEntity):
    penalty: float = HAZARD_TIME_PENALTY

    def on_contact(self, run: "LabyrinthRun") -> None:
        if run.freeze_active:
            run.add_popup(self.pos, "Frozen!", C_PELLET_FREEZE)
            run.events.append("freeze_block")
            return
        # Counts toward Momentum's "hazard-free clear" streak whether or not
        # a shield absorbed it -- a shielded hit still touched a hazard, it
        # just didn't cost time. A freeze-blocked hit above, by contrast,
        # never really "touched" a live hazard (freeze neutralizes it
        # entirely), so it doesn't count.
        run.hazard_contacts_this_maze += 1
        if run.shield_charges_remaining > 0:
            run.shield_charges_remaining -= 1
            run.add_popup(self.pos, "Shielded!", C_SHIELD)
            run.events.append("shield_block")
            return
        apply_time_penalty(run, self.penalty * run.build.hazard_resistance_multiplier, self.pos)


HAZARD_TYPES: list[type[Hazard]] = [Hazard]


def _grant_time(pellet: "Pellet", run: "LabyrinthRun", value: float, colour: tuple[int, int, int]) -> None:
    """Shared time-grant path for every pellet kind that actually gives time: folds in the pending Chain multiplier and the player's own pellet_value_multiplier, then resets the Chain multiplier back to 1.0."""
    amount = value * run.pending_chain_multiplier * run.build.pellet_value_multiplier
    run.pending_chain_multiplier = 1.0
    run.time.add(amount)
    run.add_popup(pellet.pos, f"+{amount:.1f}s", colour)
    run.events.append("pellet")


def _pellet_effect_plain(pellet: "Pellet", run: "LabyrinthRun") -> None:
    _grant_time(pellet, run, pellet.value, C_PELLET)


def _pellet_effect_double(pellet: "Pellet", run: "LabyrinthRun") -> None:
    _grant_time(pellet, run, pellet.value, C_PELLET_DOUBLE)


def _pellet_effect_volatile(pellet: "Pellet", run: "LabyrinthRun") -> None:
    _grant_time(pellet, run, pellet.value, C_PELLET_VOLATILE)
    exclude = (
        {run.player, run.goal}
        | {p.pos for p in run.pellets} | {p.pos for p in run.gold_pellets} | {h.pos for h in run.hazards}
    )
    candidates = [c for c in _open_cells(run.grid) if c not in exclude]
    if candidates:
        for pos in run.rng.sample(candidates, min(PELLET_VOLATILE_EXTRA_HAZARD_COUNT, len(candidates))):
            run.hazards.append(Hazard(pos))


def _pellet_effect_chain(pellet: "Pellet", run: "LabyrinthRun") -> None:
    run.pending_chain_multiplier *= PELLET_CHAIN_MULTIPLIER
    run.add_popup(pellet.pos, "Chain!", C_PELLET_CHAIN)
    run.events.append("pellet_chain")


def _pellet_effect_freeze(pellet: "Pellet", run: "LabyrinthRun") -> None:
    run.freeze_until = time.monotonic() + PELLET_FREEZE_DURATION_SECONDS
    run.add_popup(pellet.pos, "Freeze!", C_PELLET_FREEZE)
    run.events.append("pellet_freeze")


def _pellet_effect_gamble(pellet: "Pellet", run: "LabyrinthRun") -> None:
    if run.rng.random() < PELLET_GAMBLE_WIN_CHANCE:
        _grant_time(pellet, run, pellet.value * PELLET_GAMBLE_WIN_MULTIPLIER, C_PELLET_GAMBLE)
    else:
        run.time.scale(1.0 - PELLET_GAMBLE_LOSE_FRACTION)
        run.add_popup(pellet.pos, "Bust!", C_PELLET_GAMBLE)
        run.events.append("pellet_gamble_bust")


PELLET_KIND_EFFECTS: dict[str, Callable[["Pellet", "LabyrinthRun"], None]] = {
    PELLET_KIND_PLAIN:    _pellet_effect_plain,
    PELLET_KIND_DOUBLE:   _pellet_effect_double,
    PELLET_KIND_VOLATILE: _pellet_effect_volatile,
    PELLET_KIND_CHAIN:    _pellet_effect_chain,
    PELLET_KIND_FREEZE:   _pellet_effect_freeze,
    PELLET_KIND_GAMBLE:   _pellet_effect_gamble,
}


def _open_cells(grid: list[list[int]]) -> list[tuple[int, int]]:
    return [(x, y) for y, row in enumerate(grid) for x, val in enumerate(row) if val == 0]


def _entity_count(candidate_count: int, density: float, minimum: int, maximum: int | None = None) -> int:
    """count = density * sqrt(candidate cells), floored at `minimum`, capped at `maximum` if given."""
    count = max(minimum, round(density * math.sqrt(candidate_count))) if candidate_count > 0 else 0
    return min(count, maximum) if maximum is not None else count


def hazard_density_ramp(maze_index: int) -> float:
    """
    Density multiplier for spawn_hazards(), starting at
    HAZARD_RAMP_START_MULTIPLIER on the maze hazards first unlock (~1 hazard,
    rather than the ~4-5 full density spawns immediately) and reaching full
    density (1.0x) HAZARD_RAMP_MAZES mazes later. Callers are expected to
    only call this for maze_index >= HAZARD_UNLOCK_MAZE.
    """
    mazes_since_unlock = maze_index - HAZARD_UNLOCK_MAZE
    progress = min(1.0, mazes_since_unlock / HAZARD_RAMP_MAZES)
    return HAZARD_RAMP_START_MULTIPLIER + (1.0 - HAZARD_RAMP_START_MULTIPLIER) * progress


def pellet_value_ramp(maze_index: int) -> float:
    """
    Value multiplier for spawn_pellets(): 1.0x before PELLET_VALUE_RAMP_START_MAZE,
    ramping up to PELLET_VALUE_RAMP_END_MULTIPLIER over the following
    PELLET_VALUE_RAMP_MAZES mazes -- see the constant's docstring for why.
    """
    if maze_index < PELLET_VALUE_RAMP_START_MAZE:
        return 1.0
    mazes_since_start = maze_index - PELLET_VALUE_RAMP_START_MAZE
    progress = min(1.0, mazes_since_start / PELLET_VALUE_RAMP_MAZES)
    return 1.0 + (PELLET_VALUE_RAMP_END_MULTIPLIER - 1.0) * progress


def spawn_pellets(
    grid: list[list[int]],
    exclude: set[tuple[int, int]],
    frequency_multiplier: float = 1.0,
    value_multiplier: float = 1.0,
    rng: random.Random | None = None,
) -> list[Pellet]:
    rng = rng if rng is not None else random
    candidates = [c for c in _open_cells(grid) if c not in exclude]
    count = min(_entity_count(len(candidates), PELLET_DENSITY * frequency_multiplier, PELLET_MIN_COUNT), len(candidates))
    kinds = list(PELLET_KIND_WEIGHTS)
    weights = list(PELLET_KIND_WEIGHTS.values())
    pellets = []
    for pos in rng.sample(candidates, count):
        kind = rng.choices(kinds, weights=weights)[0]
        value = PELLET_TIME_VALUE * value_multiplier * PELLET_KIND_VALUE_MULTIPLIERS[kind]
        pellets.append(Pellet(pos, value=value, kind=kind))
    return pellets


def spawn_pellet_cluster_near(
    grid: list[list[int]],
    center: tuple[int, int],
    exclude: set[tuple[int, int]],
    count: int,
    radius: int,
    rng: random.Random | None = None,
) -> list[Pellet]:
    """
    A small guaranteed cluster of plain pellets within `radius` grid steps
    (Chebyshev distance -- cheap and good enough for "nearby," no BFS
    needed) of `center`, for augments that want a reward clustered near a
    specific cell (e.g. Twin Goals' bonus goal) on top of the normal
    maze-wide scattered spawn_pellets() pass. Graceful degradation, same
    convention as every other placement helper here: returns fewer than
    `count` (even zero) if there aren't enough qualifying open cells nearby,
    never raises.
    """
    rng = rng if rng is not None else random
    cx, cy = center
    candidates = [
        c for c in _open_cells(grid)
        if c not in exclude and max(abs(c[0] - cx), abs(c[1] - cy)) <= radius
    ]
    chosen = rng.sample(candidates, min(count, len(candidates)))
    return [Pellet(pos, value=PELLET_TIME_VALUE, kind=PELLET_KIND_PLAIN) for pos in chosen]


def spawn_gold_pellets(
    grid: list[list[int]],
    exclude: set[tuple[int, int]],
    chance: float = GOLD_SPAWN_CHANCE,
    rng: random.Random | None = None,
) -> list[GoldPellet]:
    """A maze has a `chance` chance of containing exactly one gold pellet -- rare by design, see constants.py."""
    rng = rng if rng is not None else random
    if rng.random() >= chance:
        return []
    candidates = [c for c in _open_cells(grid) if c not in exclude]
    if not candidates:
        return []
    return [GoldPellet(rng.choice(candidates))]


def load_gold_total(path: Path = DEFAULT_GOLD_PATH) -> int:
    """Load the persistent gold total from disk. Returns 0 if the file is missing or unreadable."""
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    try:
        return int(raw.get("gold", 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def save_gold_total(amount: int, path: Path = DEFAULT_GOLD_PATH) -> None:
    path.write_text(json.dumps({"gold": amount}))


def spawn_hazards(
    grid: list[list[int]],
    exclude: set[tuple[int, int]],
    density_multiplier: float = 1.0,
    rng: random.Random | None = None,
) -> list[Hazard]:
    rng = rng if rng is not None else random
    candidates = [c for c in _open_cells(grid) if c not in exclude]
    count = min(
        _entity_count(len(candidates), HAZARD_DENSITY * density_multiplier, minimum=0, maximum=HAZARD_MAX_COUNT),
        len(candidates),
    )
    return [rng.choice(HAZARD_TYPES)(pos) for pos in rng.sample(candidates, count)]

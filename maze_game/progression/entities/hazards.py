"""
hazards.py
----------
Pellets (one-time time top-ups), gold pellets (one-time additions to the
persistent gold total -- see GoldPellet/load_gold_total/save_gold_total),
and hazards (persistent time-cost obstacles) placed in a maze at generation
time. New hazard *types* are added by subclassing Hazard, appending to
HAZARD_TYPES, and adding an (unlock maze, relative weight) entry to
_HAZARD_UNLOCKS -- spawn_hazards() weighted-samples from whatever
hazard_types_for_maze() says is unlocked at the current maze index, so no
other code needs to change.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import TYPE_CHECKING

from maze_game.constants import (
    PELLET_TIME_VALUE, PELLET_DENSITY, PELLET_MIN_COUNT,
    GOLD_PELLET_VALUE, GOLD_SPAWN_CHANCE, C_GOLD,
    HAZARD_TIME_PENALTY, HAZARD_DENSITY, HAZARD_MAX_COUNT,
    HAZARD_UNLOCK_MAZE, HAZARD_RAMP_MAZES, HAZARD_RAMP_START_MULTIPLIER,
    HAZARD_BASE_WEIGHT,
    HAZARD_HEAVY_UNLOCK_MAZE, HAZARD_HEAVY_TIME_PENALTY, HAZARD_HEAVY_WEIGHT,
    HAZARD_EXTREME_UNLOCK_MAZE, HAZARD_EXTREME_TIME_FRACTION, HAZARD_EXTREME_WEIGHT,
    C_PELLET, C_SHIELD, APP_ROOT,
)
from maze_game.progression.entities import MazeEntity, apply_time_penalty, open_cells

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun

DEFAULT_GOLD_PATH = APP_ROOT / "gold.json"


class Pellet(MazeEntity):
    def __init__(self, pos: tuple[int, int], value: float = PELLET_TIME_VALUE) -> None:
        super().__init__(pos)
        self.value = value

    def on_contact(self, run: "LabyrinthRun") -> None:
        amount = self.value * run.build.pellet_value_multiplier
        run.time.add(amount)
        run.add_popup(self.pos, f"+{amount:.1f}s", C_PELLET)
        run.events.append("pellet")


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
        if run.shield_charges_remaining > 0:
            run.shield_charges_remaining -= 1
            run.add_popup(self.pos, "Shielded!", C_SHIELD)
            run.events.append("shield_block")
            return
        self._apply_effect(run)

    def _apply_effect(self, run: "LabyrinthRun") -> None:
        """The actual time cost, run once shield-blocking has been ruled out. Subclasses override this, not on_contact(), to keep the shield-charge handling shared."""
        apply_time_penalty(run, self.penalty * run.build.hazard_resistance_multiplier, self.pos)


class HeavyHazard(Hazard):
    """A flat-penalty hazard, same mechanic as the base Hazard but costing far more per contact."""
    penalty: float = HAZARD_HEAVY_TIME_PENALTY


class ExtremeHazard(Hazard):
    """
    The most severe hazard: instead of a flat penalty, takes
    HAZARD_EXTREME_TIME_FRACTION of the player's *current* banked time on
    contact -- an unavoidable-contact hazard rather than a pellet gamble, so
    it scales with (and specifically punishes) however much time the player
    has saved up, rather than being a fixed cost a large buffer shrugs off.
    """

    def _apply_effect(self, run: "LabyrinthRun") -> None:
        amount = run.time.amount * HAZARD_EXTREME_TIME_FRACTION * run.build.hazard_resistance_multiplier
        apply_time_penalty(run, amount, self.pos)


HAZARD_TYPES: list[type[Hazard]] = [Hazard, HeavyHazard, ExtremeHazard]

# Unlock maze + relative spawn weight for each type in HAZARD_TYPES, same
# order -- hazard_types_for_maze() filters this down to whatever's unlocked
# by a given maze index (keeping their relative weights) for spawn_hazards()
# to weighted-sample from. Callers are expected to only call it for
# maze_index >= HAZARD_UNLOCK_MAZE (spawn_hazards()'s existing contract),
# so the base Hazard entry is always included.
_HAZARD_UNLOCKS: list[tuple[type[Hazard], int, float]] = [
    (Hazard, HAZARD_UNLOCK_MAZE, HAZARD_BASE_WEIGHT),
    (HeavyHazard, HAZARD_HEAVY_UNLOCK_MAZE, HAZARD_HEAVY_WEIGHT),
    (ExtremeHazard, HAZARD_EXTREME_UNLOCK_MAZE, HAZARD_EXTREME_WEIGHT),
]


def hazard_types_for_maze(maze_index: int) -> tuple[list[type[Hazard]], list[float]]:
    """Hazard types unlocked by `maze_index`, paired with their relative spawn weights."""
    types = [t for t, unlock_maze, _weight in _HAZARD_UNLOCKS if maze_index >= unlock_maze]
    weights = [w for _t, unlock_maze, w in _HAZARD_UNLOCKS if maze_index >= unlock_maze]
    return types, weights


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


def spawn_pellets(
    grid: list[list[int]],
    exclude: set[tuple[int, int]],
    frequency_multiplier: float = 1.0,
    rng: random.Random | None = None,
) -> list[Pellet]:
    rng = rng if rng is not None else random
    candidates = [c for c in open_cells(grid) if c not in exclude]
    count = min(_entity_count(len(candidates), PELLET_DENSITY * frequency_multiplier, PELLET_MIN_COUNT), len(candidates))
    return [Pellet(pos) for pos in rng.sample(candidates, count)]


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
    candidates = [c for c in open_cells(grid) if c not in exclude]
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
    maze_index: int = HAZARD_UNLOCK_MAZE,
    rng: random.Random | None = None,
) -> list[Hazard]:
    rng = rng if rng is not None else random
    candidates = [c for c in open_cells(grid) if c not in exclude]
    count = min(
        _entity_count(len(candidates), HAZARD_DENSITY * density_multiplier, minimum=0, maximum=HAZARD_MAX_COUNT),
        len(candidates),
    )
    types, weights = hazard_types_for_maze(maze_index)
    return [rng.choices(types, weights=weights)[0](pos) for pos in rng.sample(candidates, count)]

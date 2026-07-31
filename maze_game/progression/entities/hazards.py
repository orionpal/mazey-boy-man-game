"""
hazards.py
----------
Pellets (one-time time top-ups), gold pellets (one-time additions to the
persistent gold total -- see GoldPellet/load_gold_total/save_gold_total),
and enemies (persistent time-cost hazards) placed in a maze at generation
time. New enemy *types* are added by subclassing Enemy and appending to
ENEMY_TYPES -- spawn_enemies() samples from that registry, so no other code
needs to change.
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
    ENEMY_TIME_PENALTY, ENEMY_DENSITY, ENEMY_MAX_COUNT,
    ENEMY_UNLOCK_MAZE, ENEMY_RAMP_MAZES, ENEMY_RAMP_START_MULTIPLIER,
    C_PELLET,
)
from maze_game.progression.entities import MazeEntity, apply_time_penalty

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun

DEFAULT_GOLD_PATH = Path(__file__).resolve().parent.parent.parent.parent / "gold.json"


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


class Enemy(MazeEntity):
    penalty: float = ENEMY_TIME_PENALTY

    def on_contact(self, run: "LabyrinthRun") -> None:
        apply_time_penalty(run, self.penalty, self.pos)


ENEMY_TYPES: list[type[Enemy]] = [Enemy]


def _open_cells(grid: list[list[int]]) -> list[tuple[int, int]]:
    return [(x, y) for y, row in enumerate(grid) for x, val in enumerate(row) if val == 0]


def _entity_count(candidate_count: int, density: float, minimum: int, maximum: int | None = None) -> int:
    """count = density * sqrt(candidate cells), floored at `minimum`, capped at `maximum` if given."""
    count = max(minimum, round(density * math.sqrt(candidate_count))) if candidate_count > 0 else 0
    return min(count, maximum) if maximum is not None else count


def enemy_density_ramp(maze_index: int) -> float:
    """
    Density multiplier for spawn_enemies(), starting at
    ENEMY_RAMP_START_MULTIPLIER on the maze enemies first unlock (~1 enemy,
    rather than the ~4-5 full density spawns immediately) and reaching full
    density (1.0x) ENEMY_RAMP_MAZES mazes later. Callers are expected to
    only call this for maze_index >= ENEMY_UNLOCK_MAZE.
    """
    mazes_since_unlock = maze_index - ENEMY_UNLOCK_MAZE
    progress = min(1.0, mazes_since_unlock / ENEMY_RAMP_MAZES)
    return ENEMY_RAMP_START_MULTIPLIER + (1.0 - ENEMY_RAMP_START_MULTIPLIER) * progress


def spawn_pellets(
    grid: list[list[int]],
    exclude: set[tuple[int, int]],
    frequency_multiplier: float = 1.0,
    rng: random.Random | None = None,
) -> list[Pellet]:
    rng = rng if rng is not None else random
    candidates = [c for c in _open_cells(grid) if c not in exclude]
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


def spawn_enemies(
    grid: list[list[int]],
    exclude: set[tuple[int, int]],
    density_multiplier: float = 1.0,
    rng: random.Random | None = None,
) -> list[Enemy]:
    rng = rng if rng is not None else random
    candidates = [c for c in _open_cells(grid) if c not in exclude]
    count = min(
        _entity_count(len(candidates), ENEMY_DENSITY * density_multiplier, minimum=0, maximum=ENEMY_MAX_COUNT),
        len(candidates),
    )
    return [rng.choice(ENEMY_TYPES)(pos) for pos in rng.sample(candidates, count)]

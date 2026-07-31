"""
hazards.py
----------
Pellets (one-time time top-ups) and enemies (persistent time-cost hazards)
placed in a maze at generation time. New enemy *types* are added by
subclassing Enemy and appending to ENEMY_TYPES -- spawn_enemies() samples
from that registry, so no other code needs to change.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from maze_game.constants import (
    PELLET_TIME_VALUE, PELLET_DENSITY, PELLET_MIN_COUNT,
    ENEMY_TIME_PENALTY, ENEMY_DENSITY, ENEMY_MAX_COUNT,
)
from maze_game.progression.entities import MazeEntity, apply_time_penalty

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun


class Pellet(MazeEntity):
    def __init__(self, pos: tuple[int, int], value: float = PELLET_TIME_VALUE) -> None:
        super().__init__(pos)
        self.value = value

    def on_contact(self, run: "LabyrinthRun") -> None:
        run.time.add(self.value * run.build.pellet_value_multiplier)


class Enemy(MazeEntity):
    penalty: float = ENEMY_TIME_PENALTY

    def on_contact(self, run: "LabyrinthRun") -> None:
        apply_time_penalty(run, self.penalty)


ENEMY_TYPES: list[type[Enemy]] = [Enemy]


def _open_cells(grid: list[list[int]]) -> list[tuple[int, int]]:
    return [(x, y) for y, row in enumerate(grid) for x, val in enumerate(row) if val == 0]


def _entity_count(candidate_count: int, density: float, minimum: int, maximum: int | None = None) -> int:
    """count = density * sqrt(candidate cells), floored at `minimum`, capped at `maximum` if given."""
    count = max(minimum, round(density * math.sqrt(candidate_count))) if candidate_count > 0 else 0
    return min(count, maximum) if maximum is not None else count


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


def spawn_enemies(
    grid: list[list[int]], exclude: set[tuple[int, int]], rng: random.Random | None = None,
) -> list[Enemy]:
    rng = rng if rng is not None else random
    candidates = [c for c in _open_cells(grid) if c not in exclude]
    count = min(_entity_count(len(candidates), ENEMY_DENSITY, minimum=0, maximum=ENEMY_MAX_COUNT), len(candidates))
    return [rng.choice(ENEMY_TYPES)(pos) for pos in rng.sample(candidates, count)]

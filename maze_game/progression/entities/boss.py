"""
boss.py
-------
The boss encountered every BOSS_INTERVAL-th maze. Deliberately NOT an Enemy
subclass -- it's the maze's win condition with its own phase state, not "an
enemy but bigger"; the ~3 lines of behaviour it shares with a regular
enemy's contact (costing the player time) go through the free
apply_time_penalty() helper instead of inheritance, so a boss can never
accidentally end up iterated alongside randomly-spawned enemies.

Alternates idle/active every player move: idle turns (move_count 0, 2, 4,
...) leave it stationary -- contact then damages it; active turns (1, 3, 5,
...) step it one cell toward the player and contact instead costs the
player time, same as a regular enemy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from maze_game.constants import BOSS_INTERVAL, LABYRINTH_GROUP_SIZE, BOSS_BASE_DAMAGE, ENEMY_TIME_PENALTY
from maze_game.maze import shortest_path
from maze_game.progression.entities import MazeEntity, apply_time_penalty

if TYPE_CHECKING:
    from maze_game.progression.run import LabyrinthRun

# A boss maze must land on a group boundary, where a perk-choice break
# already exists -- if either constant is retuned independently, a boss
# maze could otherwise land mid-group with no break before or after it.
assert BOSS_INTERVAL % LABYRINTH_GROUP_SIZE == 0


def is_boss_maze(maze_index: int) -> bool:
    return maze_index % BOSS_INTERVAL == 0


class Boss(MazeEntity):
    def __init__(self, pos: tuple[int, int], hp: int) -> None:
        super().__init__(pos)
        self.hp = hp
        self.move_count = 0
        self.phase = "idle"

    @property
    def defeated(self) -> bool:
        return self.hp <= 0

    def advance(self, player_pos: tuple[int, int], grid: list[list[int]]) -> None:
        """Call once per player move, before resolving contact for that move."""
        self.phase = "idle" if self.move_count % 2 == 0 else "active"
        if self.phase == "active":
            path = shortest_path(grid, self.pos, player_pos)
            if len(path) > 1:
                self.pos = path[1]
        self.move_count += 1

    def on_contact(self, run: "LabyrinthRun") -> None:
        if self.phase == "idle":
            self.hp -= BOSS_BASE_DAMAGE * run.build.strength_multiplier
        else:
            apply_time_penalty(run, ENEMY_TIME_PENALTY)

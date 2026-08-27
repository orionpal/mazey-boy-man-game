"""
state.py
--------
Pure state machine for the 3D arena interlude -- the one-time replay of a
run's very first maze that fires after the first group of 5 mazes (see
docs/planning/3d-rework.md and progression/run.py::_advance).

Deliberately independent of pygame, same rule as progression/run.py: the
whole thing is drivable and testable without a display. arena/app.py owns
the event loop and pumps real time into update(); arena/renderer.py reads
this state and draws it.

Model:
- Tile-based "tank" movement on the snapshotted maze grid: turn() rotates
  90 deg in place, step() moves one cell along the current facing if that
  cell is open and unoccupied.
- Enemies are slow chasers. Every player action each live enemy that is
  "awake" takes one greedy step toward the player. If an enemy reaches the
  player's cell it deals 1 damage and dies (kamikaze). attack() kills a
  live enemy in the cell directly ahead -- so the fight is: face it, hit it
  before it closes the gap.
- Treasures sit at far dead-ends off the recorded route. Walking onto one
  banks its gold; the cost is the detour time (the arena's time budget is
  ticking) and the extra trail scribble it adds in the replay.
- Ends when the player reaches the maze's goal cell ("win"), runs out of
  health ("lose"), or runs out of time ("timeout"). app.py sets "quit".
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

from maze_game.progression.run import FirstMazeRecord, TimeResource
from maze_game.arena.entities import Enemy, EnemyKind, Treasure, ROSTER

# Re-exported so callers/tests can keep importing these from arena.state.
__all__ = ["ArenaState", "Enemy", "EnemyKind", "Treasure", "FACINGS"]

# Facing index -> unit (dx, dy). Clockwise from north, so turn(+1) is "right".
FACINGS: list[tuple[int, int]] = [(0, -1), (1, 0), (0, 1), (-1, 0)]


@dataclass
class ArenaState:
    record: FirstMazeRecord
    rng: random.Random
    time_budget: float
    max_health: int
    enemy_count: int
    treasure_count: int
    treasure_gold: int

    # Derived / mutable ---------------------------------------------------
    pos: tuple[int, int] = (1, 1)
    facing: int = 1
    health: int = 0
    outcome: str | None = None
    enemies: list[Enemy] = field(default_factory=list)
    treasures: list[Treasure] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    _tick_parity: int = 0
    _active_ticks: int = 0

    def __post_init__(self) -> None:
        self.grid = self.record.grid
        self.rows = len(self.grid)
        self.cols = len(self.grid[0])
        self.goal = self.record.goal
        self.trail = list(self.record.trail)
        self.trail_cells = set(self.trail)
        self.pos = self.record.start
        self.health = self.max_health
        self.time = TimeResource(self.time_budget)
        self.facing = self._initial_facing()
        dist = self._bfs_dist(self.record.start)
        self.enemies = self._place_enemies(dist)
        self.treasures = self._place_treasures(dist)

    # ── Queries ───────────────────────────────────────────────────────────

    @property
    def gold_collected(self) -> int:
        return sum(self.treasure_gold for t in self.treasures if t.collected)

    @property
    def over(self) -> bool:
        return self.outcome is not None

    def enemy_ahead(self) -> Enemy | None:
        """The live enemy in the cell directly in front of the player, if any."""
        dx, dy = FACINGS[self.facing]
        target = (self.pos[0] + dx, self.pos[1] + dy)
        for enemy in self.enemies:
            if enemy.alive and enemy.pos == target:
                return enemy
        return None

    def is_open(self, cell: tuple[int, int]) -> bool:
        x, y = cell
        return 0 <= x < self.cols and 0 <= y < self.rows and self.grid[y][x] == 0

    # ── Player actions (each one advances the enemy sim once) ─────────────

    def turn(self, delta: int) -> None:
        if self.over:
            return
        self.facing = (self.facing + delta) % 4
        self._after_action()

    def step(self, sign: int) -> None:
        """sign = +1 forward along facing, -1 backward."""
        if self.over:
            return
        dx, dy = FACINGS[self.facing]
        target = (self.pos[0] + sign * dx, self.pos[1] + sign * dy)
        if self.is_open(target) and not self._enemy_at(target):
            self.pos = target
            self.events.append("move")
            self._collect_here()
        self._after_action()

    def attack(self) -> None:
        if self.over:
            return
        enemy = self.enemy_ahead()
        if enemy is not None:
            enemy.wounds += 1
            if enemy.down:
                enemy.alive = False
            self.events.append("hazard")  # reuse the existing "combat-y thud" sound
        self._after_action()

    def update(self) -> None:
        """Call once per frame from app.py -- only advances the clock."""
        if self.over:
            return
        self.time.tick()
        if self.time.depleted:
            self.outcome = "timeout"
            self.events.append("fail")

    # ── Internals ─────────────────────────────────────────────────────────

    def _after_action(self) -> None:
        if self.over:
            return
        if self.pos == self.goal:
            self.outcome = "win"
            self.events.append("maze_complete")
            return
        self._tick_enemies()
        if self.health <= 0:
            self.outcome = "lose"
            self.events.append("fail")

    def _enemy_at(self, cell: tuple[int, int]) -> bool:
        return any(e.alive and e.pos == cell for e in self.enemies)

    def _collect_here(self) -> None:
        for treasure in self.treasures:
            if not treasure.collected and treasure.pos == self.pos:
                treasure.collected = True
                self.events.append("gold")

    def _tick_enemies(self) -> None:
        """
        Every other player action ("active tick"), each awake enemy acts:
        strike if adjacent, else greedily step toward the player -- but only
        every ``kind.move_period``-th active tick, so a brute lumbers and a
        lurker keeps pace. Wake range is per-kind too (a lurker only stirs
        when you're almost on top of it).
        """
        self._tick_parity ^= 1
        if self._tick_parity == 0:
            return
        self._active_ticks += 1
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            if not enemy.awake and _manhattan(enemy.pos, self.pos) <= enemy.kind.wake_range:
                enemy.awake = True
            if not enemy.awake:
                continue
            if _manhattan(enemy.pos, self.pos) == 1:
                # Adjacent: the enemy strikes rather than moving, and keeps
                # striking every tick until the player kills it (attack()) or
                # backs out of reach. Attacking on the turn you close the gap
                # clears it before this fires -- attack() resolves the kill
                # before _tick_enemies().
                self.health -= 1
                self.events.append("hazard")
                continue
            if self._active_ticks % enemy.kind.move_period != 0:
                continue
            nxt = self._greedy_step(enemy.pos)
            if nxt is not None and not self._enemy_at(nxt) and nxt != self.pos:
                enemy.pos = nxt

    def _greedy_step(self, frm: tuple[int, int]) -> tuple[int, int] | None:
        best, best_d = None, _manhattan(frm, self.pos)
        for dx, dy in FACINGS:
            cand = (frm[0] + dx, frm[1] + dy)
            if not self.is_open(cand):
                continue
            d = _manhattan(cand, self.pos)
            if d < best_d:
                best, best_d = cand, d
        return best

    def _initial_facing(self) -> int:
        if len(self.trail) >= 2:
            ahead = (self.trail[1][0] - self.trail[0][0], self.trail[1][1] - self.trail[0][1])
            if ahead in FACINGS:
                return FACINGS.index(ahead)
        for i, (dx, dy) in enumerate(FACINGS):
            if self.is_open((self.record.start[0] + dx, self.record.start[1] + dy)):
                return i
        return 1

    def _bfs_dist(self, start: tuple[int, int]) -> dict[tuple[int, int], int]:
        dist = {start: 0}
        queue: deque[tuple[int, int]] = deque([start])
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in FACINGS:
                nb = (cx + dx, cy + dy)
                if self.is_open(nb) and nb not in dist:
                    dist[nb] = dist[(cx, cy)] + 1
                    queue.append(nb)
        return dist

    def _place_enemies(self, dist: dict[tuple[int, int], int]) -> list[Enemy]:
        # Spread along the recorded route, skipping the first/last stretch so
        # the player never spawns on top of one and the exit stays clean.
        route = [c for c in dict.fromkeys(self.trail) if c not in (self.record.start, self.goal)]
        if not route:
            return []
        lo, hi = int(len(route) * 0.2), int(len(route) * 0.9)
        window = route[lo:hi] or route
        count = min(self.enemy_count, len(window))
        if count == 0:
            return []
        picks = [window[round(i * (len(window) - 1) / max(1, count - 1))] for i in range(count)]
        # Cycle the roster by spawn order so the mix is deterministic and a
        # 3-enemy arena is one of each (grunt near the start, brute deepest).
        return [
            Enemy(pos=p, kind=ROSTER[i % len(ROSTER)])
            for i, p in enumerate(dict.fromkeys(picks))
        ]

    def _place_treasures(self, dist: dict[tuple[int, int], int]) -> list[Treasure]:
        dead_ends = [
            cell for cell, d in dist.items()
            if cell not in self.trail_cells
            and cell != self.goal
            and self._open_neighbours(cell) == 1
        ]
        dead_ends.sort(key=lambda c: dist[c], reverse=True)
        if len(dead_ends) < self.treasure_count:
            extra = sorted(
                (c for c in dist if c not in self.trail_cells and c != self.goal and c not in dead_ends),
                key=lambda c: dist[c], reverse=True,
            )
            dead_ends += extra
        return [Treasure(pos=p) for p in dead_ends[: self.treasure_count]]

    def _open_neighbours(self, cell: tuple[int, int]) -> int:
        return sum(1 for dx, dy in FACINGS if self.is_open((cell[0] + dx, cell[1] + dy)))


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

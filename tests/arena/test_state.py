"""Tests for maze_game.arena.state -- the pure arena state machine (no pygame)."""

import random

import pytest

from maze_game.progression.run import FirstMazeRecord
from maze_game.arena.state import ArenaState, Enemy, FACINGS
from maze_game.arena.entities import BRUTE, LURKER, ROSTER

# 7x7 hand maze. grid[y][x], 1 = wall, 0 = open.
_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1, 0, 1],
    [1, 1, 1, 0, 1, 0, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 0, 1, 1, 1, 0, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]
_TRAIL = [(1, 1), (2, 1), (3, 1), (3, 2), (3, 3), (4, 3), (5, 3), (5, 4), (5, 5)]
_GOAL = (5, 5)


def _record():
    return FirstMazeRecord(grid=[row[:] for row in _GRID], goal=_GOAL, trail=list(_TRAIL), start=(1, 1))


def _state(**kw):
    defaults = dict(
        record=_record(), rng=random.Random(0), time_budget=90.0, max_health=3,
        enemy_count=3, treasure_count=2, treasure_gold=5,
    )
    defaults.update(kw)
    return ArenaState(**defaults)


def test_starts_at_the_recorded_start_facing_along_the_trail():
    s = _state()
    assert s.pos == (1, 1)
    assert FACINGS[s.facing] == (1, 0)  # trail's first step is east
    assert s.health == 3
    assert s.outcome is None


def test_step_forward_moves_one_open_cell_and_step_into_wall_is_blocked():
    s = _state(enemy_count=0)
    s.step(1)
    assert s.pos == (2, 1)
    s.turn(-1)  # now facing north, wall above
    s.step(1)
    assert s.pos == (2, 1)


def test_turn_wraps_both_directions():
    s = _state()
    s.facing = 0
    s.turn(-1)
    assert s.facing == 3
    s.turn(1)
    assert s.facing == 0


def test_reaching_the_goal_cell_wins():
    s = _state(enemy_count=0, treasure_count=0)
    s.pos = (5, 4)
    s.facing = FACINGS.index((0, 1))
    s.step(1)
    assert s.pos == _GOAL
    assert s.outcome == "win"


def test_time_running_out_is_a_timeout():
    s = _state(time_budget=0.0, enemy_count=0)
    s.update()
    assert s.outcome == "timeout"


def test_enemies_land_on_the_recorded_route_and_never_on_start_or_goal():
    s = _state()
    assert s.enemies
    for enemy in s.enemies:
        assert enemy.pos in set(_TRAIL)
        assert enemy.pos not in ((1, 1), _GOAL)


def test_treasures_sit_off_the_recorded_route():
    s = _state()
    assert s.treasures
    for treasure in s.treasures:
        assert treasure.pos not in set(_TRAIL)


def test_cannot_walk_through_a_live_enemy_but_can_after_killing_it():
    s = _state(enemy_count=0)
    s.pos, s.facing = (1, 1), FACINGS.index((1, 0))
    s.enemies = [Enemy(pos=(2, 1))]
    s.step(1)
    assert s.pos == (1, 1)  # blocked
    assert s.enemy_ahead() is not None
    s.attack()
    assert s.enemies[0].alive is False
    s.step(1)
    assert s.pos == (2, 1)


def test_enemy_kinds_cycle_the_roster_by_spawn_order():
    s = _state(enemy_count=3)
    kinds = [e.kind for e in s.enemies]
    assert kinds == [ROSTER[i % len(ROSTER)] for i in range(len(kinds))]


def test_a_brute_takes_two_strikes_to_put_down():
    s = _state(enemy_count=0)
    s.pos, s.facing = (1, 1), FACINGS.index((1, 0))
    s.enemies = [Enemy(pos=(2, 1), kind=BRUTE)]
    s.attack()
    assert s.enemies[0].alive is True   # wounded, not down
    assert s.enemies[0].wounds == 1
    s.attack()
    assert s.enemies[0].alive is False


def test_a_lurker_stays_asleep_until_you_are_almost_on_top_of_it():
    s = _state(enemy_count=0)
    s.pos, s.facing = (1, 1), FACINGS.index((1, 0))
    s.enemies = [Enemy(pos=(3, 1), kind=LURKER)]  # Manhattan 2, == LURKER.wake_range
    s.turn(1); s.turn(1)  # two actions -> one active enemy tick
    assert s.enemies[0].awake is True
    s2 = _state(enemy_count=0)
    s2.pos, s2.facing = (1, 1), FACINGS.index((1, 0))
    s2.enemies = [Enemy(pos=(3, 3), kind=LURKER)]  # Manhattan 4, out of range
    s2.turn(1); s2.turn(1)
    assert s2.enemies[0].awake is False


def test_an_adjacent_enemy_strikes_every_tick_until_killed():
    s = _state(enemy_count=0, max_health=3)
    s.pos, s.facing = (3, 3), FACINGS.index((-1, 0))
    s.enemies = [Enemy(pos=(2, 3), awake=True)]
    s.turn(1)  # burns an action; parity means the enemy strikes on every 2nd
    s.turn(1)
    assert s.health == 2  # took a hit while ignoring it
    s.facing = FACINGS.index((-1, 0))
    s.attack()             # kills before the next strike lands
    assert s.enemies[0].alive is False
    s.turn(1)
    s.turn(1)
    assert s.health == 2   # no further damage


def test_enough_ignored_hits_end_the_arena():
    s = _state(enemy_count=0, max_health=2)
    s.pos, s.facing = (3, 3), 0
    s.enemies = [Enemy(pos=(2, 3), awake=True)]
    for _ in range(12):
        s.turn(1)
        if s.over:
            break
    assert s.outcome == "lose"


def test_walking_onto_a_treasure_banks_its_gold_once():
    s = _state(enemy_count=0)
    target = s.treasures[0].pos
    s.pos = target
    s.treasures[0].collected = False
    s._collect_here()
    assert s.treasures[0].collected is True
    assert s.gold_collected == 5
    s._collect_here()
    assert s.gold_collected == 5  # not double-counted


def test_actions_are_ignored_once_the_arena_is_over():
    s = _state(enemy_count=0)
    s.outcome = "win"
    before = s.pos
    s.step(1)
    s.turn(1)
    assert s.pos == before

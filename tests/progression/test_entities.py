"""
Tests for maze_game.progression.entities -- Pellet/Enemy spawning and
contact effects, and the Boss's phase alternation, movement, and combat.
"""

import math
import random

import pytest

from maze_game.constants import (
    PELLET_TIME_VALUE, PELLET_MIN_COUNT, ENEMY_TIME_PENALTY,
    BOSS_INTERVAL, BOSS_BASE_DAMAGE, LABYRINTH_TOTAL_MAZES,
    ENEMY_UNLOCK_MAZE, ENEMY_RAMP_MAZES, ENEMY_RAMP_START_MULTIPLIER,
    ENEMY_DENSITY, ENEMY_MAX_COUNT, C_PELLET, C_GOLD, C_ENEMY,
)
from maze_game.progression.entities.hazards import (
    Pellet, GoldPellet, Enemy, ENEMY_TYPES, spawn_pellets, spawn_enemies, enemy_density_ramp,
    spawn_gold_pellets, load_gold_total, save_gold_total,
)
from maze_game.progression.entities.boss import Boss, is_boss_maze, boss_encounter_index
from maze_game.progression.shop.perks import Build

# A small open room, no walls except the border -- every interior cell is
# a valid candidate for spawning.
OPEN_ROOM = [[1] * 7 for _ in range(7)]
for _y in range(1, 6):
    for _x in range(1, 6):
        OPEN_ROOM[_y][_x] = 0


class _FakeRun:
    """Minimal stand-in for LabyrinthRun -- just enough state for on_contact()."""

    def __init__(self, gold_path=None):
        self.time = _FakeTimeResource()
        self.build = Build()
        self.popups = []
        self.events = []
        self.gold = 0
        self.gold_path = gold_path

    def add_popup(self, pos, text, color):
        self.popups.append((pos, text, color))


class _FakeTimeResource:
    def __init__(self):
        self.amount = 10.0

    def add(self, amount):
        self.amount += amount

    def spend(self, amount):
        self.amount = max(0.0, self.amount - amount)


# ── Pellet ────────────────────────────────────────────────────────────────


def test_pellet_on_contact_adds_time_scaled_by_build_multiplier():
    run = _FakeRun()
    run.build.pellet_value_multiplier = 2.0
    pellet = Pellet((1, 1), value=4.0)
    pellet.on_contact(run)
    assert run.time.amount == pytest.approx(10.0 + 4.0 * 2.0)


def test_pellet_on_contact_adds_a_popup_with_the_scaled_amount():
    run = _FakeRun()
    run.build.pellet_value_multiplier = 2.0
    pellet = Pellet((1, 1), value=4.0)
    pellet.on_contact(run)
    assert len(run.popups) == 1
    pos, text, color = run.popups[0]
    assert pos == (1, 1)
    assert text == "+8.0s"
    assert color == C_PELLET


def test_pellet_on_contact_appends_the_pellet_sound_event():
    run = _FakeRun()
    Pellet((1, 1)).on_contact(run)
    assert run.events == ["pellet"]


# ── GoldPellet ────────────────────────────────────────────────────────────


def test_gold_pellet_on_contact_adds_to_the_gold_total(tmp_path):
    run = _FakeRun(gold_path=tmp_path / "gold.json")
    GoldPellet((1, 1), value=3).on_contact(run)
    assert run.gold == 3


def test_gold_pellet_on_contact_adds_a_popup_at_its_position(tmp_path):
    run = _FakeRun(gold_path=tmp_path / "gold.json")
    GoldPellet((1, 1), value=3).on_contact(run)
    assert len(run.popups) == 1
    pos, text, color = run.popups[0]
    assert pos == (1, 1)
    assert text == "+3g"
    assert color == C_GOLD


def test_gold_pellet_on_contact_appends_the_gold_sound_event(tmp_path):
    run = _FakeRun(gold_path=tmp_path / "gold.json")
    GoldPellet((1, 1)).on_contact(run)
    assert run.events == ["gold"]


def test_gold_pellet_on_contact_persists_the_new_total_to_disk(tmp_path):
    path = tmp_path / "gold.json"
    run = _FakeRun(gold_path=path)
    GoldPellet((1, 1), value=5).on_contact(run)
    assert load_gold_total(path) == 5


def test_spawn_gold_pellets_never_spawns_above_the_chance():
    rng = random.Random(1)
    result = spawn_gold_pellets(OPEN_ROOM, exclude=set(), chance=0.0, rng=rng)
    assert result == []


def test_spawn_gold_pellets_always_spawns_exactly_one_below_the_chance():
    rng = random.Random(1)
    result = spawn_gold_pellets(OPEN_ROOM, exclude=set(), chance=1.0, rng=rng)
    assert len(result) == 1
    assert isinstance(result[0], GoldPellet)


def test_spawn_gold_pellets_excludes_given_cells():
    rng = random.Random(1)
    exclude = {(x, y) for y in range(1, 6) for x in range(1, 6) if (x, y) != (2, 2)}
    result = spawn_gold_pellets(OPEN_ROOM, exclude=exclude, chance=1.0, rng=rng)
    assert len(result) == 1
    assert result[0].pos == (2, 2)


def test_load_gold_total_returns_zero_when_the_file_is_missing(tmp_path):
    assert load_gold_total(tmp_path / "does_not_exist.json") == 0


def test_load_gold_total_returns_zero_when_the_file_is_corrupt(tmp_path):
    path = tmp_path / "gold.json"
    path.write_text("not valid json{{{")
    assert load_gold_total(path) == 0


def test_save_and_load_gold_total_round_trips(tmp_path):
    path = tmp_path / "gold.json"
    save_gold_total(42, path)
    assert load_gold_total(path) == 42


# ── Enemy ─────────────────────────────────────────────────────────────────


def test_enemy_on_contact_spends_its_penalty():
    run = _FakeRun()
    enemy = Enemy((1, 1))
    enemy.on_contact(run)
    assert run.time.amount == pytest.approx(10.0 - ENEMY_TIME_PENALTY)


def test_enemy_on_contact_adds_a_popup_at_its_position():
    run = _FakeRun()
    enemy = Enemy((2, 3))
    enemy.on_contact(run)
    assert len(run.popups) == 1
    pos, text, color = run.popups[0]
    assert pos == (2, 3)
    assert text == f"-{ENEMY_TIME_PENALTY:.1f}s"
    assert color == C_ENEMY


def test_enemy_on_contact_appends_the_enemy_hit_sound_event():
    run = _FakeRun()
    Enemy((1, 1)).on_contact(run)
    assert run.events == ["enemy_hit"]


def test_enemy_types_registry_contains_the_base_type():
    assert Enemy in ENEMY_TYPES


# ── spawn_pellets / spawn_enemies ─────────────────────────────────────────


def test_spawn_pellets_excludes_given_cells():
    random.seed(1)
    exclude = {(1, 1), (5, 5)}
    pellets = spawn_pellets(OPEN_ROOM, exclude)
    assert all(p.pos not in exclude for p in pellets)


def test_spawn_pellets_respects_minimum_count():
    random.seed(2)
    pellets = spawn_pellets(OPEN_ROOM, exclude=set())
    assert len(pellets) >= PELLET_MIN_COUNT


def test_spawn_pellets_scale_with_room_size():
    random.seed(3)
    small_room = [[1] * 5 for _ in range(5)]
    for y in range(1, 4):
        for x in range(1, 4):
            small_room[y][x] = 0
    small_count = len(spawn_pellets(small_room, exclude=set()))
    large_count = len(spawn_pellets(OPEN_ROOM, exclude=set()))
    assert large_count >= small_count


def test_spawn_pellets_uses_the_configured_time_value():
    random.seed(4)
    pellets = spawn_pellets(OPEN_ROOM, exclude=set())
    assert all(p.value == PELLET_TIME_VALUE for p in pellets)


def test_spawn_enemies_excludes_given_cells():
    random.seed(5)
    exclude = {(1, 1), (5, 5)}
    enemies = spawn_enemies(OPEN_ROOM, exclude)
    assert all(e.pos not in exclude for e in enemies)


def test_spawn_pellets_and_spawn_enemies_can_be_composed_without_overlap():
    random.seed(6)
    exclude = {(1, 1), (5, 5)}
    pellets = spawn_pellets(OPEN_ROOM, exclude)
    exclude_for_enemies = exclude | {p.pos for p in pellets}
    enemies = spawn_enemies(OPEN_ROOM, exclude_for_enemies)
    pellet_positions = {p.pos for p in pellets}
    enemy_positions = {e.pos for e in enemies}
    assert pellet_positions.isdisjoint(enemy_positions)

def test_spawn_pellets_with_explicit_rng_is_deterministic():
    a = spawn_pellets(OPEN_ROOM, exclude=set(), rng=random.Random(11))
    b = spawn_pellets(OPEN_ROOM, exclude=set(), rng=random.Random(11))
    assert [p.pos for p in a] == [p.pos for p in b]


def test_spawn_enemies_with_explicit_rng_is_deterministic():
    a = spawn_enemies(OPEN_ROOM, exclude=set(), rng=random.Random(12))
    b = spawn_enemies(OPEN_ROOM, exclude=set(), rng=random.Random(12))
    assert [e.pos for e in a] == [e.pos for e in b]


def test_spawn_enemies_density_multiplier_scales_the_count():
    random.seed(13)
    full = spawn_enemies(OPEN_ROOM, exclude=set(), density_multiplier=1.0)
    random.seed(13)
    reduced = spawn_enemies(OPEN_ROOM, exclude=set(), density_multiplier=0.25)
    assert len(reduced) <= len(full)


# ── Enemy density ramp ──────────────────────────────────────────────────


def test_enemy_density_ramp_starts_at_the_configured_fraction_on_unlock():
    assert enemy_density_ramp(ENEMY_UNLOCK_MAZE) == pytest.approx(ENEMY_RAMP_START_MULTIPLIER)


def test_enemy_density_ramp_reaches_full_density_after_ramp_mazes():
    assert enemy_density_ramp(ENEMY_UNLOCK_MAZE + ENEMY_RAMP_MAZES) == pytest.approx(1.0)
    assert enemy_density_ramp(ENEMY_UNLOCK_MAZE + ENEMY_RAMP_MAZES + 50) == pytest.approx(1.0)  # never exceeds 1.0


def test_enemy_density_ramp_increases_monotonically():
    values = [enemy_density_ramp(ENEMY_UNLOCK_MAZE + i) for i in range(ENEMY_RAMP_MAZES + 1)]
    assert values == sorted(values)


def test_first_enemy_maze_spawns_noticeably_fewer_enemies_than_full_density():
    """The actual behaviour the ramp exists for: maze 11 should spawn far fewer enemies than the pre-ramp formula would."""
    random.seed(14)
    ramped = spawn_enemies(OPEN_ROOM, exclude=set(), density_multiplier=enemy_density_ramp(ENEMY_UNLOCK_MAZE))
    random.seed(14)
    unramped = spawn_enemies(OPEN_ROOM, exclude=set(), density_multiplier=1.0)
    assert len(ramped) < len(unramped)


# ── Boss ──────────────────────────────────────────────────────────────────


def test_is_boss_maze_only_true_on_the_interval():
    assert is_boss_maze(BOSS_INTERVAL) is True
    assert is_boss_maze(BOSS_INTERVAL * 2) is True
    assert is_boss_maze(BOSS_INTERVAL - 1) is False
    assert is_boss_maze(1) is False


def test_is_boss_maze_true_on_the_final_maze_even_off_interval():
    """LABYRINTH_TOTAL_MAZES(100) isn't a BOSS_INTERVAL(30) multiple, but the final maze is always a boss maze too."""
    assert LABYRINTH_TOTAL_MAZES % BOSS_INTERVAL != 0
    assert is_boss_maze(LABYRINTH_TOTAL_MAZES) is True


def test_boss_encounter_index_increments_per_interval():
    assert boss_encounter_index(BOSS_INTERVAL) == 0
    assert boss_encounter_index(BOSS_INTERVAL * 2) == 1
    assert boss_encounter_index(BOSS_INTERVAL * 3) == 2


def test_boss_encounter_index_final_maze_is_strictly_the_hardest():
    """
    The final maze is special-cased to be one step past interval math (which
    would otherwise tie its HP with the prior regular encounter) -- keeps
    "especially hard" true even though BOSS_INTERVAL=30 gives fewer total
    encounters (4) than the old BOSS_INTERVAL=20 scheme (5) did.
    """
    last_regular_index = boss_encounter_index((LABYRINTH_TOTAL_MAZES // BOSS_INTERVAL) * BOSS_INTERVAL)
    assert boss_encounter_index(LABYRINTH_TOTAL_MAZES) > last_regular_index


def test_boss_starts_idle_at_move_count_zero():
    boss = Boss((3, 3), hp=5)
    assert boss.move_count == 0
    assert boss.phase == "idle"
    assert boss.defeated is False


def test_boss_phase_alternates_idle_active_each_advance():
    boss = Boss((3, 3), hp=5)
    phases = []
    for _ in range(6):
        boss.advance(player_pos=(1, 1), grid=OPEN_ROOM)
        phases.append(boss.phase)
    assert phases == ["idle", "active", "idle", "active", "idle", "active"]


def test_boss_only_moves_on_active_turns():
    boss = Boss((5, 5), hp=5)
    start_pos = boss.pos
    boss.advance(player_pos=(1, 1), grid=OPEN_ROOM)  # idle turn
    assert boss.pos == start_pos  # didn't move

    boss.advance(player_pos=(1, 1), grid=OPEN_ROOM)  # active turn
    assert boss.pos != start_pos  # stepped toward the player


def test_boss_steps_one_cell_closer_to_the_player_each_active_turn():
    boss = Boss((5, 5), hp=5)
    boss.advance(player_pos=(1, 1), grid=OPEN_ROOM)  # idle, no move
    before_dist = abs(boss.pos[0] - 1) + abs(boss.pos[1] - 1)
    boss.advance(player_pos=(1, 1), grid=OPEN_ROOM)  # active, moves one step
    after_dist = abs(boss.pos[0] - 1) + abs(boss.pos[1] - 1)
    assert after_dist == before_dist - 1


# A boss maze can place the boss inside a pocket only reachable through a
# teleporter (see augments/teleporters.py) -- (5, 1) has zero open grid
# neighbours, only the extra_edges link to (1, 1) below.
BOSS_POCKET_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 1, 1, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]


def test_boss_advance_without_extra_edges_cannot_reach_a_teleporter_only_pocket():
    """Confirms the pocket really is unreachable by plain grid adjacency -- the failure mode extra_edges fixes."""
    boss = Boss((5, 1), hp=5)
    boss.move_count = 1  # force the active phase, which is what triggers the pathing
    with pytest.raises(KeyError):
        boss.advance(player_pos=(1, 1), grid=BOSS_POCKET_GRID)


def test_boss_advance_uses_extra_edges_to_escape_a_teleporter_only_pocket():
    """
    Regression test: advance() used to call shortest_path() with no
    extra_edges at all, so a boss placed in a teleporter-only pocket crashed
    with a KeyError (shortest_path() can't reach a goal with no path to it)
    the instant it hit an active turn, instead of stepping through the link.
    """
    boss = Boss((5, 1), hp=5)
    boss.move_count = 1  # force the active phase
    tmap = {(1, 1): (5, 1), (5, 1): (1, 1)}
    boss.advance(player_pos=(1, 1), grid=BOSS_POCKET_GRID, extra_edges=tmap)
    assert boss.pos == (1, 1)  # one hop through the teleporter link lands directly on the player's cell


def test_boss_on_contact_damages_hp_while_idle():
    run = _FakeRun()
    run.build.strength_multiplier = 2.0
    boss = Boss((3, 3), hp=5)
    boss.phase = "idle"
    boss.on_contact(run)
    assert boss.hp == pytest.approx(5 - BOSS_BASE_DAMAGE * 2.0)
    assert run.time.amount == pytest.approx(10.0)  # no time cost while idle
    assert run.events == ["boss_damage"]


def test_boss_on_contact_costs_time_while_active():
    run = _FakeRun()
    boss = Boss((3, 3), hp=5)
    boss.phase = "active"
    boss.on_contact(run)
    assert boss.hp == 5  # no damage while active
    assert run.time.amount == pytest.approx(10.0 - ENEMY_TIME_PENALTY)
    assert run.events == ["enemy_hit"]  # shares apply_time_penalty()'s event with a regular enemy hit


def test_boss_defeated_when_hp_at_or_below_zero():
    boss = Boss((3, 3), hp=1)
    boss.phase = "idle"
    boss.on_contact(_FakeRun())
    assert boss.defeated is True

"""
Tests for maze_game.progression.entities -- Pellet/GoldPellet/Hazard
spawning and contact effects.
"""

import math
import random

import pytest

from maze_game.constants import (
    PELLET_TIME_VALUE, PELLET_MIN_COUNT, HAZARD_TIME_PENALTY,
    HAZARD_UNLOCK_MAZE, HAZARD_RAMP_MAZES, HAZARD_RAMP_START_MULTIPLIER,
    HAZARD_DENSITY, HAZARD_MAX_COUNT, C_PELLET, C_GOLD, C_HAZARD, C_SHIELD,
)
from maze_game.progression.entities.hazards import (
    Pellet, GoldPellet, Hazard, HAZARD_TYPES, spawn_pellets, spawn_hazards, hazard_density_ramp,
    spawn_gold_pellets, load_gold_total, save_gold_total,
)
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
        self.shield_charges_remaining = 0

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


# ── Hazard ─────────────────────────────────────────────────────────────────


def test_hazard_on_contact_spends_its_penalty():
    run = _FakeRun()
    hazard = Hazard((1, 1))
    hazard.on_contact(run)
    assert run.time.amount == pytest.approx(10.0 - HAZARD_TIME_PENALTY)


def test_hazard_on_contact_adds_a_popup_at_its_position():
    run = _FakeRun()
    hazard = Hazard((2, 3))
    hazard.on_contact(run)
    assert len(run.popups) == 1
    pos, text, color = run.popups[0]
    assert pos == (2, 3)
    assert text == f"-{HAZARD_TIME_PENALTY:.1f}s"
    assert color == C_HAZARD


def test_hazard_on_contact_scales_the_penalty_by_hazard_resistance():
    run = _FakeRun()
    run.build.hazard_resistance_multiplier = 0.5
    hazard = Hazard((1, 1))
    hazard.on_contact(run)
    assert run.time.amount == pytest.approx(10.0 - HAZARD_TIME_PENALTY * 0.5)


def test_hazard_on_contact_appends_the_hazard_hit_sound_event():
    run = _FakeRun()
    Hazard((1, 1)).on_contact(run)
    assert run.events == ["hazard_hit"]


def test_hazard_on_contact_consumes_a_shield_charge_and_blocks_the_penalty():
    run = _FakeRun()
    run.shield_charges_remaining = 1
    hazard = Hazard((2, 3))
    hazard.on_contact(run)
    assert run.time.amount == pytest.approx(10.0)  # fully blocked, no penalty
    assert run.shield_charges_remaining == 0
    assert run.events == ["shield_block"]
    pos, text, color = run.popups[0]
    assert pos == (2, 3)
    assert text == "Shielded!"
    assert color == C_SHIELD


def test_hazard_on_contact_only_blocks_up_to_the_remaining_charges():
    run = _FakeRun()
    run.shield_charges_remaining = 1
    hazard = Hazard((1, 1))
    hazard.on_contact(run)  # consumes the only charge
    hazard.on_contact(run)  # no charges left -- normal penalty applies
    assert run.time.amount == pytest.approx(10.0 - HAZARD_TIME_PENALTY)
    assert run.events == ["shield_block", "hazard_hit"]


def test_hazard_types_registry_contains_the_base_type():
    assert Hazard in HAZARD_TYPES


# ── spawn_pellets / spawn_hazards ─────────────────────────────────────────


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


def test_spawn_hazards_excludes_given_cells():
    random.seed(5)
    exclude = {(1, 1), (5, 5)}
    hazards = spawn_hazards(OPEN_ROOM, exclude)
    assert all(e.pos not in exclude for e in hazards)


def test_spawn_pellets_and_spawn_hazards_can_be_composed_without_overlap():
    random.seed(6)
    exclude = {(1, 1), (5, 5)}
    pellets = spawn_pellets(OPEN_ROOM, exclude)
    exclude_for_hazards = exclude | {p.pos for p in pellets}
    hazards = spawn_hazards(OPEN_ROOM, exclude_for_hazards)
    pellet_positions = {p.pos for p in pellets}
    hazard_positions = {e.pos for e in hazards}
    assert pellet_positions.isdisjoint(hazard_positions)

def test_spawn_pellets_with_explicit_rng_is_deterministic():
    a = spawn_pellets(OPEN_ROOM, exclude=set(), rng=random.Random(11))
    b = spawn_pellets(OPEN_ROOM, exclude=set(), rng=random.Random(11))
    assert [p.pos for p in a] == [p.pos for p in b]


def test_spawn_hazards_with_explicit_rng_is_deterministic():
    a = spawn_hazards(OPEN_ROOM, exclude=set(), rng=random.Random(12))
    b = spawn_hazards(OPEN_ROOM, exclude=set(), rng=random.Random(12))
    assert [e.pos for e in a] == [e.pos for e in b]


def test_spawn_hazards_density_multiplier_scales_the_count():
    random.seed(13)
    full = spawn_hazards(OPEN_ROOM, exclude=set(), density_multiplier=1.0)
    random.seed(13)
    reduced = spawn_hazards(OPEN_ROOM, exclude=set(), density_multiplier=0.25)
    assert len(reduced) <= len(full)


# ── Hazard density ramp ──────────────────────────────────────────────────


def test_hazard_density_ramp_starts_at_the_configured_fraction_on_unlock():
    assert hazard_density_ramp(HAZARD_UNLOCK_MAZE) == pytest.approx(HAZARD_RAMP_START_MULTIPLIER)


def test_hazard_density_ramp_reaches_full_density_after_ramp_mazes():
    assert hazard_density_ramp(HAZARD_UNLOCK_MAZE + HAZARD_RAMP_MAZES) == pytest.approx(1.0)
    assert hazard_density_ramp(HAZARD_UNLOCK_MAZE + HAZARD_RAMP_MAZES + 50) == pytest.approx(1.0)  # never exceeds 1.0


def test_hazard_density_ramp_increases_monotonically():
    values = [hazard_density_ramp(HAZARD_UNLOCK_MAZE + i) for i in range(HAZARD_RAMP_MAZES + 1)]
    assert values == sorted(values)


def test_first_hazard_maze_spawns_noticeably_fewer_hazards_than_full_density():
    """The actual behaviour the ramp exists for: maze 11 should spawn far fewer hazards than the pre-ramp formula would."""
    random.seed(14)
    ramped = spawn_hazards(OPEN_ROOM, exclude=set(), density_multiplier=hazard_density_ramp(HAZARD_UNLOCK_MAZE))
    random.seed(14)
    unramped = spawn_hazards(OPEN_ROOM, exclude=set(), density_multiplier=1.0)
    assert len(ramped) < len(unramped)


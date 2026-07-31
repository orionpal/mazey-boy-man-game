"""
Tests for maze_game.progression.augments -- AugmentBuild (level tracking),
run_pipeline (composition/ordering), and offer_augment_cards (cap-aware
sampling). Uses stub augments and monkeypatches the module's ALL_AUGMENTS
registry so these tests stay independent of however many real augments
(teleporters.py and later ones) end up registered.
"""

import random

import pytest

import maze_game.progression.augments as augments_module
from maze_game.progression.augments import Augment, AugmentBuild, run_pipeline, offer_augment_cards
from maze_game.constants import MAX_ACTIVE_AUGMENTS


class _StubAugment(Augment):
    def __init__(self, id_, call_log=None):
        self.id = id_
        self.name = id_
        self.description = f"stub {id_}"
        self._call_log = call_log

    def apply(self, ctx):
        if self._call_log is not None:
            self._call_log.append(self.id)


# ── AugmentBuild ──────────────────────────────────────────────────────────


def test_augment_build_starts_with_no_picks():
    build = AugmentBuild()
    assert build.picks == {}
    assert build.active_ids == []
    assert build.level_of("teleporters") == 0


def test_acquiring_an_augment_increments_its_level():
    build = AugmentBuild()
    a = _StubAugment("teleporters")
    build.acquire(a)
    assert build.level_of("teleporters") == 1
    build.acquire(a)
    assert build.level_of("teleporters") == 2
    assert build.active_ids == ["teleporters"]


# ── run_pipeline ──────────────────────────────────────────────────────────


def test_run_pipeline_only_applies_active_augments(monkeypatch):
    call_log = []
    a = _StubAugment("a", call_log)
    b = _StubAugment("b", call_log)
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", [a, b])

    build = AugmentBuild()
    build.acquire(b)  # only b is active

    grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    ctx = run_pipeline(grid, 3, 3, (1, 1), (1, 1), build, random.Random(1))

    assert call_log == ["b"]
    assert ctx.grid is grid


def test_run_pipeline_applies_in_registry_order_not_pick_order(monkeypatch):
    call_log = []
    a = _StubAugment("a", call_log)
    b = _StubAugment("b", call_log)
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", [a, b])

    build = AugmentBuild()
    build.acquire(b)  # picked first...
    build.acquire(a)  # ...but a is still first in registry order

    grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    run_pipeline(grid, 3, 3, (1, 1), (1, 1), build, random.Random(1))

    assert call_log == ["a", "b"]


def test_run_pipeline_sets_level_before_each_apply(monkeypatch):
    seen_levels = []

    class _LevelRecordingAugment(Augment):
        id = "leveled"
        name = "leveled"
        description = ""

        def apply(self, ctx):
            seen_levels.append(ctx.level)

    aug = _LevelRecordingAugment()
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", [aug])
    build = AugmentBuild()
    build.acquire(aug)
    build.acquire(aug)
    build.acquire(aug)

    grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    run_pipeline(grid, 3, 3, (1, 1), (1, 1), build, random.Random(1))

    assert seen_levels == [3]


# ── offer_augment_cards ──────────────────────────────────────────────────


def test_offer_favors_new_augments_when_below_cap(monkeypatch):
    stubs = [_StubAugment(f"aug{i}") for i in range(5)]
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", stubs)
    build = AugmentBuild()
    build.acquire(stubs[0])  # 1 active, well below MAX_ACTIVE_AUGMENTS

    offered = offer_augment_cards(build, rng=random.Random(1))
    assert len(offered) == 3
    assert all(card.id != stubs[0].id for card in offered)


def test_offer_restricted_to_active_once_at_cap(monkeypatch):
    stubs = [_StubAugment(f"aug{i}") for i in range(6)]
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", stubs)
    build = AugmentBuild()
    for a in stubs[:MAX_ACTIVE_AUGMENTS]:
        build.acquire(a)

    offered = offer_augment_cards(build, rng=random.Random(2))
    active_ids = {a.id for a in stubs[:MAX_ACTIVE_AUGMENTS]}
    assert all(card.id in active_ids for card in offered)


def test_offer_degrades_gracefully_when_pool_smaller_than_offered_count(monkeypatch):
    stubs = [_StubAugment("only_one")]
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", stubs)
    build = AugmentBuild()

    offered = offer_augment_cards(build, rng=random.Random(3))
    assert offered == stubs


def test_offer_tops_up_with_active_when_new_pool_is_short(monkeypatch):
    stubs = [_StubAugment(f"aug{i}") for i in range(2)]
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", stubs)
    build = AugmentBuild()
    build.acquire(stubs[0])  # 1 active, 1 not-yet-active -- below cap but short of a 3-card offer

    offered = offer_augment_cards(build, rng=random.Random(4))
    assert len(offered) == 2  # can't offer more cards than augments exist at all
    assert {c.id for c in offered} == {stubs[0].id, stubs[1].id}


def test_offer_with_explicit_rng_is_deterministic(monkeypatch):
    stubs = [_StubAugment(f"aug{i}") for i in range(5)]
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", stubs)
    build = AugmentBuild()

    a = offer_augment_cards(build, rng=random.Random(77))
    b = offer_augment_cards(build, rng=random.Random(77))
    assert [c.id for c in a] == [c.id for c in b]

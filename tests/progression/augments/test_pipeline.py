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


# ── AugmentBuild pellet-economy multipliers ────────────────────────────────


def test_pellet_multipliers_are_neutral_with_no_augments_active():
    build = AugmentBuild()
    assert build.pellet_frequency_multiplier == pytest.approx(1.0)
    assert build.pellet_value_multiplier == pytest.approx(1.0)


def test_pellet_multipliers_read_the_active_augments_own_values(monkeypatch):
    a = _StubAugment("a")
    a.pellet_frequency_multiplier = 1.5
    a.pellet_value_multiplier = 1.2
    monkeypatch.setattr(augments_module, "AUGMENTS_BY_ID", {"a": a})

    build = AugmentBuild()
    build.acquire(a)
    assert build.pellet_frequency_multiplier == pytest.approx(1.5)
    assert build.pellet_value_multiplier == pytest.approx(1.2)


def test_pellet_multipliers_combine_multiplicatively_across_active_augments(monkeypatch):
    a = _StubAugment("a")
    a.pellet_frequency_multiplier = 1.5
    a.pellet_value_multiplier = 1.2
    b = _StubAugment("b")
    b.pellet_frequency_multiplier = 0.7
    b.pellet_value_multiplier = 1.1
    monkeypatch.setattr(augments_module, "AUGMENTS_BY_ID", {"a": a, "b": b})

    build = AugmentBuild()
    build.acquire(a)
    build.acquire(b)
    assert build.pellet_frequency_multiplier == pytest.approx(1.5 * 0.7)
    assert build.pellet_value_multiplier == pytest.approx(1.2 * 1.1)


def test_pellet_multipliers_are_unaffected_by_augment_level(monkeypatch):
    """Flat per augment *type*, not scaled by pick count -- level already scales the augment's own mechanic separately."""
    a = _StubAugment("a")
    a.pellet_frequency_multiplier = 1.5
    monkeypatch.setattr(augments_module, "AUGMENTS_BY_ID", {"a": a})

    build = AugmentBuild()
    build.acquire(a)
    build.acquire(a)
    build.acquire(a)
    assert build.level_of("a") == 3
    assert build.pellet_frequency_multiplier == pytest.approx(1.5)  # not 1.5**3


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


# ── ctx.frontier / _finalize_goal (composability, see docs/progression.md) ──


def test_frontier_seeded_at_start(monkeypatch):
    seen_frontier = []

    class _FrontierRecordingAugment(Augment):
        id = "recorder"
        name = "recorder"
        description = ""

        def apply(self, ctx):
            seen_frontier.append(ctx.frontier)

    aug = _FrontierRecordingAugment()
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", [aug])
    build = AugmentBuild()
    build.acquire(aug)

    grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    run_pipeline(grid, 3, 3, (1, 1), (1, 1), build, random.Random(1))

    assert seen_frontier == [(1, 1)]


def test_frontier_threads_from_one_augment_to_the_next(monkeypatch):
    seen_frontier = []

    class _FirstAugment(Augment):
        id = "first"
        name = "first"
        description = ""

        def apply(self, ctx):
            ctx.frontier = (9, 9)  # pretend this augment placed mandatory content ending here

    class _SecondAugment(Augment):
        id = "second"
        name = "second"
        description = ""

        def apply(self, ctx):
            seen_frontier.append(ctx.frontier)

    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", [_FirstAugment(), _SecondAugment()])
    build = AugmentBuild()
    build.acquire(_FirstAugment())
    build.acquire(_SecondAugment())

    grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    run_pipeline(grid, 3, 3, (1, 1), (1, 1), build, random.Random(1))

    # The second augment must see the FIRST augment's advanced frontier,
    # not ctx.start -- this is the exact mechanism that fixes multiple
    # active augments each independently (and silently) overwriting the
    # goal instead of nesting behind each other's mandatory content.
    assert seen_frontier == [(9, 9)]


def test_finalize_goal_places_the_real_farthest_cell_even_when_nothing_is_mandatory(monkeypatch):
    class _NoopAugment(Augment):
        id = "noop"
        name = "noop"
        description = ""

        def apply(self, ctx):
            pass  # never touches ctx.frontier -- no mandatory content placed

    aug = _NoopAugment()
    monkeypatch.setattr(augments_module, "ALL_AUGMENTS", [aug])
    build = AugmentBuild()
    build.acquire(aug)

    # A straight corridor: start at one end, only the far end is stoppable
    # (a dead end, 1 open neighbour) -- every cell in between has exactly 2.
    grid = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    ctx = run_pipeline(grid, 7, 3, (1, 1), (1, 1), build, random.Random(1))

    # _finalize_goal() now runs unconditionally (no early-return when
    # nothing advanced ctx.frontier) -- with no mandatory content,
    # ctx.extra["mandatory_gated_cells"] is empty, so this degrades to
    # plain farthest-stoppable-cell placement from ctx.start, same metric
    # the no-augment default already used, not a special-cased no-op.
    assert ctx.goal == (5, 1)


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


# ── Real augments' pellet-economy declarations ────────────────────────────


def test_every_real_augment_declares_a_pellet_economy_trade_off():
    """Sanity check against typos/copy-paste mistakes wiring each augment's constant -- every registered augment should have *some* opinion here, even if neutral (1.0), not silently fall through to the base class default by accident."""
    from maze_game.progression.augments import ALL_AUGMENTS

    for augment in ALL_AUGMENTS:
        assert isinstance(augment.pellet_frequency_multiplier, float)
        assert isinstance(augment.pellet_value_multiplier, float)
        assert augment.pellet_frequency_multiplier > 0
        assert augment.pellet_value_multiplier > 0


def test_fog_of_war_and_twin_goals_pull_in_opposite_directions():
    """The two augments the trade-off design was explicitly motivated by: fog of war (much harder -- boosts pellets) and twin goals (a net advantage -- reduces frequency)."""
    from maze_game.progression.augments import AUGMENTS_BY_ID

    fog = AUGMENTS_BY_ID["fog_of_war"]
    twin_goals = AUGMENTS_BY_ID["twin_goals"]
    assert fog.pellet_frequency_multiplier > 1.0
    assert fog.pellet_value_multiplier > 1.0
    assert twin_goals.pellet_frequency_multiplier < 1.0

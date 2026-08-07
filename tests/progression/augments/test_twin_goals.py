"""
Tests for maze_game.progression.augments.twin_goals -- TwinGoalsAugment's
near-no-op apply(), its pipeline wiring (run_pipeline() resolving
ctx.extra["secondary_goal"] after _finalize_goal()), and -- most
importantly -- the mutual-exclusion guard against Doors/Teleporters in
offer_augment_cards() (see augments/__init__.py's
_MUTUALLY_EXCLUSIVE_AUGMENT_IDS and _resolve_secondary_goal()'s docstring
for why). Uses the real ALL_AUGMENTS registry, not stubs -- the exclusion
table is keyed to real augment ids, so a stubbed registry can't exercise it.
"""

import random

from maze_game.progression.augments import (
    AugmentBuild, run_pipeline, offer_augment_cards, AUGMENTS_BY_ID,
)
from maze_game.progression.augments.twin_goals import TwinGoalsAugment
from maze_game.progression.augments.gating.doors import DoorsAugment
from maze_game.progression.augments.gating.teleporters import TeleportersAugment
from maze_game.maze import generate_maze, farthest_reachable_cell

START = (1, 1)


def _big_grid(seed=1):
    rng = random.Random(seed)
    grid = generate_maze(21, 21, rng=rng)
    goal = farthest_reachable_cell(grid, START)
    return grid, goal


def test_twin_goals_apply_only_sets_the_activation_flag():
    grid, goal = _big_grid()
    before = [row[:] for row in grid]
    build = AugmentBuild()
    build.acquire(TwinGoalsAugment())
    ctx = run_pipeline(grid, 21, 21, START, goal, build, random.Random(2))
    assert ctx.grid == before  # no generation-time mutation of its own


def test_twin_goals_is_registered():
    assert "twin_goals" in AUGMENTS_BY_ID
    assert isinstance(AUGMENTS_BY_ID["twin_goals"], TwinGoalsAugment)


def test_run_pipeline_populates_secondary_goal_when_twin_goals_is_active():
    grid, goal = _big_grid(seed=5)
    build = AugmentBuild()
    build.acquire(TwinGoalsAugment())
    ctx = run_pipeline(grid, 21, 21, START, goal, build, random.Random(5))
    assert "secondary_goal" in ctx.extra
    secondary = ctx.extra["secondary_goal"]
    assert secondary is not None
    assert secondary != ctx.goal
    assert secondary != START


def test_run_pipeline_does_not_touch_secondary_goal_when_inactive():
    grid, goal = _big_grid(seed=6)
    build = AugmentBuild()  # nothing acquired
    ctx = run_pipeline(grid, 21, 21, START, goal, build, random.Random(6))
    assert "secondary_goal" not in ctx.extra


def test_offer_never_offers_twin_goals_alongside_doors():
    build = AugmentBuild()
    build.acquire(DoorsAugment())
    offered = offer_augment_cards(build, rng=random.Random(1), count=100)
    assert "twin_goals" not in {a.id for a in offered}


def test_offer_never_offers_twin_goals_alongside_teleporters():
    build = AugmentBuild()
    build.acquire(TeleportersAugment())
    offered = offer_augment_cards(build, rng=random.Random(1), count=100)
    assert "twin_goals" not in {a.id for a in offered}


def test_offer_never_offers_doors_or_teleporters_alongside_twin_goals():
    build = AugmentBuild()
    build.acquire(TwinGoalsAugment())
    offered = offer_augment_cards(build, rng=random.Random(1), count=100)
    offered_ids = {a.id for a in offered}
    assert "doors" not in offered_ids
    assert "teleporters" not in offered_ids


def test_offer_still_allows_leveling_up_an_already_active_incompatible_pair():
    """The exclusion only blocks *new* incompatible picks -- re-offering an already-active augment (to level it up) is always fine."""
    build = AugmentBuild()
    build.acquire(DoorsAugment())
    offered = offer_augment_cards(build, rng=random.Random(1), count=100)
    assert "doors" in {a.id for a in offered}

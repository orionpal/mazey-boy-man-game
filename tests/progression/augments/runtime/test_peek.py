"""
Tests for maze_game.progression.augments.runtime.peek -- PeekAugment's
no-op apply() plus peek_alpha(), the pure time-to-alpha ramp function.
Runtime wiring (reading augment_build.level_of(PEEK_ID) to decide whether
to fade or snap opaque) lives in progression/app.py::_run_pause_loop() and
isn't pygame-loop-tested here -- see that function's docstring.
"""

import pytest

from maze_game.constants import PEEK_FADE_DURATION_SECONDS
from maze_game.progression.augments import AugmentContext
from maze_game.progression.augments.runtime.peek import PeekAugment, peek_alpha


def test_peek_augment_apply_is_a_no_op():
    ctx = AugmentContext(grid=[[0]], cols=1, rows=1, start=(0, 0), goal=(0, 0), rng=None)
    before = [row[:] for row in ctx.grid]
    PeekAugment().apply(ctx)
    assert ctx.grid == before
    assert ctx.extra == {}


def test_peek_is_registered():
    from maze_game.progression.augments import AUGMENTS_BY_ID
    assert "peek" in AUGMENTS_BY_ID
    assert isinstance(AUGMENTS_BY_ID["peek"], PeekAugment)


def test_peek_alpha_starts_fully_transparent():
    assert peek_alpha(0.0) == 0


def test_peek_alpha_is_fully_opaque_at_the_fade_duration():
    assert peek_alpha(PEEK_FADE_DURATION_SECONDS) == 255


def test_peek_alpha_clamps_at_255_beyond_the_fade_duration():
    assert peek_alpha(PEEK_FADE_DURATION_SECONDS + 100) == 255


def test_peek_alpha_never_goes_negative_for_negative_elapsed():
    assert peek_alpha(-1.0) == 0


def test_peek_alpha_increases_monotonically():
    steps = 20
    values = [peek_alpha(PEEK_FADE_DURATION_SECONDS * i / steps) for i in range(steps + 1)]
    assert values == sorted(values)

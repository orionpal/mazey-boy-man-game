"""
Tests for maze_game.progression.renderer -- Layout's window/sidebar/perk-card
sizing math, the text-wrapping helper perk cards/tooltips rely on to avoid
overflowing their rects, the zip-animation interpolation helper, and (via
a real off-screen Surface + Renderer) pressure pad marker drawing, the one
part of this module where pixel-level inspection is actually the most
direct way to verify the behavior. Everything else here is pure geometry
(pygame.Rect) and font metrics, no display needed.
"""

import time

import pygame
import pytest

from maze_game.progression.renderer import (
    Layout, MAZE_AREA_SIZE, Renderer, _wrap_text,
    animated_player_position, animated_maze_rotation_angle,
)
from maze_game.progression.run import LabyrinthRun, TeleportAnimation, RotationAnimation
from maze_game.progression.augments.runtime.rotation import RotatingMazeAugment
from maze_game.progression.augments.shifting_room import PressurePad
from maze_game.progression.shop.perks import ALL_PERKS
from maze_game.progression.augments import ALL_AUGMENTS
from maze_game.constants import (
    SIDEBAR_W, HUD_HEIGHT, ZIP_ANIMATION_DURATION_SECONDS, ROTATE_ANIMATION_DURATION_SECONDS,
    C_BG, C_PRESSURE_PADS,
)


def test_window_size_is_static_regardless_of_maze_dimensions():
    small = Layout(cols=9, rows=9)
    large = Layout(cols=41, rows=41)
    assert small.window_w == large.window_w == SIDEBAR_W + MAZE_AREA_SIZE + SIDEBAR_W
    assert small.window_h == large.window_h == MAZE_AREA_SIZE + HUD_HEIGHT


def test_right_legend_sidebar_spans_the_full_window_height():
    layout = Layout(cols=21, rows=21)
    assert layout.right.height == layout.window_h
    assert layout.right.width == SIDEBAR_W
    assert layout.right.x == SIDEBAR_W + MAZE_AREA_SIZE


def test_cell_size_shrinks_as_maze_dimensions_grow():
    small = Layout(cols=9, rows=9)
    large = Layout(cols=41, rows=41)
    assert large.cell < small.cell
    assert large.cell >= 1


def test_maze_pixel_size_fits_within_the_fixed_area_at_any_dimension():
    for cols in (9, 21, 41):
        layout = Layout(cols=cols, rows=cols)
        assert layout.maze_w <= MAZE_AREA_SIZE
        assert layout.maze_h <= MAZE_AREA_SIZE


def test_left_sidebar_spans_the_full_window_height():
    layout = Layout(cols=21, rows=21)
    assert layout.left.height == layout.window_h
    assert layout.left.width == SIDEBAR_W


def test_maze_origin_is_offset_by_the_sidebar_width():
    layout = Layout(cols=21, rows=21)
    assert layout.maze_origin == (SIDEBAR_W, 0)


def test_hud_sits_below_the_maze_area_and_fits_the_window():
    layout = Layout(cols=21, rows=21)
    assert layout.hud.y == MAZE_AREA_SIZE
    assert layout.hud.bottom == layout.window_h


def test_there_are_exactly_three_perk_cards_inside_the_maze_area():
    layout = Layout(cols=21, rows=21)
    assert len(layout.cards) == 3
    for card in layout.cards:
        assert card.left >= layout.maze_origin[0]
        assert card.top >= layout.maze_origin[1]
        assert card.right <= layout.maze_origin[0] + MAZE_AREA_SIZE
        assert card.bottom <= MAZE_AREA_SIZE


def test_perk_cards_do_not_overlap():
    layout = Layout(cols=21, rows=21)
    for a, b in zip(layout.cards, layout.cards[1:]):
        assert a.right <= b.left


def test_perk_card_geometry_is_independent_of_maze_dimensions():
    """Cards live in the fixed viewport, not the (shrinking) maze pixel size."""
    small = Layout(cols=9, rows=9)
    large = Layout(cols=41, rows=41)
    assert small.cards == large.cards


def test_build_squares_has_one_slot_per_perk():
    layout = Layout(cols=21, rows=21)
    assert len(layout.build_squares) == len(ALL_PERKS)


def test_build_squares_are_within_the_left_sidebar():
    layout = Layout(cols=21, rows=21)
    for square in layout.build_squares:
        # The whole square, not just its top-left corner -- a square whose
        # origin is inside the sidebar but that extends past its right
        # edge would still pass a topleft-only check while visibly
        # clipping off-screen.
        assert layout.left.contains(square)


def test_build_squares_wrap_to_a_new_row_past_the_per_row_limit():
    from maze_game.progression.renderer import BUILD_SQUARES_PER_ROW, BUILD_SQUARES_Y

    layout = Layout(cols=21, rows=21)
    assert len(ALL_PERKS) > BUILD_SQUARES_PER_ROW  # otherwise this test can't exercise wrapping at all
    first_row = layout.build_squares[:BUILD_SQUARES_PER_ROW]
    second_row = layout.build_squares[BUILD_SQUARES_PER_ROW:]
    assert all(sq.y == BUILD_SQUARES_Y for sq in first_row)
    assert all(sq.y > BUILD_SQUARES_Y for sq in second_row)  # wrapped to a lower row
    assert len({sq.y for sq in second_row}) == 1  # every square in the second row shares one y


def test_augments_section_shifts_down_to_clear_wrapped_perk_squares():
    layout = Layout(cols=21, rows=21)
    perk_squares_bottom = max(sq.bottom for sq in layout.build_squares)
    assert layout.augments_title_y > perk_squares_bottom
    assert layout.augments_subtitle_y > layout.augments_title_y
    assert layout.augment_squares[0].y > layout.augments_subtitle_y


# ── _wrap_text ────────────────────────────────────────────────────────────


def test_wrap_text_keeps_every_line_within_max_width():
    pygame.font.init()
    font = pygame.font.SysFont("monospace", 14)
    text = "+20% pellet spawn frequency in future mazes."
    lines = _wrap_text(font, text, max_width=100)
    assert len(lines) > 1
    for line in lines:
        assert font.size(line)[0] <= 100


def test_wrap_text_preserves_all_words():
    pygame.font.init()
    font = pygame.font.SysFont("monospace", 14)
    text = "a short perk description here"
    lines = _wrap_text(font, text, max_width=200)
    assert " ".join(lines).split(" ") == text.split(" ")


def test_wrap_text_fits_a_perk_card_at_the_smallest_maze_size():
    """Regression test: card text used to overflow its rect at 9x9 (round 1-5)."""
    pygame.font.init()
    font = pygame.font.SysFont("monospace", 14)
    layout = Layout(cols=9, rows=9)
    card_w = layout.cards[0].width
    for perk in ALL_PERKS:
        lines = _wrap_text(font, perk.description, card_w - 24)
        for line in lines:
            assert font.size(line)[0] <= card_w - 24


def test_wrap_text_fits_every_card_name():
    """
    Regression test: card names (rendered in the bigger, bold font) used to
    be blitted unwrapped, so "Teleporting Squares" overflowed its card and
    bled into the next one -- _draw_break_cards() now wraps names the same
    way it already wrapped descriptions.
    """
    pygame.font.init()
    font = pygame.font.SysFont("monospace", 20, bold=True)
    layout = Layout(cols=9, rows=9)
    card_w = layout.cards[0].width
    for card in list(ALL_PERKS) + list(ALL_AUGMENTS):
        lines = _wrap_text(font, card.name, card_w - 24)
        for line in lines:
            assert font.size(line)[0] <= card_w - 24


# ── animated_player_position (zip animation) ───────────────────────────────


class _StubRun:
    """Just enough of LabyrinthRun's shape for animated_player_position()."""

    def __init__(self, player, teleport_animation=None):
        self.player = player
        self.teleport_animation = teleport_animation


def test_animated_player_position_is_just_player_pos_with_no_animation():
    run = _StubRun(player=(5, 5))
    assert animated_player_position(run, now=100.0) == (5, 5)


def test_animated_player_position_interpolates_partway_through_the_window():
    anim = TeleportAnimation(from_cell=(2, 1), to_cell=(8, 1), started_at=100.0)
    run = _StubRun(player=(8, 1), teleport_animation=anim)
    halfway = 100.0 + ZIP_ANIMATION_DURATION_SECONDS / 2
    x, y = animated_player_position(run, now=halfway)
    assert x == pytest.approx(5.0)  # halfway between 2 and 8
    assert y == pytest.approx(1.0)


def test_animated_player_position_falls_back_to_player_pos_once_expired():
    anim = TeleportAnimation(from_cell=(2, 1), to_cell=(8, 1), started_at=100.0)
    run = _StubRun(player=(8, 1), teleport_animation=anim)
    after = 100.0 + ZIP_ANIMATION_DURATION_SECONDS + 1.0
    assert animated_player_position(run, now=after) == (8, 1)


# ── animated_maze_rotation_angle (rotation transition) ──────────────────


class _RotationStubRun:
    """Just enough of LabyrinthRun's shape for animated_maze_rotation_angle()."""

    def __init__(self, rotation_animation=None):
        self.rotation_animation = rotation_animation


def test_animated_maze_rotation_angle_is_zero_with_no_animation():
    run = _RotationStubRun()
    assert animated_maze_rotation_angle(run, now=100.0) == 0.0


def test_animated_maze_rotation_angle_starts_at_90_degrees():
    anim = RotationAnimation(started_at=100.0)
    run = _RotationStubRun(rotation_animation=anim)
    assert animated_maze_rotation_angle(run, now=100.0) == pytest.approx(90.0)


def test_animated_maze_rotation_angle_eases_down_to_zero_partway_through():
    anim = RotationAnimation(started_at=100.0)
    run = _RotationStubRun(rotation_animation=anim)
    halfway = 100.0 + ROTATE_ANIMATION_DURATION_SECONDS / 2
    assert animated_maze_rotation_angle(run, now=halfway) == pytest.approx(45.0)


def test_animated_maze_rotation_angle_is_zero_once_expired():
    anim = RotationAnimation(started_at=100.0)
    run = _RotationStubRun(rotation_animation=anim)
    after = 100.0 + ROTATE_ANIMATION_DURATION_SECONDS + 1.0
    assert animated_maze_rotation_angle(run, now=after) == 0.0
# ── Pressure pad markers ─────────────────────────────────────────────────


def test_pressure_pad_marker_is_drawn(tmp_path):
    """The wall segment itself needs no special drawing (see renderer.py's
    _draw_pressure_pads docstring) -- only the pad marker is under test here."""
    pygame.display.init()
    pygame.font.init()
    run = LabyrinthRun(seed=1, gold_path=tmp_path / "gold.json", meta_upgrades_path=tmp_path / "meta.json")
    run.grid = [
        [1, 1, 1, 1, 1],
        [1, 0, 0, 0, 1],
        [1, 1, 1, 1, 1],
    ]
    run.cols, run.rows = 5, 3
    run.player = (1, 1)
    run.goal = (1, 1)
    run.pellets = []
    run.gold_pellets = []
    run.hazards = []
    run.teleporters = []
    run.doors = []
    run.keys = []
    run.pressure_pads = [PressurePad(pad=(3, 1), wall_segment=(3, 0), mandatory=True, color_index=0)]

    layout = Layout(run.cols, run.rows)
    surface = pygame.Surface((layout.window_w, layout.window_h))
    Renderer(surface).draw(run)

    ox, oy = layout.maze_origin
    cell = layout.cell
    pad_px = surface.get_at((ox + 3 * cell + cell // 2, oy + cell + cell // 2))
    assert tuple(pad_px)[:3] == C_PRESSURE_PADS[0]


# ── Rotating maze animation ──────────────────────────────────────────────


def test_draw_mid_rotation_animation_does_not_crash_and_draws_within_the_maze_area(tmp_path):
    """
    A smoke test for the offscreen-surface-plus-rotate path in
    Renderer._draw_rotating_maze() -- doesn't check exact pixels (the
    rotated image's content shifts every frame of the animation), just that
    drawing mid-spin succeeds and still paints something other than pure
    background inside the maze viewport.
    """
    pygame.display.init()
    pygame.font.init()
    run = LabyrinthRun(seed=1, gold_path=tmp_path / "gold.json", meta_upgrades_path=tmp_path / "meta.json")
    run.augment_build.acquire(RotatingMazeAugment())
    run.grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    run.cols, run.rows = 3, 3
    run.player = (1, 1)
    run.goal = (1, 1)
    run.pellets = []
    run.gold_pellets = []
    run.hazards = []
    run.teleporters = []
    run.doors = []
    run.keys = []
    run.rotation_animation = RotationAnimation(started_at=time.monotonic() - ROTATE_ANIMATION_DURATION_SECONDS / 2)

    layout = Layout(run.cols, run.rows)
    surface = pygame.Surface((layout.window_w, layout.window_h))
    Renderer(surface).draw(run)  # must not raise

    ox, oy = layout.maze_origin
    cell = layout.cell
    painted = any(
        tuple(surface.get_at((ox + x, oy + y)))[:3] != C_BG
        for x in range(layout.maze_w)
        for y in range(layout.maze_h)
    )
    assert painted

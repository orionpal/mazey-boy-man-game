"""
Tests for maze_game.progression.renderer.Layout -- window/sidebar/perk-card
sizing math, and the text-wrapping helper perk cards/tooltips rely on to
avoid overflowing their rects. Pure geometry (pygame.Rect) and font
metrics, no display needed.
"""

import pygame

from maze_game.progression.renderer import Layout, MAZE_AREA_SIZE, _wrap_text
from maze_game.progression.shop.perks import ALL_PERKS
from maze_game.progression.augments import ALL_AUGMENTS
from maze_game.constants import SIDEBAR_W, HUD_HEIGHT


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
        assert layout.left.collidepoint(square.topleft)


# ── view_bounds (multi-level camera crop, see LabyrinthRun.current_view_bounds) ──


def test_layout_without_view_bounds_matches_full_grid_behaviour():
    """Regression guard: top-level rendering (no active floor) must be
    identical to plain Layout(cols, rows) -- explicit view_bounds=None is
    the same as omitting it."""
    implicit = Layout(cols=21, rows=13)
    explicit = Layout(cols=21, rows=13, view_bounds=None)
    assert implicit.cell == explicit.cell == Layout(cols=21, rows=13).cell
    assert implicit.view_origin == (0, 0)
    assert implicit.view_w == 21
    assert implicit.view_h == 13


def test_layout_with_view_bounds_scales_to_the_view_not_the_full_grid():
    """A small floor cropped inside a big maze should render at a much
    bigger cell size than the big maze itself would."""
    full = Layout(cols=41, rows=41)
    cropped = Layout(cols=41, rows=41, view_bounds=(10, 10, 5, 5))
    assert cropped.cell > full.cell
    assert cropped.view_w == 5
    assert cropped.view_h == 5
    assert cropped.maze_w <= MAZE_AREA_SIZE
    assert cropped.maze_h <= MAZE_AREA_SIZE


def test_layout_view_origin_offsets_cell_px():
    layout = Layout(cols=41, rows=41, view_bounds=(10, 12, 6, 6))
    assert layout.view_origin == (10, 12)
    ox, oy = layout.maze_origin
    # The view's own top-left cell (10, 12) must map to the maze area's
    # own screen-space top-left corner, regardless of its raw grid position.
    assert layout.cell_px(10, 12) == (ox, oy)
    assert layout.cell_px(11, 12) == (ox + layout.cell, oy)


def test_layout_in_view_respects_the_crop():
    layout = Layout(cols=41, rows=41, view_bounds=(10, 10, 5, 5))
    assert layout.in_view(10, 10)
    assert layout.in_view(14, 14)  # last cell inside a 5-wide/tall crop starting at 10
    assert not layout.in_view(15, 10)  # one past the crop's right edge
    assert not layout.in_view(9, 10)  # one before the crop's left edge


def test_layout_in_view_is_always_true_without_a_crop():
    layout = Layout(cols=21, rows=21)
    assert layout.in_view(0, 0)
    assert layout.in_view(20, 20)


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

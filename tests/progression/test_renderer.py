"""
Tests for maze_game.progression.renderer.Layout -- window/sidebar/perk-card
sizing math, and the text-wrapping helper perk cards/tooltips rely on to
avoid overflowing their rects. Pure geometry (pygame.Rect) and font
metrics, no display needed.
"""

import pygame

from maze_game.progression.renderer import Layout, MAZE_AREA_SIZE, _wrap_text
from maze_game.progression.shop.perks import ALL_PERKS
from maze_game.progression.shop.items import ALL_ITEMS
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


def test_item_squares_has_one_slot_per_item():
    layout = Layout(cols=21, rows=21)
    assert len(layout.item_squares) == len(ALL_ITEMS) == 4  # fixed Q/W/E/R, always drawn


def test_item_squares_are_within_the_left_sidebar():
    layout = Layout(cols=21, rows=21)
    for square in layout.item_squares:
        assert layout.left.collidepoint(square.topleft)


def test_item_squares_do_not_overlap_build_squares():
    layout = Layout(cols=21, rows=21)
    for build_square in layout.build_squares:
        for item_square in layout.item_squares:
            assert not build_square.colliderect(item_square)


def test_item_square_geometry_is_independent_of_maze_dimensions():
    small = Layout(cols=9, rows=9)
    large = Layout(cols=41, rows=41)
    assert small.item_squares == large.item_squares


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

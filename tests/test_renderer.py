"""
Tests for maze_game.renderer.Layout -- window/sidebar sizing math.
Pure geometry (pygame.Rect), no display needed.
"""

from maze_game.renderer import Layout, RIGHT_HEADER_HEIGHT, RIGHT_ENTRY_HEIGHT, RIGHT_BOTTOM_PADDING
from maze_game.constants import HUD_HEIGHT, MAX_HISTORY_SHOWN


def test_window_height_fits_a_small_maze_with_many_history_entries():
    """
    Regression test: a small maze's window used to be sized only from the
    maze + HUD, so a long history list would draw past the bottom of the
    window and visibly overlap the HUD text underneath it.
    """
    history_count = 10
    layout = Layout(cols=9, rows=9, history_count=history_count)

    required_for_history = RIGHT_HEADER_HEIGHT + history_count * RIGHT_ENTRY_HEIGHT + RIGHT_BOTTOM_PADDING
    assert layout.window_h >= required_for_history
    # Sidebars must span the full window, or their background can end above
    # the content drawn on top of it (the original form of this bug).
    assert layout.left.height == layout.window_h
    assert layout.right.height == layout.window_h


def test_window_height_caps_at_max_history_shown():
    """More history than MAX_HISTORY_SHOWN shouldn't keep growing the window forever."""
    layout_at_cap = Layout(cols=9, rows=9, history_count=MAX_HISTORY_SHOWN)
    layout_over_cap = Layout(cols=9, rows=9, history_count=MAX_HISTORY_SHOWN + 50)
    assert layout_at_cap.window_h == layout_over_cap.window_h


def test_window_height_grows_with_maze_for_large_mazes():
    small = Layout(cols=9, rows=9, history_count=0)
    large = Layout(cols=41, rows=41, history_count=0)
    assert large.window_h > small.window_h
    assert large.window_h == large.maze_h + HUD_HEIGHT


def test_hud_always_fits_within_the_window():
    for cols, rows, history_count in [(9, 9, 0), (9, 9, 20), (41, 41, 0), (21, 21, 12)]:
        layout = Layout(cols, rows, history_count)
        assert layout.hud.bottom <= layout.window_h

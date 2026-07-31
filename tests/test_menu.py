"""Tests for maze_game.menu -- the tiny main-menu cursor state."""

from maze_game.menu import MainMenu, MENU_OPTIONS


def test_starts_at_the_first_option():
    menu = MainMenu()
    assert menu.cursor == 0
    assert menu.selected_mode == MENU_OPTIONS[0][0]


def test_move_cursor_wraps_forward_and_backward():
    menu = MainMenu()
    menu.move_cursor(-1)
    assert menu.cursor == len(MENU_OPTIONS) - 1  # wraps backward from 0
    menu.move_cursor(1)
    assert menu.cursor == 0
    menu.move_cursor(1)
    assert menu.cursor == 1 % len(MENU_OPTIONS)


def test_selected_mode_matches_the_option_at_the_cursor():
    menu = MainMenu()
    for i in range(len(MENU_OPTIONS)):
        menu.cursor = i
        assert menu.selected_mode == MENU_OPTIONS[i][0]

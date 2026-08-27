"""
Integration smoke test for maze_game.arena.app.run_arena -- drives the real
event loop with posted pygame events under the dummy SDL video driver (set
by the test env), so the loop, renderer and state all run together for a
few frames without a visible window.
"""

import random

import pygame
import pytest

from maze_game.progression.run import FirstMazeRecord
from maze_game.arena import run_arena
from maze_game.arena.state import FACINGS

_GRID = [
    [1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 0, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 1],
]
_TRAIL = [(1, 1), (2, 1), (3, 1), (3, 2), (3, 3)]


@pytest.fixture
def window():
    pygame.init()
    pygame.display.set_mode((1, 1))
    from pygame._sdl2.video import Window
    win = Window.from_display_module()
    yield win
    pygame.display.quit()


def _record():
    return FirstMazeRecord(grid=[r[:] for r in _GRID], goal=(3, 3), trail=list(_TRAIL), start=(1, 1))


def test_escape_leaves_the_arena_with_a_quit_outcome(window):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    state = run_arena(window, pygame.time.Clock(), _record(), random.Random(0))
    assert state.outcome == "quit"


def test_fighting_along_the_recorded_route_reaches_the_exit_and_wins(window):
    # Start faces east along the trail. Punch east with strike+step pairs
    # (enemies spawn on the route), turn south, then punch south to the goal
    # at (3, 3). Extra pairs past a wall are harmless no-ops.
    keys = [pygame.K_SPACE, pygame.K_UP] * 3 + [pygame.K_RIGHT] + [pygame.K_SPACE, pygame.K_UP] * 3
    keys.append(pygame.K_RETURN)  # dismiss the result screen once "win" is set
    for key in keys:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key))
    state = run_arena(window, pygame.time.Clock(), _record(), random.Random(0))
    assert state.outcome == "win"

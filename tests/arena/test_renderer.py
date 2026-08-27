"""
Smoke tests for maze_game.arena.renderer.ArenaRenderer -- the software
raycaster. No display is opened; it draws onto a plain in-memory Surface.
The point is that a full frame (walls + billboards + HUD + result overlay)
renders without raising for a range of player positions/facings.
"""

import random

import pygame

from maze_game.progression.run import FirstMazeRecord
from maze_game.arena.state import ArenaState, FACINGS
from maze_game.arena.renderer import ArenaRenderer

_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 1, 0, 1],
    [1, 1, 1, 0, 1, 0, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 0, 1, 1, 1, 0, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 1, 1, 1, 1],
]
_TRAIL = [(1, 1), (2, 1), (3, 1), (3, 2), (3, 3), (4, 3), (5, 3), (5, 4), (5, 5)]


def _state():
    record = FirstMazeRecord(grid=[r[:] for r in _GRID], goal=(5, 5), trail=list(_TRAIL), start=(1, 1))
    return ArenaState(
        record=record, rng=random.Random(0), time_budget=90.0, max_health=3,
        enemy_count=3, treasure_count=2, treasure_gold=5,
    )


def _renderer():
    pygame.font.init()
    surface = pygame.Surface(ArenaRenderer.window_size())
    return ArenaRenderer(surface)


def test_draws_a_full_frame_from_every_facing_at_every_open_cell():
    renderer = _renderer()
    state = _state()
    for y, row in enumerate(_GRID):
        for x, cell in enumerate(row):
            if cell != 0:
                continue
            state.pos = (x, y)
            for facing in range(len(FACINGS)):
                state.facing = facing
                renderer.draw(state)


def test_draws_each_result_overlay():
    renderer = _renderer()
    state = _state()
    for outcome in ("win", "lose", "timeout", "quit"):
        state.outcome = outcome
        renderer.draw(state)


def test_draws_the_intro_card_without_raising():
    renderer = _renderer()
    renderer.draw(_state(), intro=True)


def test_camera_eases_toward_a_stepped_position_then_arrives():
    renderer = _renderer()
    state = _state()
    state.pos = (3, 3)
    renderer.draw(state)          # seeds the view at the start cell
    state.pos = (3, 2)            # one tile north
    renderer.draw(state)
    partway = (renderer._vx, renderer._vy)
    for _ in range(30):
        renderer.draw(state)
    assert partway != (3.5, 2.5)                      # it interpolated, didn't snap
    assert abs(renderer._vx - 3.5) < 0.05             # and converged
    assert abs(renderer._vy - 2.5) < 0.05

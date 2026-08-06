"""
Tests for maze_game.progression.augments.runtime.fog -- the line-of-sight
helper, visible_cells_from(). FogOfWarAugment's apply() is a no-op (see
the module docstring); runtime wiring (discovered_cells accumulation, the
permanent-memory default) is tested in tests/progression/test_run.py.
"""

from maze_game.progression.augments.runtime.fog import visible_cells_from

# A straight corridor, (1,1)-(2,1)-(3,1)-(4,1)-(5,1), with a short dead-end
# branch hanging off the middle at (3,2).
CORRIDOR_GRID = [
    [1, 1, 1, 1, 1, 1, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [1, 1, 1, 0, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1],
]


def test_a_straight_corridor_reveals_the_whole_corridor_both_directions():
    visible = visible_cells_from(CORRIDOR_GRID, (3, 1))
    for x in range(1, 6):
        assert (x, 1) in visible


def test_a_straight_corridor_reveals_nothing_beyond_its_own_boundary_walls():
    visible = visible_cells_from(CORRIDOR_GRID, (3, 1))
    # The wall cells terminating the corridor are visible (so it reads as
    # bounded, not fading into nothing) -- but nothing past them.
    assert (0, 1) in visible
    assert (6, 1) in visible
    assert (0, 0) not in visible
    assert (6, 2) not in visible


def test_standing_at_a_junction_reveals_partway_down_every_open_branch():
    visible = visible_cells_from(CORRIDOR_GRID, (3, 1))
    assert (3, 2) in visible  # one cell down the branch
    assert (3, 3) in visible  # the branch's own terminating wall


def test_a_dead_end_reveals_just_itself_and_the_approach():
    """
    Standing in the branch's own dead-end cell (3, 2): left/right rays hit
    a wall immediately (2, 2)/(4, 2); the down-ray hits the branch's own
    terminating wall (3, 3); the up-ray passes straight through the
    junction cell (3, 1) -- a ray only stops at a *wall*, not at a
    junction -- continuing to the corridor's own far wall (3, 0). It does
    NOT reveal sideways along the corridor at y=1 (2, 1)/(4, 1) -- that's a
    turn, not a straight line, and true line of sight can't see around one.
    """
    visible = visible_cells_from(CORRIDOR_GRID, (3, 2))
    assert visible == {(3, 2), (3, 1), (3, 0), (3, 3), (2, 2), (4, 2)}

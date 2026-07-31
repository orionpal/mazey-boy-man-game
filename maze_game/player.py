"""
player.py
---------
Player movement logic.

The player "slides" in a chosen direction — moving cell by cell until they
either hit a wall or arrive at an intersection (a cell with 3+ open
neighbours, meaning a choice is available).  This gives the game its
distinctive feel without requiring frame-by-frame movement.
"""

from typing import Callable


def _open_neighbour_count(
    grid: list[list[int]], cx: int, cy: int
) -> int:
    """Return how many of the four cardinal neighbours are open passages."""
    cols = len(grid[0])
    rows = len(grid)
    return sum(
        1
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))
        if 0 <= cx + dx < cols
        and 0 <= cy + dy < rows
        and grid[cy + dy][cx + dx] == 0
    )


def slide_path(
    grid: list[list[int]],
    pos: tuple[int, int],
    direction: tuple[int, int],
    *,
    junction_stop_count: int | None = 1,
    break_wall: Callable[[int, int], bool] | None = None,
    teleport: Callable[[int, int], tuple[int, int] | None] | None = None,
) -> list[tuple[int, int]]:
    """
    Slide the player from `pos` in `direction`, returning every cell entered
    along the way (not just the final stopping point) -- needed so callers
    can detect contact with anything placed inside the maze (pellets,
    enemies) that the slide passes *through* without stopping on,
    which happens routinely: the stop rule only cares whether the next cell
    in the *current* travel direction is a wall, so any cell that merely
    isn't a dead end/turn along this particular direction gets passed
    through, regardless of its own neighbour count. Empty if the immediate
    next cell is already a wall/out of bounds (a no-op slide).

    Stops after passing `junction_stop_count` intersections (≥ 3 open
    neighbours):
      - The default, 1, stops at the very first intersection reached --
        the normal single-press move.
      - N > 1 blows straight through the first N-1 intersections reached
        (continuing in the same `direction`, same as holding the key down
        through them) and stops at the Nth.
      - None never stops at an intersection at all, only at a wall -- the
        "hold spacebar" combo, for running a corridor out to its end.

    Normally also stops the instant the next cell would be a wall or out of
    bounds. If `break_wall` is given, it's offered the chance to override an
    in-bounds wall stop: called as `break_wall(nx, ny)`, and if it returns
    True (having mutated `grid[ny][nx]` to open, which is this hook's
    responsibility, not this function's -- `slide_path` stays maze/charge-
    agnostic, just "ask, and if yes, treat this cell as open now"), the
    slide continues straight through it instead of stopping. Out-of-bounds
    is never offered to `break_wall` -- there's no cell there to open.

    If `teleport` is given, it's checked against every newly-entered cell:
    called as `teleport(cx, cy)`, and if it returns a cell (rather than
    None), the slide immediately warps there and stops -- one hop per call,
    no momentum carried through the link. Stopping (rather than continuing
    in `direction` from the linked cell) sidesteps needing extra state to
    guard against bouncing back and forth through a pair, and matches the
    existing "you always land exactly on a stopping cell, then choose your
    next direction" feel already used for junctions.
    """
    cols = len(grid[0])
    rows = len(grid)
    dx, dy = direction
    cx, cy = pos
    path: list[tuple[int, int]] = []
    junctions_passed = 0

    while True:
        nx, ny = cx + dx, cy + dy

        if not (0 <= nx < cols and 0 <= ny < rows):
            break

        if grid[ny][nx] == 1:
            if break_wall is None or not break_wall(nx, ny):
                break
            # break_wall() has opened (nx, ny); fall through and move into it.

        cx, cy = nx, ny
        path.append((cx, cy))

        if teleport is not None:
            dest = teleport(cx, cy)
            if dest is not None:
                cx, cy = dest
                path.append((cx, cy))
                break

        # Stop at an intersection once junction_stop_count of them have been reached.
        if _open_neighbour_count(grid, cx, cy) > 2:
            junctions_passed += 1
            if junction_stop_count is not None and junctions_passed >= junction_stop_count:
                break

    return path


def slide(
    grid: list[list[int]],
    pos: tuple[int, int],
    direction: tuple[int, int],
) -> tuple[int, int]:
    """
    Slide the player from `pos` in `direction` until they:
      1. Would move into a wall or out of bounds, OR
      2. Arrive at an intersection (≥ 3 open neighbours).

    Returns the new (col, row) position.
    """
    path = slide_path(grid, pos, direction)
    return path[-1] if path else pos

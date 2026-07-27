"""
player.py
---------
Player movement logic.

The player "slides" in a chosen direction — moving cell by cell until they
either hit a wall or arrive at an intersection (a cell with 3+ open
neighbours, meaning a choice is available).  This gives the game its
distinctive feel without requiring frame-by-frame movement.
"""


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
) -> list[tuple[int, int]]:
    """
    Slide the player from `pos` in `direction`, returning every cell entered
    along the way (not just the final stopping point) -- needed so callers
    can detect contact with anything placed inside the maze (pellets,
    enemies, a boss) that the slide passes *through* without stopping on,
    which happens routinely: the stop rule only cares whether the next cell
    in the *current* travel direction is a wall, so any cell that merely
    isn't a dead end/turn along this particular direction gets passed
    through, regardless of its own neighbour count. Empty if the immediate
    next cell is already a wall/out of bounds (a no-op slide).

    Stops when the player:
      1. Would move into a wall or out of bounds, OR
      2. Arrives at an intersection (≥ 3 open neighbours).
    """
    cols = len(grid[0])
    rows = len(grid)
    dx, dy = direction
    cx, cy = pos
    path: list[tuple[int, int]] = []

    while True:
        nx, ny = cx + dx, cy + dy

        # Stop if the next cell is a wall or out of bounds.
        if not (0 <= nx < cols and 0 <= ny < rows) or grid[ny][nx] == 1:
            break

        cx, cy = nx, ny
        path.append((cx, cy))

        # Stop at junctions so the player can choose a new direction.
        if _open_neighbour_count(grid, cx, cy) > 2:
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

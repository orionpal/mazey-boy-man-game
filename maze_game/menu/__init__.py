"""
menu/__init__.py
-----------------
The main-menu state: pick between the timed labyrinth run, the untimed
free-play ("Relax") mode, or replaying the tutorial (see
progression/meta/tutorial.py). Pure state, no pygame dependency -- same
pattern as freeplay/game.py::Game and progression/run.py::LabyrinthRun.
Drawing lives in menu/renderer.py, mirroring the freeplay/progression
package shape.
"""

# (mode key used by main.py's dispatch, display label). Order is the
# on-screen/cursor order.
MENU_OPTIONS: list[tuple[str, str]] = [
    ("labyrinth", "Labyrinth Run"),
    ("relax", "Relax (Free Play)"),
    ("tutorial", "Tutorial"),
]


class MainMenu:
    """Just a wrapping cursor over MENU_OPTIONS -- there's nothing else to track."""

    def __init__(self) -> None:
        self.cursor = 0

    def move_cursor(self, delta: int) -> None:
        self.cursor = (self.cursor + delta) % len(MENU_OPTIONS)

    @property
    def selected_mode(self) -> str:
        return MENU_OPTIONS[self.cursor][0]

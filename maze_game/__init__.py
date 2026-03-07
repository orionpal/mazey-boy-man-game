# maze_game/__init__.py
# Exposes the public surface of the package.
from maze_game.game import Game
from maze_game.renderer import Renderer

__all__ = ["Game", "Renderer"]

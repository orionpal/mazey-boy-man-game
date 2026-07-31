"""
menu/renderer.py
-----------------
Drawing for the main menu -- a title plus the two mode options from
menu/__init__.py, cursor/hover-highlighted. Its own small fixed window
size, independent of either game mode's layout (which only get sized once
a mode -- and therefore a maze -- actually exists).
"""

import pygame

from maze_game.constants import C_BG, C_TEXT, C_DIM, C_BUTTON, C_BUTTON_HOVER, C_FLASH
from maze_game.menu import MainMenu, MENU_OPTIONS

WINDOW_W = 480
WINDOW_H = 360

OPTION_W = 360
OPTION_H = 60
OPTION_GAP = 20
OPTION_START_Y = 160


class MenuRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font_huge = pygame.font.SysFont("monospace", 36, bold=True)
        self.font_big = pygame.font.SysFont("monospace", 22, bold=True)
        self.font_small = pygame.font.SysFont("monospace", 14)

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    @staticmethod
    def window_size() -> tuple[int, int]:
        return WINDOW_W, WINDOW_H

    def option_rects(self) -> list[pygame.Rect]:
        """Shared by draw() and main.py's click handling -- same convention as the game-mode Layouts."""
        x = (WINDOW_W - OPTION_W) // 2
        return [
            pygame.Rect(x, OPTION_START_Y + i * (OPTION_H + OPTION_GAP), OPTION_W, OPTION_H)
            for i in range(len(MENU_OPTIONS))
        ]

    def draw(self, menu: MainMenu, mouse_pos: tuple[int, int]) -> None:
        self.surface.fill(C_BG)

        title = self.font_huge.render("MAZE", True, C_TEXT)
        self.surface.blit(title, title.get_rect(center=(WINDOW_W // 2, 70)))

        for i, ((_, label), rect) in enumerate(zip(MENU_OPTIONS, self.option_rects())):
            selected = i == menu.cursor
            hovered = rect.collidepoint(mouse_pos)
            colour = C_BUTTON_HOVER if (selected or hovered) else C_BUTTON
            pygame.draw.rect(self.surface, colour, rect, border_radius=8)
            pygame.draw.rect(self.surface, C_FLASH if selected else C_DIM, rect, width=2, border_radius=8)

            text = self.font_big.render(label, True, C_TEXT)
            self.surface.blit(text, text.get_rect(center=rect.center))

        hint = self.font_small.render(
            "arrows/click to choose, enter/space to confirm, ESC to quit", True, C_DIM,
        )
        self.surface.blit(hint, hint.get_rect(center=(WINDOW_W // 2, WINDOW_H - 30)))

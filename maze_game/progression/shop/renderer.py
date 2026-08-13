"""
shop/renderer.py
-----------------
Drawing for the in-maze walk-to shop panel (progression/entities/shop_tile.py
-- step on the tile, LabyrinthRun.enter_shop() pauses the real timer and
starts its own SHOP_PAUSE_SECONDS countdown, shown here as a big, hard-to-
miss number). Split out of progression/renderer.py into its own module the
same way progression/meta/ already owns a renderer.py separate from the main
one -- this panel is a self-contained overlay (drawn *on top of* the still-
visible maze/HUD/sidebars, not replacing them like the break-card screen
does), so it doesn't need to live inside the main Renderer class at all.
"""

import pygame

from maze_game.constants import (
    C_TEXT, C_DIM, C_CARD_DESC, C_FLASH, C_GOLD, C_SHOP,
    C_PANEL_BG, C_PANEL_LINE, C_BUTTON, C_BUTTON_HOVER,
)
from maze_game.progression.shop import MAZE_SHOP_ITEMS, maze_shop_cost

PANEL_W = 380
ITEM_H = 72  # tall enough for a name+cost line plus a two-line-wrapped description
ITEM_GAP = 10
ITEM_PADDING = 12
TOP_PADDING = 92  # room for the title + big countdown above the item rows
BOTTOM_PADDING = 16
TEXT_PADDING = 12
LINE_HEIGHT = 18
LOW_TIME_WARNING_SECONDS = 5.0


def _wrap_text(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
    """Greedy word-wrap: split `text` into lines no wider than `max_width` pixels."""
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def panel_rect(maze_area_size: int, sidebar_w: int) -> pygame.Rect:
    """Centred over the maze viewport -- shared by Layout and app.py's click handling."""
    item_count = len(MAZE_SHOP_ITEMS)
    h = TOP_PADDING + item_count * ITEM_H + (item_count - 1) * ITEM_GAP + BOTTOM_PADDING
    return pygame.Rect(
        sidebar_w + (maze_area_size - PANEL_W) // 2, (maze_area_size - h) // 2, PANEL_W, h,
    )


def item_rects(panel: pygame.Rect) -> list[pygame.Rect]:
    return [
        pygame.Rect(
            panel.x + ITEM_PADDING, panel.y + TOP_PADDING + i * (ITEM_H + ITEM_GAP),
            PANEL_W - 2 * ITEM_PADDING, ITEM_H,
        )
        for i in range(len(MAZE_SHOP_ITEMS))
    ]


def draw(
    surface: pygame.Surface,
    run,
    panel: pygame.Rect,
    rects: list[pygame.Rect],
    font_big: pygame.font.Font,
    font_huge: pygame.font.Font,
    font_small: pygame.font.Font,
    mouse_pos: tuple[int, int],
) -> None:
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 150))
    surface.blit(overlay, (0, 0))

    pygame.draw.rect(surface, C_PANEL_BG, panel, border_radius=10)
    pygame.draw.rect(surface, C_SHOP, panel, width=3, border_radius=10)

    title = font_big.render("SHOP", True, C_TEXT)
    surface.blit(title, title.get_rect(center=(panel.centerx, panel.y + 20)))

    remaining = run.shop_time.amount if run.shop_time is not None else 0.0
    countdown_colour = C_FLASH if remaining <= LOW_TIME_WARNING_SECONDS else C_SHOP
    countdown = font_huge.render(f"{remaining:4.1f}s", True, countdown_colour)
    surface.blit(countdown, countdown.get_rect(center=(panel.centerx, panel.y + 58)))

    gold_label = font_small.render(f"{run.gold}g available", True, C_GOLD)
    surface.blit(gold_label, gold_label.get_rect(center=(panel.centerx, panel.y + 84)))

    text_w = PANEL_W - 2 * ITEM_PADDING - 2 * TEXT_PADDING
    for i, (item, rect) in enumerate(zip(MAZE_SHOP_ITEMS, rects)):
        cost = maze_shop_cost(item, run)
        affordable = run.gold >= cost
        selected = rect.collidepoint(mouse_pos) or i == run.shop_cursor
        pygame.draw.rect(surface, C_BUTTON_HOVER if selected else C_BUTTON, rect, border_radius=6)
        pygame.draw.rect(surface, C_FLASH if i == run.shop_cursor else C_PANEL_LINE, rect, width=2, border_radius=6)

        name = font_small.render(f"[{i + 1}] {item.name}", True, C_TEXT)
        surface.blit(name, (rect.x + TEXT_PADDING, rect.y + 6))

        cost_label = font_small.render(f"{cost}g", True, C_GOLD if affordable else C_DIM)
        surface.blit(cost_label, (rect.right - cost_label.get_width() - TEXT_PADDING, rect.y + 6))

        desc_y = rect.y + 26
        for line in _wrap_text(font_small, item.description, text_w):
            desc = font_small.render(line, True, C_CARD_DESC)
            surface.blit(desc, (rect.x + TEXT_PADDING, desc_y))
            desc_y += LINE_HEIGHT

    hint = font_small.render(
        "Arrows + space, click, or 1/2/3 to buy -- resumes when the countdown ends", True, C_DIM,
    )
    surface.blit(hint, hint.get_rect(center=(panel.centerx, panel.bottom + 16)))

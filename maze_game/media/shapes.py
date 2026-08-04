# maze_game/media/shapes.py
"""
Primitive-shape drawing helpers shared by freeplay/renderer.py and
progression/renderer.py -- both fall back to drawing the player as a plain
circle when assets/icons/player.png doesn't exist (see sprites.py), and
both want the same smiley face on that circle, so it lives here rather
than being duplicated per renderer.
"""

import math

import pygame

_MIN_RADIUS_FOR_FACE = 4  # below this, eyes/mouth are too small to read -- skip them


def draw_smiley_face(surface: pygame.Surface, colour, center: tuple[int, int], radius: int) -> None:
    """Draw two eyes and a smiling mouth inside a circle of `radius` centred at `center`."""
    if radius < _MIN_RADIUS_FOR_FACE:
        return

    cx, cy = center
    eye_r = max(1, radius // 6)
    eye_dx = radius // 2
    eye_dy = radius // 4
    pygame.draw.circle(surface, colour, (cx - eye_dx, cy - eye_dy), eye_r)
    pygame.draw.circle(surface, colour, (cx + eye_dx, cy - eye_dy), eye_r)

    mouth_w = int(radius * 1.1)
    mouth_h = int(radius * 0.9)
    mouth_rect = pygame.Rect(0, 0, mouth_w, mouth_h)
    mouth_rect.center = (cx, cy)
    # pygame.draw.arc measures angles counterclockwise with a math (y-up)
    # convention despite screen y being down -- pi to 2*pi traces the
    # bottom half of the ellipse, which reads as a smile.
    pygame.draw.arc(surface, colour, mouth_rect, math.pi, 2 * math.pi, max(1, radius // 8))

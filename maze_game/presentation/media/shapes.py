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


def draw_player_marker(
    surface: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    fill_colour,
    outline_colour,
    face_colour,
) -> None:
    """
    Draw the player as a filled circle with a bright outline ring and a
    smiley face -- the outline is what keeps the marker readable once large
    mazes shrink `radius` down to just a few pixels, since a thin halo still
    reads against wall/floor/entity colours even when the fill alone would
    blend in. Both renderers' fallback (no assets/icons/player.png) path
    call this so the look stays identical.
    """
    outline_radius = radius + max(2, radius // 3)
    pygame.draw.circle(surface, outline_colour, center, outline_radius)
    pygame.draw.circle(surface, fill_colour, center, radius)
    draw_smiley_face(surface, face_colour, center, radius)


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

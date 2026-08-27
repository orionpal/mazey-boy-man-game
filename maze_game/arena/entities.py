"""
entities.py
-----------
The arena interlude's enemies and treasures: their value types, the enemy
roster (variety -- grunt / lurker / brute, each with its own wake range,
move cadence and toughness), and the plain-``pygame.draw`` billboard
sprites the renderer stamps for each one.

Kept out of state.py (pure sim) and renderer.py (the raycaster) so both
stay focused: state.py imports the dataclasses + kinds, renderer.py imports
the ``draw_*`` helpers. Sprites are still just rects/circles/polygons -- no
textures, so nothing here changes the pygbag build (see 3d-rework.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame


@dataclass(frozen=True)
class EnemyKind:
    name: str
    colour: tuple[int, int, int]
    wake_range: int      # Manhattan distance at which a parked enemy starts chasing
    move_period: int     # steps one cell every Nth "active" enemy tick (1 = as fast as the sim allows)
    hits_to_kill: int    # attack() calls to put it down
    height: float        # billboard scale (1.0 == a wall strip at that distance)


# Cycled by spawn order in ArenaState._place_enemies (index % len(ROSTER)),
# so a 3-enemy arena is always one of each and the mix is deterministic.
GRUNT = EnemyKind("grunt", (230, 60, 60), wake_range=6, move_period=2, hits_to_kill=1, height=0.82)
LURKER = EnemyKind("lurker", (180, 80, 205), wake_range=2, move_period=1, hits_to_kill=1, height=0.72)
BRUTE = EnemyKind("brute", (210, 120, 45), wake_range=5, move_period=3, hits_to_kill=2, height=1.02)

ROSTER: tuple[EnemyKind, ...] = (GRUNT, LURKER, BRUTE)


@dataclass
class Enemy:
    pos: tuple[int, int]
    kind: EnemyKind = GRUNT
    alive: bool = True
    awake: bool = False
    wounds: int = 0

    @property
    def down(self) -> bool:
        return self.wounds >= self.kind.hits_to_kill


@dataclass
class Treasure:
    pos: tuple[int, int]
    collected: bool = False


# ── Billboard sprites ─────────────────────────────────────────────────────
# Each takes the on-screen bounding rect the raycaster projected for the
# entity and a `tint` colour already blended toward fog for distance.


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(a[i] + (b[i] - a[i]) * t))) for i in range(3))  # type: ignore[return-value]


def draw_enemy(surface: pygame.Surface, rect: pygame.Rect, kind: EnemyKind, tint: tuple[int, int, int]) -> None:
    w, h = rect.width, rect.height
    if w < 2 or h < 2:
        pygame.draw.rect(surface, tint, rect)
        return
    dark = _mix(tint, (0, 0, 0), 0.45)
    eye = _mix(tint, (255, 255, 255), 0.8)

    if kind.name == "lurker":
        body = pygame.Rect(0, 0, max(2, w * 3 // 5), h)
        body.midbottom = rect.midbottom
        pygame.draw.rect(surface, tint, body, border_radius=max(1, w // 6))
        hood = [body.midtop, (body.left - w // 6, body.top + h // 4), (body.right + w // 6, body.top + h // 4)]
        pygame.draw.polygon(surface, dark, hood)
        slit = pygame.Rect(0, 0, max(2, w // 3), max(1, h // 12))
        slit.center = (rect.centerx, body.top + h // 6)
        pygame.draw.rect(surface, eye, slit)
        return

    if kind.name == "brute":
        body = pygame.Rect(0, 0, w, h * 4 // 5)
        body.midbottom = rect.midbottom
        pygame.draw.rect(surface, tint, body, border_radius=max(1, w // 8))
        head_r = max(2, w // 5)
        head_c = (rect.centerx, body.top - head_r // 2)
        pygame.draw.circle(surface, dark, head_c, head_r)
        for sx in (-1, 1):
            horn = [
                (head_c[0] + sx * head_r, head_c[1]),
                (head_c[0] + sx * head_r * 2, head_c[1] - head_r),
                (head_c[0] + sx * head_r, head_c[1] - head_r // 2),
            ]
            pygame.draw.polygon(surface, tint, horn)
        for sx in (-1, 1):
            pygame.draw.circle(surface, eye, (head_c[0] + sx * head_r // 2, head_c[1]), max(1, head_r // 3))
        return

    # grunt (default): simple torso + round head + two eyes
    body = pygame.Rect(0, 0, max(2, w * 3 // 4), h * 3 // 4)
    body.midbottom = rect.midbottom
    pygame.draw.rect(surface, tint, body, border_radius=max(1, w // 5))
    head_r = max(2, w // 4)
    head_c = (rect.centerx, body.top - head_r // 3)
    pygame.draw.circle(surface, tint, head_c, head_r)
    for sx in (-1, 1):
        pygame.draw.circle(surface, eye, (head_c[0] + sx * head_r // 2, head_c[1]), max(1, head_r // 3))


def draw_treasure(surface: pygame.Surface, rect: pygame.Rect, tint: tuple[int, int, int]) -> None:
    w, h = rect.width, rect.height
    if w < 3 or h < 3:
        pygame.draw.rect(surface, tint, rect)
        return
    chest = pygame.Rect(0, 0, w, h * 3 // 4)
    chest.midbottom = rect.midbottom
    wood = _mix(tint, (90, 55, 20), 0.55)
    pygame.draw.rect(surface, wood, chest, border_radius=max(1, w // 10))
    lid = pygame.Rect(chest.left, chest.top, chest.width, max(2, chest.height // 3))
    pygame.draw.rect(surface, _mix(wood, (255, 255, 255), 0.2), lid, border_radius=max(1, w // 10))
    band = pygame.Rect(chest.left, chest.centery - max(1, h // 16), chest.width, max(2, h // 8))
    pygame.draw.rect(surface, tint, band)
    pygame.draw.circle(surface, _mix(tint, (0, 0, 0), 0.5), band.center, max(1, w // 10))
    # a floating glint above the chest
    pygame.draw.circle(surface, _mix(tint, (255, 255, 255), 0.7), (rect.centerx, rect.top + h // 8), max(1, w // 12))


def draw_goal(surface: pygame.Surface, rect: pygame.Rect, tint: tuple[int, int, int]) -> None:
    w, h = rect.width, rect.height
    if w < 3 or h < 3:
        pygame.draw.rect(surface, tint, rect)
        return
    inner = _mix(tint, (255, 255, 255), 0.65)
    for i, shrink in enumerate((0.0, 0.28, 0.55)):
        ring = rect.inflate(-int(w * shrink), -int(h * shrink))
        colour = _mix(tint, inner, i / 2)
        pygame.draw.ellipse(surface, colour, ring, width=0 if i == 2 else max(1, w // 12))

"""
sprites.py
----------
Lazy-loading, cached icon lookup with a "no icon yet" fallback: every
entity currently renders as a primitive shape (circle/rect/ellipse); this
lets a PNG in assets/icons/ transparently replace that shape once one
exists, without any renderer changes beyond what's already wired up.

get(name, size) returns a `size`x`size` pygame.Surface, or None if no icon
file exists for `name` yet -- every call site is expected to fall back to
drawing its existing primitive shape when None comes back.
"""

from pathlib import Path

import pygame

ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "icons"

_raw_cache: dict[str, pygame.Surface | None] = {}
_scaled_cache: dict[tuple[str, int], pygame.Surface] = {}


def get(name: str, size: int) -> pygame.Surface | None:
    """Return a `size`x`size` icon for `name` (assets/icons/{name}.png), or None if it doesn't exist."""
    if name not in _raw_cache:
        _raw_cache[name] = _load(name)
    raw = _raw_cache[name]
    if raw is None:
        return None

    key = (name, size)
    if key not in _scaled_cache:
        _scaled_cache[key] = pygame.transform.smoothscale(raw, (size, size))
    return _scaled_cache[key]


def _load(name: str) -> pygame.Surface | None:
    path = ICONS_DIR / f"{name}.png"
    if not path.exists():
        return None
    try:
        # Deliberately not .convert_alpha() -- that requires an active
        # display (pygame.display.set_mode()) to have already run, which
        # would make this untestable without one. The raw loaded surface
        # still blits correctly (including per-pixel alpha from the PNG),
        # just without the display-format blit-speed optimization -- a
        # fine trade for icons this small, drawn this infrequently.
        return pygame.image.load(path)
    except pygame.error:
        return None


def clear_cache() -> None:
    """Drop cached icons/scales -- useful for tests, or after dropping a new file in mid-session."""
    _raw_cache.clear()
    _scaled_cache.clear()

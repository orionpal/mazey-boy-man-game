"""
Tests for maze_game.media.sprites -- icon lookup with a None-on-miss
fallback (see docs/assets.md).
"""

import pygame

from maze_game.media import sprites


def setup_function():
    # Each test gets a clean cache -- otherwise an earlier test's monkeypatched
    # ICONS_DIR could leave stale entries that mask a later test's real check.
    sprites.clear_cache()


def test_get_returns_none_when_no_icon_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "ICONS_DIR", tmp_path)
    assert sprites.get("does_not_exist", 32) is None


def _write_tiny_png(path, size=8):
    pygame.init()
    surface = pygame.Surface((size, size))
    surface.fill((255, 0, 0))
    pygame.image.save(surface, str(path))


def test_get_loads_and_scales_a_real_icon_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "ICONS_DIR", tmp_path)
    _write_tiny_png(tmp_path / "pellet.png")

    icon = sprites.get("pellet", 40)
    assert icon is not None
    assert icon.get_size() == (40, 40)


def test_get_caches_the_loaded_icon(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "ICONS_DIR", tmp_path)
    _write_tiny_png(tmp_path / "gold.png")

    first = sprites.get("gold", 20)
    (tmp_path / "gold.png").unlink()  # prove the second call doesn't re-read the file
    second = sprites.get("gold", 20)
    assert first is second


def test_clear_cache_forces_a_fresh_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "ICONS_DIR", tmp_path)
    assert sprites.get("enemy", 20) is None

    _write_tiny_png(tmp_path / "enemy.png")
    assert sprites.get("enemy", 20) is None  # still cached as missing

    sprites.clear_cache()
    assert sprites.get("enemy", 20) is not None  # fresh lookup finds the new file

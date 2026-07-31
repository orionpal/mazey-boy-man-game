"""
Tests for maze_game.media.sound -- event-name-keyed sound playback with a
silent-no-op-on-miss fallback (see docs/assets.md).
"""

import wave

import pygame

from maze_game.media import sound


def setup_function():
    sound.clear_cache()


def _write_tiny_wav(path) -> None:
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\x00\x00" * 800)  # 0.1s of silence -- just needs to be a valid WAV


def test_play_on_unknown_event_is_a_silent_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "SOUNDS_DIR", tmp_path)
    sound.play("does_not_exist")  # must not raise


def test_play_never_touches_mixer_init_when_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "SOUNDS_DIR", tmp_path)
    monkeypatch.setattr(sound, "_mixer_ready", None)
    calls = []
    monkeypatch.setattr(pygame.mixer, "init", lambda *a, **k: calls.append(1))

    sound.play("nonexistent")

    assert calls == []
    assert sound._mixer_ready is None  # never even attempted


def test_play_loads_and_plays_a_real_sound_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "SOUNDS_DIR", tmp_path)
    monkeypatch.setattr(sound, "_mixer_ready", None)
    _write_tiny_wav(tmp_path / "move.wav")

    sound.play("move")  # should not raise, and should actually load it

    assert sound._mixer_ready is True
    assert sound._cache["move"] is not None


def test_play_finds_ogg_files_too(tmp_path, monkeypatch):
    """Only checking the file exists here (not a real OGG) -- confirms both extensions are searched, in order."""
    monkeypatch.setattr(sound, "SOUNDS_DIR", tmp_path)
    (tmp_path / "gold.ogg").touch()

    found = sound._find_file("gold")
    assert found == tmp_path / "gold.ogg"


def test_play_caches_the_loaded_sound_and_survives_the_file_disappearing(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "SOUNDS_DIR", tmp_path)
    monkeypatch.setattr(sound, "_mixer_ready", None)
    _write_tiny_wav(tmp_path / "pellet.wav")

    sound.play("pellet")
    first = sound._cache["pellet"]
    (tmp_path / "pellet.wav").unlink()

    sound.play("pellet")  # must not error even though the file's gone -- reuses the cached Sound
    assert sound._cache["pellet"] is first


def test_clear_cache_forces_a_fresh_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(sound, "SOUNDS_DIR", tmp_path)
    monkeypatch.setattr(sound, "_mixer_ready", None)

    sound.play("hazard_hit")
    assert sound._cache["hazard_hit"] is None

    _write_tiny_wav(tmp_path / "hazard_hit.wav")
    sound.play("hazard_hit")
    assert sound._cache["hazard_hit"] is None  # still cached as missing

    sound.clear_cache()
    sound.play("hazard_hit")
    assert sound._cache["hazard_hit"] is not None  # fresh lookup finds the new file

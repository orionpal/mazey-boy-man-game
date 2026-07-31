"""
sound.py
--------
Lazy-loading, cached sound-effect lookup with a graceful "no sound yet"
no-op: gameplay events (move, pellet, teleport, ...) are reported by
LabyrinthRun/Game via their `events` list (see progression/run.py,
freeplay/game.py) and drained once per frame by the pygame loops
(progression/app.py, freeplay/app.py), which call play(event) for each.
play() looks up assets/sounds/{event}.wav (or .ogg) and plays it if the
file exists, and does nothing at all otherwise -- dropping a file in later
just works with no code changes, and the game stays fully playable today
with zero sound files.

Deliberately checks for a matching file *before* touching pygame.mixer at
all: with no sound files (today), play() never attempts mixer init, so
there's nothing to fail even on a machine with no audio device. Once a
file does exist, mixer init is attempted exactly once (cached) and wrapped
in try/except -- a failure there permanently (for this process) disables
sound rather than raising, since sound is a nice-to-have, never a hard
requirement to play.
"""

from pathlib import Path

import pygame

SOUNDS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "sounds"
SOUND_EXTENSIONS = (".wav", ".ogg")

_mixer_ready: bool | None = None  # None = not attempted yet
_cache: dict[str, pygame.mixer.Sound | None] = {}


def play(event: str) -> None:
    """Play the sound effect for `event` if assets/sounds/{event}.(wav|ogg) exists; silently do nothing otherwise."""
    if event not in _cache:
        _cache[event] = _load(event)
    sound = _cache[event]
    if sound is not None:
        sound.play()


def _load(event: str) -> pygame.mixer.Sound | None:
    path = _find_file(event)
    if path is None:
        return None
    if not _ensure_mixer():
        return None
    try:
        return pygame.mixer.Sound(str(path))
    except pygame.error:
        return None


def _find_file(event: str) -> Path | None:
    for ext in SOUND_EXTENSIONS:
        path = SOUNDS_DIR / f"{event}{ext}"
        if path.exists():
            return path
    return None


def _ensure_mixer() -> bool:
    global _mixer_ready
    if _mixer_ready is None:
        try:
            pygame.mixer.init()
            _mixer_ready = True
        except pygame.error:
            _mixer_ready = False
    return _mixer_ready


def clear_cache() -> None:
    """Drop cached lookups -- useful for tests, or after dropping a new file in mid-session."""
    _cache.clear()

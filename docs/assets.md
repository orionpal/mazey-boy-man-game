# Asset Readiness: Sound and Icon Hooks

## The ask

Be able to drop in and test different sound effects (movement, going
through a portal, "and whatnot") and different icons (a clock for time
pellets, say) later, without a code change each time. There's no actual
audio/image content today -- this is purely the plumbing and the fallback
behaviour, built once so dropping a file in "just works."

## Two lookups, one shape: cached, keyed by name, `None`/no-op on a miss

`maze_game/media/sound.py::play(event: str)` and
`maze_game/media/sprites.py::get(name: str, size: int)` both follow the
same contract: check `assets/{sounds,icons}/` for a file matching the
given name, cache the result (hit or miss), and degrade gracefully if
nothing's there -- `play()` does nothing at all, `get()` returns `None`
and the caller falls back to whatever it was already drawing (a primitive
shape). Every existing draw/action call site keeps its current behaviour
completely unchanged until a matching file actually exists.

`sound.play()` deliberately checks for a matching file *before* touching
`pygame.mixer` at all. With zero sound files (today, and for anyone who
never adds any), `pygame.mixer.init()` is never even attempted -- nothing
to fail on a machine with no audio device. The first time a real file is
found, mixer init is attempted exactly once (cached) and wrapped in
`try/except pygame.error`; a failure there permanently disables sound for
that process rather than crashing anything, since sound is a nice-to-have,
never a hard requirement to play.

`sprites.get()` deliberately skips `.convert_alpha()` on the loaded image
-- that call requires an active display (`pygame.display.set_mode()`) to
already be running, which would make icon lookup untestable without one.
The raw loaded `Surface` still blits correctly, per-pixel PNG alpha
included, just without the display-format blit-speed optimization -- a
fine trade for icons this small, drawn this infrequently.

## How gameplay events reach `sound.play()` without polluting pure state

`LabyrinthRun` and `Game` are both explicitly documented as pure state
machines, independent of pygame, testable without a display -- so neither
calls `pygame.mixer` directly. Instead, each gained a `self.events:
list[str]` that action methods append short event-name strings to (the
same shape `add_popup()` already used for the floating +Xs/-Xs feedback
text, and reusing several of its exact call sites). The pygame-aware loop
layer (`progression/app.py`/`freeplay/app.py`) drains and clears this list
once per frame, calling `sound.play(name)` for each entry. Menu navigation
is simpler and skips this indirection entirely -- `main.py`'s `run_menu()`
already branches on every relevant key/click directly, so it calls
`sound.play("menu_move")`/`sound.play("menu_select")` inline.

## The vocabulary

Sound events (`assets/sounds/{event}.wav` or `.ogg`):

| event | fires when |
|---|---|
| `move` | any move that actually slides somewhere (both modes) |
| `teleport` | a slide ends by stepping through a teleporter pad |
| `pellet` | a time pellet is collected |
| `gold` | a gold pellet is collected |
| `enemy_hit` | contact with an enemy |
| `key` | a key is collected, unlocking its door |
| `shield_block` | Bulwark blocks an enemy contact with a shield charge |
| `maze_complete` | a maze is cleared (goal reached) |
| `speed_bonus` | the speed bonus is awarded (alongside `maze_complete`) |
| `fail` | the run fails (time depleted) |
| `card_select` | a power-up or maze-modifier break card is chosen |
| `menu_move` | the main-menu cursor moves |
| `menu_select` | a main-menu option is confirmed |

Icon names (`assets/icons/{name}.png`):

| name | replaces |
|---|---|
| `player` | the player dot (both modes) |
| `goal` | the goal marker (both modes) |
| `pellet` | a time pellet |
| `gold` | a gold pellet |
| `enemy` | an enemy |
| `door_locked` | a locked door |
| `door_unlocked` | a door whose key has been collected |
| `key` | a still-uncollected key |

Not covered: teleporter pads (their per-pair colour coding *is* the visual
language; a single named icon doesn't fit that) and popups (text, not
icon-appropriate). Doors/keys get named icons for lock state, but which
key matches which door is still colour-only, same reasoning as
teleporters -- both are easy to extend into this same system later if
that changes.

See `assets/README.md` for the short version.

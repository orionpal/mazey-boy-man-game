# Assets

Drop files in here to replace the game's placeholder sounds/shapes — no
code changes needed. Everything in this directory is optional: with it
empty (as it ships), the game plays exactly as it always has (no sound,
primitive-shape entities). See `docs/assets.md` for the full design
writeup; this file is just the quick reference.

## `sounds/`

One file per event, named `{event}.wav` or `{event}.ogg`:

```
move.wav          teleport.wav       pellet.wav        gold.wav
enemy_hit.wav      wall_break.wav     laser.wav         stopwatch.wav
squeak.wav         maze_complete.wav  speed_bonus.wav   fail.wav
card_select.wav    menu_move.wav      menu_select.wav
```

Only add the ones you want to test — any event without a matching file
just stays silent.

## `icons/`

One file per entity, named `{name}.png` (any size; scaled to fit each
maze's current cell size):

```
player.png   goal.png   pellet.png   gold.png   enemy.png
```

Only add the ones you want to test — any entity without a matching icon
keeps rendering as its current primitive shape.

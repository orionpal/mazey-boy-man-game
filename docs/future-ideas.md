# Future Ideas Backlog

Mechanics considered while designing the rogue-like resource layer
(`docs/progression.md`) but deliberately deferred — not started, no
committed design, just captured so they aren't lost. Pull one into an
actual plan when it's time to build it.

## 1. Held-button stances

A button held down (rather than tapped) could switch the player into a
different "stance," giving arrow keys a different meaning while held —
e.g. a movement stance (today's only mode) vs. an action stance. This is
the main lever for giving the player more to do than just move, without
adding more permanently-bound keys.

## 2. Active perks

All current starter perks (`progression/perks.py`) are passive multipliers
applied automatically on pickup/contact. An active perk would instead be
triggered deliberately by the player (a keypress, or an action while in a
stance from #1) — e.g. a short-range attack, a temporary shield, a
teleport. Needs a decision on resource cost/cooldown model before it can
share the same `Perk`/`Build` machinery passive perks use today.

## 3. Limited wall-breaking

Let the player destroy a capped number of wall segments per run (or per
maze), opening a shortcut through a dead end or a long detour. Needs:
where the charges come from (a perk? a pickup, like pellets?), whether
broken walls persist for the rest of that maze only or the run, and how it
interacts with `player.slide()`'s stop-at-junction rule (breaking a wall
can turn a 2-neighbour corridor cell into a 3-neighbour junction on the
fly, mid-slide).

## 4. Maze generation changes to make wall-breaking mandatory

If #3 ships, later mazes could be generated with deliberately isolated
"vault" sections — reachable only by breaking a wall, not by any path
`generate_maze()`'s carving normally leaves open. This would need a
generation-time change (not just a post-process like `braid()`), since it
requires *withholding* a connection on purpose rather than adding one, and
a way to guarantee the vault is worth the wall-break cost (e.g. always
contains a large pellet cache or a guaranteed perk). Only makes sense once
#3 exists and has numbers attached to "how many breaks does a player
typically have banked by maze N."

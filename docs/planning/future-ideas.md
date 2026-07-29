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

## 2. Active perks -- DONE, see docs/progression.md

Shipped as the Q/W/E/R item system (`progression/shop/items.py`): Wall
Breaker, Laser, Stopwatch, Squeaky Toy, each triggered deliberately by the
player rather than passive, with their own charge-based resource model
(`Loadout`) sitting alongside passive `Perk`/`Build`. See "Perks & items:
the shop" in `docs/progression.md`.

## 3. Limited wall-breaking -- DONE, see docs/progression.md

Shipped as the Wall Breaker item (Q slot): 1 charge per pick, breaks one
non-border wall per activation, persists for the rest of the run (not
reset until death). Resolved the stop-at-junction interaction by reusing
`player.slide_path()`'s existing stop rule with a `break_wall` callback
hook, rather than inventing separate logic.

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

## 5. Trap doors, puzzle elements, collectors, portals, false wall


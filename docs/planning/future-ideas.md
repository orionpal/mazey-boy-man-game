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

## 2. Active perks -- DONE, then REMOVED, see docs/progression.md

Shipped as the Q/W/E/R item system (`progression/shop/items.py`): Wall
Breaker, Laser, Stopwatch, Squeaky Toy, each triggered deliberately by the
player rather than passive, with their own charge-based resource model
(`Loadout`) sitting alongside passive `Perk`/`Build`. Later removed
entirely in favour of keeping player controls to just movement (plus the
hold-SPACE combo) -- the shop's card pool was replaced with two passive
perks, Bulwark and Speedrunner. See "Perks: the shop, chosen every group"
in `docs/progression.md`.

## 3. Limited wall-breaking -- DONE, then REMOVED, see docs/progression.md

Shipped as the Wall Breaker item (Q slot): 1 charge per pick, breaks one
non-border wall per activation, persists for the rest of the run (not
reset until death). Resolved the stop-at-junction interaction by reusing
`player.slide_path()`'s existing stop rule with a `break_wall` callback
hook, rather than inventing separate logic. Removed along with the rest of
the active-item system (see #2) -- `slide_path()` no longer has a
`break_wall` hook.

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

Doors/keys -- DONE, see docs/progression.md and progression/augments/doors.py.
The rest of this bucket (puzzle elements, collectors, portals, false walls)
is still pure backlog.

## 6. Maze augments -- IN PROGRESS, see docs/progression.md and docs/maze-generation.md

A pool of generation-time maze modifiers, chosen every `AUGMENT_INTERVAL`
(10) mazes alongside the existing perk/item shop, each able to level up on
repeat picks (more/harder effect) and up to `MAX_ACTIVE_AUGMENTS` (4)
composable at once in a single run. Architecture: `progression/augments/`
(`Augment`, `AugmentContext`, `AugmentBuild`, `run_pipeline()`,
`offer_augment_cards()`) is a post-process pipeline over `generate_maze()`'s
output -- `generate_maze(cols, rows) -> grid` itself stays untouched, per
`docs/maze-generation.md`'s "Proposed near-term plan". Every future augment
plugs into the same registry (`ALL_AUGMENTS`) and composes through the same
pipeline without a rewrite.

Starting list:

- **Teleporting squares -- SHIPPED first**, `progression/augments/teleporters.py`.
  Seals a "pocket" of the maze off from the rest (re-walled boundary,
  verified with `bfs_reachable()` *and* a real-move simulation -- see
  `docs/progression.md`), reachable only via a linked teleporter pad pair.
  Level 1 places a handful of pairs with one mandatory; higher levels add
  more pairs and make more of them mandatory, each nested one pocket deeper
  than the last.
- **Doors & Keys -- SHIPPED second**, `progression/augments/doors.py`. A
  locked door blocks progress until its matching key (reachable before the
  door) is collected. Same rigor as teleporters -- seals a pocket's whole
  boundary except the door's own entrance, verifies solvability via a full
  sequential-unlock simulation -- but as a *gate* instead of a *shortcut*.
- **Multi-level mazes** -- built and shipped, then scrapped after
  playtesting (`progression/augments/multi_level.py`, removed). A pocket
  was sealed and its own interior recarved from scratch, linked to the
  parent region by two one-way stairs warps, with a per-floor camera crop
  so it rendered at full-viewport scale. Mechanically sound (forced-use
  guarantee, full test coverage) but reported as "pretty disorienting" in
  actual play -- scrapped for now rather than iterated on further. Not
  started again unless revisited.
- **Rotating maze** -- not started. The whole maze rotates on a fixed
  timer (every 2s), with a warning indicator shortly before each rotation
  fires. A rigid rotation of the grid + every entity position together is
  an isometry, so unlike the augments above it doesn't need its own
  forced-use/solvability verification machinery -- the maze is exactly as
  solvable after rotating as before.
- **Fog of war** -- not started. Only cells within the player's line of
  sight are visible; discovered cells stay revealed permanently by
  default, structured so that default is easy to swap later for something
  narrower (e.g. an item that grants permanent memory, rather than it
  being everyone's baseline).
- **Shifting room** -- not started. Pressure pads that shift certain walls
  when stepped on, changing maze connectivity at *runtime* -- unlike every
  augment above, which only ever mutates the grid once, at generation
  time.
- **Reverse controls** -- not started.
- **Lights out** -- not started.

The last four are pure backlog: naming them here reserves their place in
the augment pool and pacing, nothing more. Pull one into an actual design
(generation-time pass, run-time hook, rendering) when it's time to build it
-- teleporting squares is the concrete template for what that involves.


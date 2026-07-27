# Labyrinth Progression Mode

The core loop beyond a single maze: get through 100 mazes, gradually
bigger, in groups of 5 that stitch together seamlessly with a shop-card
choice between groups (a passive perk or an active Q/W/E/R item). A
rogue-like resource layer sits on top: time is one persistent budget
carried across the *whole* run, topped up by pellets and drained by
enemies (and, every 20th maze, a boss). Implemented in
`maze_game/progression/` (`run.py`'s `LabyrinthRun`, `shop/` for perks and
items, `entities/`), playable via `main.py` (this is now the default entry
point — see the "Renamed" note at the bottom). Everything below is a
**first guess to playtest**, not a balance pass — the constants live in
`constants.py` under "Labyrinth progression mode" and are meant to move.

## Dimensions: 9x9 -> 41x41, +2 every 5 mazes

Reused the free-play sidebar's existing bounds rather than inventing new
ones: starts at `MIN_DIMENSION` (9), steps by `DIMENSION_STEP` (2, i.e. one
click of the existing resize button) after every `LABYRINTH_GROUP_SIZE`
(5) mazes, caps at `MAX_DIMENSION` (41).

That reaches the cap at maze 81 (group 17 of 20) and holds there for the
last 20 mazes — difficulty ramps for the first 80% of the run, then
plateaus at max size for a sustained-challenge finish rather than growing
without bound. If 100 mazes feels like too long a ramp (or too short a
plateau), the knobs are `MIN_DIMENSION`/`DIMENSION_STEP`/`MAX_DIMENSION` in
`constants.py` — changing the step size directly trades off ramp length vs.
plateau length.

## Time: a persistent resource, not a per-maze limit

Earlier versions of this mode estimated a fresh time *limit* for every
maze (`estimate_time_limit()`, BFS'd from the shortest path and its turn
count) and reset the clock at the start of each one. That's gone: time is
now one persistent `TimeResource` (`progression/run.py`) the whole run
shares, starting at `LABYRINTH_START_TIME` (15.0s, cut down from an
original 75.0s after playtesting made the early game feel too padded) and
ticking down continuously regardless of which maze is active. Running out
ends the run, wherever you are — not "you failed maze 47," just "you ran
out of time." A fresh per-maze estimate never mattered for a shared pool,
so `estimate_time_limit()` and `count_direction_changes()` were deleted
outright along with `LABYRINTH_TIME_BASE`/`LABYRINTH_TIME_BASE_STEP`/
`LABYRINTH_TIME_PER_TURN` (their history, including the bug described
below, is kept here for context even though the code is gone).

Clearing a maze quickly now also earns a small amount of time back:
`SPEED_BONUS_TIME` (3.0s) is added if a maze finishes within a par time
derived from that maze's own BFS shortest-path length
(`SPEED_BONUS_SECONDS_PER_CELL`, 0.5s/cell) — set faster than the ~0.75s/
cell a careful player needs on average (see the measured table further
down), so it rewards genuinely brisk play, not just eventually getting
there.

### Pellets: the top-up

`spawn_pellets()` (`progression/entities/hazards.py`) places
`PELLET_TIME_VALUE` (1.0s) pickups on random open cells at maze generation
time, excluding the start and goal (and, on boss mazes, the boss doesn't
share a maze with pellets at all — see below). Count scales with
`PELLET_DENSITY * sqrt(open_cell_count)` (0.6, e.g. ~3 pellets at 9x9, ~17
at 41x41) rather than a flat fraction of cells, since traversal difficulty
grows closer to linearly with maze size while a flat fraction grows
quadratically. Collected pellets are removed — one-time pickups, not
standing hazards. A pellet sitting mid-corridor is still collectible even
though the player can't *stop* there: `move()` uses `player.slide_path()`
(returns every cell entered, not just the final stop) and checks contact
against every cell passed through, not just where the slide ends.

(`PELLET_TIME_VALUE` started at 4.0s and `PELLET_DENSITY` at 1.2 -- both
cut, after playtesting, to keep pellets a small, frequent trickle rather
than a handful of big top-ups, and to thin out the early, small mazes
specifically, which the sqrt-scaled count formula was flooding with
pellets relative to their size.)

### Enemies: persistent hazards, unlocked partway through

Starting at `ENEMY_UNLOCK_MAZE` (11), `spawn_enemies()` places a handful of
stationary hazards the same way pellets are placed (sqrt-scaled,
excluding start/goal/pellet cells too — the two never overlap). Contact
costs `ENEMY_TIME_PENALTY` (3.0s). Unlike pellets, enemies aren't removed
on contact — backtracking over the same one costs again.

Note this is now *larger* than a single pellet's value (1.0s) -- with
pellets cut to a small frequent trickle, one enemy hit costs several
pellets' worth of progress. Worth revisiting if that feels too punishing
in practice; the two were originally tuned in the opposite relationship
(enemy penalty deliberately below pellet value) back when a pellet was
worth 4.0s.

Extensibility was an explicit goal here: `Enemy` is a base class
(`pos`, `penalty`, `on_contact()`) plus a module-level `ENEMY_TYPES`
registry list that `spawn_enemies()` samples from. A new enemy type later
is one subclass + one line appended to the registry — nothing else in the
spawn/contact/rendering pipeline needs to change.

### The boss: every 20th maze

Every `BOSS_INTERVAL`-th maze (20, 40, ..., 100 —
`progression/entities/boss.py::is_boss_maze()`) replaces the normal goal
with a `Boss` instead: it occupies the maze's `farthest_reachable_cell`
position (the same tested placement goal cells normally use), and
defeating it — not reaching a cell — clears the maze. No pellets/enemies
share a boss maze; it's a focused fight.

The boss alternates every player move: idle turns (`move_count` 0, 2, 4,
...) leave it stationary, and contact then damages it
(`BOSS_BASE_DAMAGE`, scaled by the strength perk); active turns (1, 3, 5,
...) step it one cell toward the player (via the existing `shortest_path`
BFS — no new pathing code) and contact instead costs the player time, same
as a regular enemy. This is the literal reading of "moves every other
move": on the in-between turn it doesn't move, and that's the window to
land a hit. HP is `BOSS_BASE_HP + BOSS_HP_STEP * encounter_index` (5, 8,
11, 14, 17 across the 5 encounters) so later fights don't get relatively
easier as the strength perk compounds. `BOSS_INTERVAL` must land on a
group boundary (where a perk-choice break already exists) — enforced by an
assertion next to `is_boss_maze()`, so retuning one constant without the
other fails loudly instead of stranding a boss maze mid-group.

Deliberately *not* an `Enemy` subclass: a boss is the maze's win condition
with its own phase state, not "an enemy but bigger." The one bit of
behaviour it shares with a regular enemy (costing the player time) goes
through a small `apply_time_penalty()` helper instead of inheritance, so a
boss can never accidentally end up iterated alongside randomly-spawned
enemies.

### Perks & items: the shop, chosen every group

Every group-boundary break (mazes 5, 10, ..., 95) now offers 3 cards drawn
at random from the combined pool of passive perks and active items
(`progression/shop/__init__.py::offer_shop_cards()`, `random.sample` of
`ALL_PERKS + ALL_ITEMS`) instead of a bare "press SPACE to continue" or the
earlier guaranteed-all-3-perks behaviour — `LabyrinthRun.choose_shop_card()`
replaced the old `choose_perk()`; picking a card *is* the resume action.

**Perks** (`progression/shop/perks.py::ALL_PERKS`, unchanged starter set):
more pellet spawn frequency, more time per pellet, more damage to bosses.
Stacking is explicitly **multiplicative** (picking the same perk again
multiplies its multiplier by its magnitude again), a deliberate rogue-like
snowball. The accumulated `Build` is reset on death along with the time
resource (see "Failure" below) and shown in the left sidebar
(`progression/renderer.py`) as one square per acquired perk with a
stack-count badge; hovering shows the perk's description.

**Items** (`progression/shop/items.py::ALL_ITEMS`) are active abilities
bound to fixed Q/W/E/R slots, always drawn in the sidebar below the perk
squares — empty or filled — so the player can always see what's available
to acquire, not just what they have:

- **Q — Wall Breaker**: hold Q + an arrow key to slide as if holding
  spacebar (ignoring intersections), and if the wall it would stop at
  isn't a border wall, break through it and keep going. 1 charge per pick.
- **W — Laser**: fire in all 4 cardinal directions from the player's
  position (each ray runs to its own wall), destroying any enemy hit. 1
  charge per pick.
- **E — Stopwatch**: pause the time resource and block movement for
  `STOPWATCH_PAUSE_SECONDS` (5.0s). 1 charge per pick — charges are the
  limited resource, every use pauses the same fixed length (not a
  duration that scales with picks).
- **R — Squeaky Toy**: does nothing except flash a "Squeak!"
  acknowledgment. No charges — unlimited once acquired.

Unlike perks' shared `EFFECTS` dispatch table, each item's effect is a
dedicated `LabyrinthRun` method (`_try_break_wall`, `activate_laser`,
`activate_stopwatch`, `activate_squeaky_toy`) — four genuinely different
mechanics (grid mutation, enemy removal, a timed pause, nothing) didn't
have a shared abstraction worth forcing. `Loadout` (`shop/items.py`) tracks
charges the same shape as `Build` tracks perk picks, reset on death too.

Selectable by arrow keys + space (`LabyrinthRun.move_shop_cursor(delta)`
moves a wrapping cursor across the 3 cards, `choose_shop_card(shop_cursor)`
confirms it), by number keys 1/2/3, or by clicking a card directly — all
three land on the same `choose_shop_card(index)` call.

The break genuinely pauses the clock: `update()` skips
`TimeResource.tick()` entirely while `on_break`, but the tick reference
point (`_last_tick`) still needs an explicit `TimeResource.resync()` call
in `choose_shop_card()` once the break ends — otherwise the very next
`tick()` computes its delta against a timestamp from *before* the break
started, charging the whole break duration in one lump the instant play
resumes (this shipped as a bug before being caught in playtesting: it
looked like "the timer didn't stop for the perk screen," just deferred by
a frame). The Stopwatch item's pause reuses the exact same
`TimeResource.resync()` fix in `update()` once its pause elapses.

Measured empirically (30 trials per size, actual `generate_maze` output),
back when time limits were per-maze-estimated rather than a shared pool —
kept here since it's still the reference for how traversal difficulty
scales with size, which the pellet/enemy density formulas above lean on:

| size | avg shortest-path cells | avg key presses (turns) |
|---|---|---|
| 9x9 | 14.6 | 5.8 |
| 21x21 | 47.2 | 17.3 |
| 41x41 | 99.1 | 36.3 |

### Bug: forced stops at junctions weren't counted (found via playtesting)

Two related bugs, both found by actually playing the game and reported as
"sometimes the maze seems impossible to finish":

1. **Goal could be unreachable at all.** `farthest_reachable_cell` picked
   whichever cell BFS visited last, with no regard for whether the sliding
   mechanic could ever land on it. `player.slide()` only stops at a wall
   ahead or a junction (3+ open neighbours) — a cell with exactly 2 open
   neighbours (a mid-corridor or turn cell) can never be a stopping point;
   the player always slides straight through it. If BFS's "farthest" cell
   happened to be one of those, the goal was **structurally impossible to
   reach**, confirmed in ~18% of generated mazes (500-trial measurement).
   Fixed by restricting "farthest" to cells the sliding mechanic can
   actually stop on (`maze.py::farthest_reachable_cell`).

2. **Time limits were under-counted.** `count_direction_changes` only
   counted actual turns, but `slide()` force-stops at *every* junction it
   enters — even one the shortest path runs straight through without
   turning — because the stop check only looks at open-neighbour count, not
   at where the path intends to go next. That forced stop needs its own
   key press to continue, which pure direction-change counting missed,
   under-estimating the time limit on any maze whose shortest path passes
   through such a junction. Fixed by also counting forced stops (this
   function has since been deleted along with the per-maze time-limit
   model it served — see "Time: a persistent resource" above — but the bug
   it fixed, and why, is still worth keeping on record).

Both are covered by regression tests, including an end-to-end one
(`test_maze_is_actually_completable_via_sliding`) that doesn't just check
a path exists on paper — it derives the real key-press sequence and runs it
through the actual `slide()` function, confirming the player lands exactly
on the goal.

## Movement combos: hold a modifier, then an arrow key

A plain arrow press stops at the first intersection reached (`slide_path`'s
default `junction_stop_count=1`) — the base feel described in
`docs/controls-audit.md`. One combo, checked in `main.py` against
`pygame.key.get_pressed()` at the moment the arrow key is pressed, extends
that:

- **Hold spacebar + an arrow key**: ignore intersections entirely, running
  all the way to the next wall (`junction_stop_count=None`).

(An earlier version also had "hold a number key (1-9) + an arrow key" to
blow through the first N-1 intersections and stop at the Nth — dropped in
favour of the Q/W/E/R item slots below, freeing the number row for shop-card
selection instead. `slide_path`'s general `junction_stop_count=N` contract
still exists and is still tested; it's just no longer bound to a key.)

This is just `player.slide_path()`'s existing wall-vs-junction stop rule
generalized to "stop after the Nth junction" instead of hardcoded at the
1st (`None` behaves as "never"). `LabyrinthRun.move()` passes the count
straight through, so pellet/enemy/boss contact resolution (which already
checks every cell in the returned path, not just the final stop) works
identically for combo moves — a longer path is still just a longer path.

**Wall Breaker (item, Q slot)** reuses the exact same mechanism from the
other direction: it always slides with `junction_stop_count=None` (as if
holding spacebar) but additionally passes a `break_wall` callback into
`slide_path` — when the slide would stop at a wall, the callback gets a
chance to open it (if it's not a border wall and a charge is available)
and let the slide continue through. `slide_path` itself stays maze/charge-
agnostic; `break_wall` owns all of that policy.

## Groups: seamless within, a perk choice between

Within a group of 5, finishing a maze immediately starts the next one --
no pause, matching "they stitch together seamlessly." After the 5th maze
in a group, `on_break=True`: the timer stops advancing and the maze view
is replaced with 3 shop cards, each a perk or an item (see "Perks & items"
above) until `choose_shop_card(index)` is called (click a card, or 1/2/3 in
`main.py`), at which point the chosen card is applied and the next maze
generates at the new (possibly larger) size.

## Failure: full reset, not a retry

Running out of the shared time resource ends the whole run back at maze 1
(`restart()`) — both the time budget and the accumulated perk build reset
— rather than retrying that one maze or losing progress only within the
current group. This was pitched as a maze **rogue-like**, and permadeath-style
stakes are the genre's whole tension — a softer failure mode (retry in
place, or only lose the current group) is a small change in
`LabyrinthRun.update()`/`restart()` if full-reset turns out to feel too
punishing in practice. Flagging this as the single decision here most
likely to need adjusting.

## Not built yet (deliberately out of scope for this first pass)

- No persistent history/leaderboard for labyrinth runs (unlike free-play's
  `run_history.json`) — didn't want to lock in a record schema before the
  numbers above are even validated by playing it.
- `main.py` is a minimal, separate entry point rather than integrated into
  free-play's (`mvp_main.py`) sidebar UI — free-play's sidebars (dimension
  adjustment, history log) don't apply to a structured progression run, and
  building a unified shell felt premature before knowing whether this
  pacing is even fun. Worth merging once it is.
- See `docs/planning/future-ideas.md` for a longer backlog of mechanics
  considered but deliberately deferred (stances, limited wall-breaking as a
  maze-gen requirement, and others now partially overlapping with the
  Q/W/E/R items above).

## Renamed: this is now the default `main.py`

After a first playtest, this became the primary mode: what was `main.py`
(single maze, adjustable size, no timer) is now `mvp_main.py`, and what was
`progression_main.py` is now `main.py`. The playtest also surfaced that the
maze counter (`Maze N/100`) and the "All 100 mazes complete!" win screen
already existed in this file but went unnoticed — the actual issue was
running the wrong entry point, not missing features.

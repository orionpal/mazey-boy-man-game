# Labyrinth Progression Mode

The core loop beyond a single maze: get through 100 mazes, gradually
bigger, with two break cadences layered on top of each other -- a passive
perk choice every 5 mazes, and a maze-modifier (augment) choice every 10
mazes. A rogue-like resource layer sits underneath: time is one persistent
budget carried across the *whole* run, topped up by pellets and drained by
hazards. Implemented in `maze_game/progression/` (`run.py`'s
`LabyrinthRun`, `shop/` for perks, `augments/` for maze modifiers,
`entities/`), playable via `main.py` (this is now the default entry point
— see the "Renamed" note at the bottom). Everything below is a **first
guess to playtest**, not a balance pass — the constants live in
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

### Milestone mazes: a one-off dimension spike

An earlier version of this mode replaced the goal with a boss fight every
`MILESTONE_INTERVAL`-th maze (30, 60, 90), plus always the final maze --
that's gone (see git history if curious), and in its place those same
maze indices (`run.py::is_milestone_maze()`, same cadence the boss used)
get a one-off dimension *spike* instead: noticeably bigger than the normal
ramp would give that specific maze index, reverting to the regular ramp
on the very next maze. Otherwise it's a totally ordinary maze -- a real
goal, normal pellet/hazard/gold spawning, no special win condition.

`dimensions_for_maze()` computes the normal ramp size first, then on a
milestone maze adds `MILESTONE_DIMENSION_BOOST` (16) on top, capped
separately at `MILESTONE_MAX_DIMENSION` (61, higher than the normal run's
`MAX_DIMENSION`) -- a plain `min(normal_size + boost, MAX_DIMENSION)` would
have nowhere left to jump to on the later milestones (90, 100), which
already sit at `MAX_DIMENSION` under the normal ramp alone. Nothing else
needed to change for this: the par-time BFS, the fixed-viewport renderer,
and the pellet/hazard/gold density formulas already all scale purely from
`cols`/`rows`, so a milestone maze naturally gets a proportionally longer
time budget and more hazards along with its bigger footprint.

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
time, excluding the start and goal. Count scales with
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

### Hazards: persistent, unlocked partway through

Starting at `HAZARD_UNLOCK_MAZE` (11), `spawn_hazards()` places a handful of
stationary hazards the same way pellets are placed (sqrt-scaled,
excluding start/goal/pellet cells too — the two never overlap). Contact
costs `HAZARD_TIME_PENALTY` (3.0s). Unlike pellets, hazards aren't removed
on contact — backtracking over the same one costs again.

Note this is now *larger* than a single pellet's value (1.0s) -- with
pellets cut to a small frequent trickle, one hazard hit costs several
pellets' worth of progress. Worth revisiting if that feels too punishing
in practice; the two were originally tuned in the opposite relationship
(hazard penalty deliberately below pellet value) back when a pellet was
worth 4.0s.

Extensibility was an explicit goal here: `Hazard` is a base class
(`pos`, `penalty`, `on_contact()`) plus a module-level `HAZARD_TYPES`
registry list that `spawn_hazards()` samples from. A new hazard type later
is one subclass + one line appended to the registry — nothing else in the
spawn/contact/rendering pipeline needs to change.

**Ramped in, not full density from the first maze**: `spawn_hazards()`'s
sqrt-scaled formula alone put ~4-5 hazards on the very first hazard maze --
a spike right as the mechanic is introduced, not a gradual "here's a new
threat" moment. `hazards.py::hazard_density_ramp(maze_index)` scales the
density down to `HAZARD_RAMP_START_MULTIPLIER` (0.25, ~1 hazard) on
`HAZARD_UNLOCK_MAZE` itself, climbing linearly back to full density over
`HAZARD_RAMP_MAZES` (10) mazes. Passed into `spawn_hazards()` as
`density_multiplier` rather than changing `HAZARD_DENSITY` itself, so the
steady-state curve (already tuned) is untouched -- only the introduction is
softened.

### Feedback popups: "+Xs"/"-Xs" wherever the clock actually changes

A pellet, a hazard, and a maze-clear speed bonus all move the shared time
resource, but previously the only feedback was the HUD number itself
ticking -- easy to miss mid-slide, and not obviously *tied* to the pellet/
hazard the player just passed through. `LabyrinthRun.add_popup(pos, text,
color)` (called from `Pellet.on_contact`, the shared `apply_time_penalty()`
helper, and the speed-bonus branch of `update()`) queues a `Popup(pos,
text, color, created_at)`; `renderer.py::_draw_popups()` renders each one
at its cell, drifting upward (`POPUP_RISE_PIXELS`) over its lifetime
(`POPUP_DURATION_SECONDS`, 1.0s) before it's pruned. Colour matches the
thing that caused it (`C_PELLET`/`C_HAZARD`), except the speed bonus, which
gets its own `C_SPEED_BONUS` so a maze-clear bonus reads as something
extra rather than "a big pellet."

`apply_time_penalty()` takes a required `pos` parameter for this (the
hazard's current position) -- `Hazard.on_contact` already had a `self.pos`
to pass.

### Perks: the shop, chosen every group

Every group-boundary break (mazes 5, 10, ..., 95) offers cards drawn at
random from the perk pool (`progression/shop/__init__.py::offer_shop_cards()`,
`random.sample` of `ALL_PERKS`, capped at whatever's actually in the pool)
instead of a bare "press SPACE to continue" — `LabyrinthRun.choose_shop_card()`
applies the pick; picking a card *is* the resume action.

Movement is deliberately just arrow keys (plus the hold-SPACE run-to-wall
combo, see "Movement combos" below) — there is no separate active-item
system with its own keybinds. `progression/shop/perks.py::ALL_PERKS` holds
exactly two perks, and stacking is explicitly **additive** (picking the
same perk again adds another charge/bonus unit, not a multiplier) since
both grant a count, not a rate:

- **Bulwark** (`hazard_shield`): each maze, ignore the first N hazard
  contacts, where N is the perk's level (total times picked).
  `LabyrinthRun._begin_maze()` refills `shield_charges_remaining` to
  `Build.hazard_shield_charges_per_maze` every maze; `Hazard.on_contact()`
  consumes a charge and fully blocks the hit (a "Shielded!" popup, the
  `shield_block` sound event) before falling back to the normal
  time-penalty path once charges run out.
- **Speedrunner** (`gold_rush`): bonus gold on a maze cleared within its
  par-time threshold, on top of the existing unconditional `SPEED_BONUS_TIME`
  (see "Feedback popups" above) — the two compound, not replace each other.
  `LabyrinthRun.update()`'s speed-bonus branch adds `Build.gold_rush_bonus`
  gold, persists it immediately (same pattern as `GoldPellet.on_contact()`),
  and shows a second "+Ng" popup alongside the time-bonus one.

The accumulated `Build` is reset on death along with the time resource (see
"Failure" below) and shown in the left sidebar (`progression/renderer.py`)
as one square per acquired perk with a stack-count badge; hovering shows
the perk's description.

Selectable by arrow keys + space (`LabyrinthRun.move_break_cursor(delta)`
moves a wrapping cursor across the offered cards, `choose_break_card(break_cursor)`
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
a frame).

Measured empirically (30 trials per size, actual `generate_maze` output),
back when time limits were per-maze-estimated rather than a shared pool —
kept here since it's still the reference for how traversal difficulty
scales with size, which the pellet/hazard density formulas above lean on:

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
blow through the first N-1 intersections and stop at the Nth, and a
Q/W/E/R active-item system with its own dedicated key handling (a Wall
Breaker item reused this same `junction_stop_count=None` mechanism plus a
`break_wall` callback into `slide_path` to open walls mid-slide) — both
dropped later in favour of keeping player controls to just movement.
`slide_path`'s general `junction_stop_count=N` contract still exists and
is still tested; it's just no longer bound to a key.)

This is just `player.slide_path()`'s existing wall-vs-junction stop rule
generalized to "stop after the Nth junction" instead of hardcoded at the
1st (`None` behaves as "never"). `LabyrinthRun.move()` passes the count
straight through, so pellet/hazard contact resolution (which already
checks every cell in the returned path, not just the final stop) works
identically for combo moves — a longer path is still just a longer path.

## Groups: seamless within, breaks stack sequentially between

Within a group of 5, finishing a maze immediately starts the next one --
no pause, matching "they stitch together seamlessly." After the 5th maze
in a group, `on_break` becomes true (now a computed property --
`break_kind is not None`): the timer stops advancing and the maze view is
replaced with shop cards, each a perk (see "Perks: the shop, chosen every
group" above) until `choose_break_card(index)` is called (click a card, or 1/2/3
in `main.py`), at which point the chosen card is applied.

That alone is unchanged from before. What's new: a maze index can be a
boundary for more than one break at once (10 is a multiple of both
`LABYRINTH_GROUP_SIZE` and `AUGMENT_INTERVAL`). Rather than one break replacing another, they
**stack sequentially** — `LabyrinthRun._breaks_due_after(maze_index)`
builds the ordered list (`["shop", "augment"]` when both apply), and
`_resume_after_break()` pops one at a time: pick a shop card, and instead
of immediately starting the next maze, the modifier-choice screen replaces
it if one is queued; only once the queue is empty does the clock resync
(**once**, not once per break -- see the resync note in "Perks: the shop,
chosen every group" above; the same staleness bug it fixes could otherwise
resurface per-break)
and the next maze actually begin. `choose_shop_card`/`choose_augment_card`
are the two concrete pick handlers; `choose_break_card`/`move_break_cursor`
are the kind-agnostic entry points `main.py` and the renderer actually call,
dispatching on `run.break_kind`.

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

What *doesn't* reset on failure: gold and owned meta-progression upgrades
(see "The Base" below) — the whole point of a persistent currency layered
on top of a rogue-like's full-reset one is that death isn't a total loss.

## The Base: meta-progression between runs

Gold (`GoldPellet`, `docs/assets.md`) used to be collect-and-display only.
`progression/meta/` gives it a purpose: the Base is a screen the player
visits between runs (`progression/app.py::run_progression_mode()` — always
precedes a run, and R after a fail/complete screen now routes back into it
instead of restarting in place) where gold buys permanent passive
upgrades. Two ship today: **Prospector's Eye** (+10% pellet time/level) and
**Thick Skin** (-10% hazard damage/level), each repurchasable at an
increasing gold cost (`cost_base + cost_step * level`).

**Deliberately reuses `shop/perks.py`'s stacking machinery rather than
inventing a parallel one.** A meta upgrade (`MetaUpgrade`) has the same
`effect_key`/`magnitude` shape as an in-run `Perk` — `MetaProgress.seed_build()`
builds a fresh `Build` and applies each owned upgrade's effect through the
*exact* `EFFECTS` dict `Build.acquire()` already uses, once per owned
level. `LabyrinthRun.__init__`/`restart()` call this instead of a bare
`Build()`, so owned upgrades apply before the run even starts and compound
underneath whatever gets picked in-run. `Build` gained
`hazard_resistance_multiplier` for Thick Skin's effect (`Hazard.on_contact`
now multiplies its penalty by it) — no in-run `Perk` uses that
`effect_key`, but it lives alongside `Build`'s other fields for
consistency. Same goes for `pellet_value_multiplier`/
`pellet_frequency_multiplier` (Prospector's Eye still drives the former;
no in-run perk sets either away from 1.0 anymore since Keen Eye/Rich Vein
were replaced by Bulwark/Speedrunner, but `spawn_pellets()`/
`Pellet.on_contact()` still read them directly).

**Persistence**: gold stays owned by `hazards.py`'s existing
`load_gold_total()`/`save_gold_total()` (`gold.json`) — `MetaProgress`
reads/writes it via those same functions rather than duplicating gold
persistence. Owned upgrade levels get their own sibling file,
`meta_upgrades.json`, loaded fresh every time the Base is shown so it
always reflects whatever the just-finished run left behind.

## Seeded runs

`LabyrinthRun(seed=...)` — every RNG-consuming call the run makes
(`generate_maze`, `spawn_pellets`/`spawn_hazards`, `offer_shop_cards`,
`offer_augment_cards`, and the augment pipeline's own placement logic) is
threaded through one `self.rng = random.Random(self.seed)` instance rather
than the bare global `random` module every one of those functions still
defaults to when called without an explicit `rng`. Chose instance-threading
over the simpler "just call `random.seed(n)` once at run start" approach:
both need touching every RNG call site once, but instance-threading
survives future reordering of those calls within a run (a global reseed
wouldn't — anything else touching global `random` state, a debug tool,
pytest-xdist, a future feature, would silently perturb it), for the same
amount of work.

No seed is required — `LabyrinthRun()` picks one via `_random_seed()`
(deliberately drawn from the bare global `random`, not an `rng` instance,
since choosing *which* seed to start with is inherently a one-off,
non-reproducible decision, not part of the reproducible sequence a seed is
meant to pin down) and stores it on `run.seed`, shown in the HUD so it's
discoverable, not just internally reproducible. `restart()` picks a fresh
seed by default (a genuinely new run, not a replay) unless called as
`restart(same_seed=True)`.

**Scope**: seeding governs maze layout, entity placement, shop/augment
offers — everything that consumes `self.rng`. It does **not** make real-time
play itself deterministic: `TimeResource` is driven by `time.monotonic()`
(wall-clock), and player input is, well, the player. Two runs with the same
seed generate byte-for-byte identical content and offers; they don't replay
identical outcomes unless the input is also identical.

## Maze augments

Generation-time maze modifiers — the first being teleporting squares —
chosen every `AUGMENT_INTERVAL` (10) mazes, stacked on top of the existing
group-boundary shop break (see "Groups" above). Up to `MAX_ACTIVE_AUGMENTS`
(4) can be active in one run at once; picking an augment already active
levels it up instead of doing nothing (same shape as perk stacking:
`AugmentBuild.picks[id]` *is* the level, mirroring `shop/perks.py::Build`).

**Architecture** (`progression/augments/`): `Augment.apply(ctx)` is the
only shared hook (deliberately no generic `contact()`/`render()` hook --
mirrors the existing precedent in `hazards.py`/`renderer.py` of bespoke
methods over a forced-fit abstraction). `AugmentContext` bundles
the mutable state a pipeline pass works against (`grid`, `goal`, `rng`,
`level`, `reserved` cells, `frontier`, an `extra` dict for augment-specific
output). `run_pipeline()` applies every active augment in **registry
order** (`ALL_AUGMENTS`), not pick order — a hard contract: augment N must
assume augment N-1 may have already mutated the grid/reserved/frontier
state, and fold its own effect on top rather than starting fresh. Called
from `LabyrinthRun._begin_maze()` *after* `generate_maze()` returns --
`generate_maze(cols, rows) -> grid` itself stays untouched (see
`docs/maze-generation.md`'s "Proposed near-term plan"), so the pipeline is
a post-process, not a change to the generator's own interface.

**Composing multiple augments' mandatory content — `ctx.frontier`.**
Every augment below places some content that's optional (decorative) and,
at higher levels, some that's *mandatory* — required to reach the goal.
Getting that "required" guarantee to actually hold once *more than one*
augment is active turned out to be its own hard problem, found and fixed
directly (not just theorized): each augment used to independently pick its
own mandatory chain's root (`ctx.start`, hardcoded) and, once done,
unconditionally overwrite `ctx.goal` to sit inside its own chain — so
whichever augment happened to run *last* in `ALL_AUGMENTS` silently won
ownership of the goal, and every *other* active augment's "mandatory"
pocket/gate became a real, sealed, reachable, but no-longer-required side
room. `ctx.frontier` fixes this: a single shared "current end of the
mandatory chain," seeded at `ctx.start`, that every augment's mandatory
placement (a) roots its own search at (instead of `ctx.start`) and (b)
advances to wherever its own chain ends, before returning — so Teleporters
and Doors nest their mandatory content behind each other, in whatever
order the player actually picked, instead of running independent,
competing chains. Final goal placement moved out of the individual
augments entirely, into one shared step (`run_pipeline()`'s
`_finalize_goal()`, run once after the whole loop) that places the goal
via a farthest-cell search rooted at the final `ctx.frontier` —
deliberately *not* a naive real-move walk from a link's own endpoint,
since a mandatory teleporter pair's own bidirectional link (or a mandatory
door, once its key is “found”) can otherwise leak the search straight back
out to the near side; see `_finalize_goal()`'s and
`_movement.py::farthest_within()`'s docstrings for the exact mechanism.
`tests/progression/augments/test_composition.py` is the regression
coverage: with both augments active, disabling *either one's* mandatory
content individually (with the other left fully intact) must break
solvability — the property that would have caught this bug, which a
weaker "is everything reachable with it all intact" check does not.

**Nesting a mandatory chain used to be silently impossible.** A second bug,
found directly while building the fix above (not previously known):
placing a mandatory pocket *inside* an already-placed one's own sealed
pocket requires rooting the next search there — but every candidate search
also unconditionally rejected any candidate touching `ctx.reserved`, which
already contains the *entire* enclosing pocket (reserved on purpose, so a
*different*, unrelated augment can never overlap it) — so a nested
search's candidate pool was always empty. Confirmed by running the
original code directly: 0 of 50 random seeds ever placed two nested
mandatory teleporter pairs at a level whose formula asks for it. Fixed
with `nested_local_forbidden()` (`augments/__init__.py`): once a search is
confirmed to already be rooted inside a sealed pocket, it drops the
blanket `ctx.reserved` check (the whole point of nesting is to further
subdivide that same, already-isolated interior) and instead avoids only
the individual special cells already placed there — including, for a
same-call chain still in progress, cells `ctx.extra` hasn't been written
back with yet.

`offer_augment_cards()` mirrors `offer_shop_cards()`'s sampling shape:
below the cap, prefer offering not-yet-active augments (topped up with
active ones if too few new ones exist to fill the offer); at or above the
cap, every offer is drawn only from the active set, so a pick always levels
one up.

### Teleporting squares (`progression/augments/teleporters.py`)

Guarantees the goal is unreachable from the start via ordinary movement
alone: seals a connected "pocket" of the maze behind a re-walled boundary,
linked back to the main region only by a teleporter pad pair (step onto
either pad, warp to its partner, and vice versa). Level 1 places
`TELEPORT_PAIR_COUNT_BASE` (3) pairs with `TELEPORT_MANDATORY_COUNT_BASE`
(1) of them load-bearing; each level adds more pairs and more mandatory
ones (capped at `TELEPORT_PAIR_COUNT_MAX`/the pair count), each successive
mandatory pair nested one pocket deeper than the last (walking into pocket
1's exit and searching *from there* naturally confines the next pocket to
pocket 1's now-isolated interior — nesting falls out for the pipeline for
free, no extra bookkeeping needed).

**Pocket selection — the actual hard part.** An arbitrary same-size
connected blob of cells is usually the *wrong* thing to seal off: mazes are
close to spanning trees (only sparse extra edges from `braid()`), so a
random blob is typically a *bridge* — sealing it fragments some large,
unrelated part of the maze along with it. Fixed by computing a BFS spanning
tree from the current start and sealing off a **pendant subtree** instead
(a node's full descendant closure) — provably safe by construction, since
everything outside that closure still has its own untouched tree-path back
to the root.

**Real-move verification — the second hard part.** Even a geometrically
correct pocket seal isn't enough: a teleporter pad forces an *unconditional*
redirect the instant it's entered — not an optional extra edge the way
plain grid-adjacency reachability (`bfs_reachable`, or `shortest_path`'s
`extra_edges`) models it. A pad placed on what would otherwise be a
load-bearing junction can look perfectly connected to that kind of check
and still make the maze unsolvable, by forcibly yanking the player away
from it on every approach (found by an end-to-end test that walks the
*actual* movement-state graph, not just checking fine-grained cell
reachability — the exact class of bug this project has hit before with
`farthest_reachable_cell`, see "Bug: forced stops at junctions" above).
Fixed with `real_move_reachable()` (now in the shared
`progression/augments/_movement.py`, promoted there once a second augment
needed the same technique): a BFS over the real `player.slide_path()`-
produced state graph, used to verify — and reject-and-retry against a
different pocket/pad placement if it fails — every mandatory *and*
decorative pad before committing it. This is the concrete first
application of the "generate, then BFS-connectivity-check, retry/patch on
failure" pattern `docs/maze-generation.md` anticipated would eventually be
needed for topology-changing tiles.

`slide_path()` resolves a teleport by stopping immediately at the linked
cell (no momentum carried through) — the same "you always land exactly on
a stopping cell" model already used for junctions, and it trivially avoids
needing extra state to guard against bouncing back and forth through a
pair.

### Doors & Keys (`progression/augments/doors.py`)

The second augment, shipped alongside teleporting squares: a locked door
blocks progress until its matching key — placed somewhere reachable
*before* the door — is collected, unlocking it permanently for the rest of
the maze. Same rigor and much of the same machinery as teleporters (level
scaling, pendant-subtree pocket selection, real-move verification), but as
a *gate* instead of a *shortcut*, which turned out to need two fixes
teleporters never had to make.

**A locked door's own cell stays grid-open, gated only behaviorally.**
`player.slide_path()` gained a `door_locked` hook, checked the same way
`teleport` already is, that stops the slide one cell short — exactly like
an unbreakable wall — without ever mutating `grid[y][x]`. This means
`shortest_path()`/`farthest_reachable_cell()`/`bfs_reachable()` all keep
treating a door cell as ordinarily passable, with zero special-casing —
sidestepping the exact class of crash a real-wall door would risk
(`shortest_path()` finding no path to a target that's genuinely
unreachable before any key is collected, the same bug class recently fixed
for the now-removed boss's pathing).

**But a single gated cell alone isn't a reliable cut vertex.** `braid()`
adds loop-forming extra edges by design, and one very often bypasses a
lone gated cell — found the hard way, as this augment's own test suite
failing at a 100% rate before the fix. So placement physically re-walls
the *entire* boundary of the chosen pocket (`seal_pocket()`, the same
technique teleporters uses for its sealed pockets) except the one crossing
into the door cell itself, which stays open. That crossing becomes the
sole way in or out once sealed, so behaviorally gating just that one
(still grid-open) cell now genuinely gates the whole pocket.

**Multi-door placement needs a *joint* solvability check, not pairwise
ones.** A subtler bug survived the fixes above: sealing a *later* door's
pocket boundary could, in rare cases, sever the *only* remaining path to
an *earlier* door's key (a `braid()` loop that used to route through
territory that's now sealed off). Checking "is the goal still reachable
with just this one door locked" missed it, since that check never
re-examined earlier doors' keys. Fixed with `sequentially_reachable()`: a
full simulation that starts with every door in the maze locked, repeatedly
collects whatever key becomes reachable and unlocks its door, and repeats
until nothing more unlocks — the actual ground-truth "can the player
finish this maze" answer, verified after *every* placement attempt (not
just once at the end).

## Not built yet (deliberately out of scope for this first pass)

- No persistent history/leaderboard for labyrinth runs (unlike free-play's
  `run_history.json`) — didn't want to lock in a record schema before the
  numbers above are even validated by playing it.
- ~~`main.py` is a minimal, separate entry point rather than integrated into
  free-play's (`mvp_main.py`) sidebar UI~~ — **done**: `main.py` now opens
  to a menu (`maze_game/menu.py`/`menu_renderer.py`) offering both modes.
  Each mode's event loop was factored out into its own package
  (`progression/app.py::run_labyrinth()`, `freeplay/app.py::run_freeplay()`)
  so `main.py`'s menu and `mvp_main.py`'s standalone launch share the exact
  same loop rather than duplicating it — free-play's sidebars (dimension
  adjustment, history log) still don't apply to a structured progression
  run, so this is a shared *launcher*, not a merged UI shell; each mode
  still owns its own renderer/layout.
- See `docs/planning/future-ideas.md` for a longer backlog of mechanics
  considered but deliberately deferred (stances, limited wall-breaking as a
  maze-gen requirement, and others -- an earlier version of this backlog
  also spawned a Q/W/E/R active-item system, later removed in favour of
  Bulwark/Speedrunner above).

## Renamed: this is now the default `main.py`

After a first playtest, this became the primary mode: what was `main.py`
(single maze, adjustable size, no timer) is now `mvp_main.py`, and what was
`progression_main.py` is now `main.py`. The playtest also surfaced that the
maze counter (`Maze N/100`) and the "All 100 mazes complete!" win screen
already existed in this file but went unnoticed — the actual issue was
running the wrong entry point, not missing features.

# Labyrinth Progression Mode

The core loop beyond a single maze: get through 100 mazes. Gradually
bigger, each with a time limit, in groups of 5 that stitch together
seamlessly with a break-and-resume prompt between groups. Implemented in
`maze_game/progression.py` (`LabyrinthRun`), playable via `main.py` (this
is now the default entry point — see the "Renamed" note at the bottom).
Everything below is a **first guess to playtest**,
not a balance pass — the constants live in `constants.py` under "Labyrinth
progression mode" and are meant to move.

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

## Time limit: measured, not guessed

Rather than a fixed lookup table per size, `estimate_time_limit()` computes
the limit from the **actual generated maze**: BFS the shortest path from
start to goal, count direction changes needed under this game's sliding
movement (`count_direction_changes` — a straight corridor of any length is
one key press, so cells traveled isn't the right unit; turns are), then:

```
time_limit = LABYRINTH_TIME_BASE + LABYRINTH_TIME_PER_TURN * turns_on_shortest_path
```

This adapts to each specific maze's real difficulty (a lucky easy layout at
a given size gets less time than an unlucky winding one), rather than
averaging over size and getting it wrong in both directions half the time.

Measured empirically (30 trials per size, actual `generate_maze` output)
before picking the constants:

| size | avg shortest-path cells | avg key presses (turns) |
|---|---|---|
| 9x9 | 14.6 | 5.8 |
| 21x21 | 47.2 | 17.3 |
| 41x41 | 99.1 | 36.3 |

(Updated after a bug fix — see "Bug: forced stops at junctions weren't
counted" below. The key-press counts here are higher than the first
version of this table.)

With `LABYRINTH_TIME_BASE=10.0` and `LABYRINTH_TIME_PER_TURN=2.0`, that
puts the *average* maze at roughly 22s (9x9) up to 83s (41x41) — 2 seconds
per turn is a generous per-press budget (covers reading the junction and
reacting, not just the keypress itself), meant to be comfortably
completable by a careful player while still creating real time pressure
for a wandering one. Almost certainly the first thing worth retuning after
playing it.

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
   through such a junction. Fixed by also counting forced stops
   (`progression.py::count_direction_changes` now takes the grid and checks
   `_open_neighbour_count(...) >= 3` at each path cell, not just whether the
   direction changed).

Both are covered by regression tests, including an end-to-end one
(`test_maze_is_actually_completable_via_sliding`) that doesn't just check
a path exists on paper — it derives the real key-press sequence and runs it
through the actual `slide()` function, confirming the player lands exactly
on the goal.

## Groups: seamless within, break between

Within a group of 5, finishing a maze immediately starts the next one --
no pause, matching "they stitch together seamlessly." After the 5th maze
in a group, `on_break=True`: the timer stops advancing and nothing happens
until `resume()` (SPACE in `main.py`), at which point the next
maze generates at the new (possibly larger) size.

## Failure: full reset, not a retry

Timing out on any maze ends the whole run back at maze 1 (`restart()`),
rather than retrying that one maze or losing progress only within the
current group. This was pitched as a maze **rogue-like**, and permadeath-style
stakes are the genre's whole tension — a softer failure mode (retry in
place, or only lose the current group) is a one-line change in
`LabyrinthRun.update()`/`_advance()` if full-reset turns out to feel too
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

## Renamed: this is now the default `main.py`

After a first playtest, this became the primary mode: what was `main.py`
(single maze, adjustable size, no timer) is now `mvp_main.py`, and what was
`progression_main.py` is now `main.py`. The playtest also surfaced that the
maze counter (`Maze N/100`) and the "All 100 mazes complete!" win screen
already existed in this file but went unnoticed — the actual issue was
running the wrong entry point, not missing features.

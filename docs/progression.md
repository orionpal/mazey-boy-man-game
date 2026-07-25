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
| 9x9 | 14.6 | 4.6 |
| 21x21 | 47.2 | 14.3 |
| 41x41 | 99.1 | 27.7 |

With `LABYRINTH_TIME_BASE=10.0` and `LABYRINTH_TIME_PER_TURN=2.0`, that
puts the *average* maze at roughly 19s (9x9) up to 65s (41x41) — 2 seconds
per turn is a generous per-press budget (covers reading the junction and
reacting, not just the keypress itself), meant to be comfortably
completable by a careful player while still creating real time pressure
for a wandering one. Almost certainly the first thing worth retuning after
playing it.

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

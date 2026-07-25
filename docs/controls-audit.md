# Controls Audit

Goal: verify start/end + timer + sliding movement are solid before building
progression on top. Added `tests/` (44 cases, pure-logic — no pygame/display
needed since `maze.py`/`player.py`/`game.py` don't touch pygame).

## Bug found & fixed: recursion limit on large mazes

`generate_maze`'s recursive-backtracker carved via Python function
recursion. `RecursionError` at ~101×101 and up (call depth ~ number of open
cells, past the default `sys.getrecursionlimit()` of 1000). Directly blocks
the "scalable" goal for maze generation. Fixed by carving with an explicit
stack instead of the call stack — same algorithm, same output distribution,
now scales to arbitrarily large grids. Covered by
`test_generate_maze_scales_past_recursion_limit` (up to 201×201).

## Confirmed correct: sliding movement

Property-tested `slide()` across every open cell × all 4 directions, on
multiple maze sizes:
- Never lands on a wall or out of bounds.
- No-op when the immediate next cell is blocked.
- Every stop is explained by either "wall/bound ahead" or "3+ open
  neighbours underfoot" (a junction) — no silent stops elsewhere.
- Round-trip consistent: from a resolved stop, sliding back then forward
  again lands on the same stop (no jitter).

## Design note, not a bug: continuing straight through a junction

Initially wrote a test assuming "pressing the same arrow twice in a row is
always a no-op." That's false by design at a junction: if you stop at a
junction and the same direction is still open, pressing it again correctly
carries you straight through. Only a *wall-caused* stop (dead end) is a true
no-op on repeat. This is what lets you combo through a straight run of
junctions without re-confirming direction each time — matches the "quick
succession" feel described as the goal. Flagging in case the intent was
actually "always pause at every junction, regardless of repeated key" —
that would be a one-line change in `player.slide` (checked before writing:
would just mean stopping unconditionally at a junction, never continuing
through it even if the next cell in `direction` is open) but current
behavior seems more consistent with the "combo" framing, so left as-is.

## Timer / win condition

Confirmed: `elapsed` freezes exactly at the finish moment (updates stop
being applied once `finished`), `best_time` only improves, persists across
`new_maze()`, and `move()` is a no-op once finished. No changes needed here.

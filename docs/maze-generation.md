# Maze Generation: WFC vs. Graph Algorithms

## The question

Current generator is a recursive backtracker (DFS) — a "perfect maze"
(spanning tree: fully connected, no loops). Considering switching to Wave
Function Collapse (WFC) so new tile types can just be added to the adjacency
pool later, without rewriting the generator. Concern: mazes becoming too
simplistic/uninteresting.

## The concern is valid

Vanilla cell-by-cell WFC over a small "which edges are open" tile alphabet
only enforces **local** edge-matching between neighbors. It has no built-in
notion of:
- **Global connectivity** — nothing stops isolated pockets unless you add
  extra logic (post-check + retry, or connectivity-aware weighting).
- **"Interesting" structure** — a perfect maze's winding, long-corridor feel
  comes from the *spanning-tree* property (exactly one path between any two
  cells). WFC's entropy-minimization has no concept of this; left alone it
  tends toward locally-repetitive, low-surprise tiling, especially with a
  small tile vocabulary — which is exactly the "too simplistic" fear.
- **Solvability** — larger/weirder tile pools raise the odds of local
  contradictions (no valid tile fits), which most simple WFC implementations
  handle by restarting from scratch rather than backtracking cleanly.

So a straight swap of "DFS carver" → "WFC over wall/passage tiles" would very
likely be a regression, not an upgrade, on the "interesting" axis.

## Recommendation: keep the graph algorithm for topology, use WFC (or a simpler pool pick) for tile variety on top of it

Split the two things "WFC" was being asked to do:

1. **Guarantee a connected, interesting layout.** Keep doing this with a
   graph algorithm — current DFS carver is fine, and it's cheap to add
   Prim's / Kruskal's / Wilson's as alternate algorithms later for a
   different feel (DFS: long winding corridors, few branches; Prim's: many
   short dead ends; Wilson's: unbiased spanning tree). All of them already
   produce a `cols x rows` wall/passage grid — same interface as today.

2. **Pick a tile skin for each cell.** Once the topology is fixed, each
   cell's *required* open/closed edge signature is already known (determined
   by whether its neighbors are connected or walled). This is where a tile
   *pool* makes sense: for each signature (e.g. "straight corridor",
   "T-junction", "dead end", "4-way"), keep a list of acceptable visual/
   gameplay variants and pick one — this is the actual mechanism you
   described wanting ("add weirder tiles to the pool of acceptable adjacent
   tiles"), and it's exactly WFC's adjacency-pool idea, just applied to a
   *decoration* layer instead of the *connectivity* layer. Connectivity is
   never at risk because it was already locked in by step 1.

This gets the real goal (drop new tile types into a pool over time) without
the risk (simplistic/disconnected mazes) — because the part that's allowed
to vary (tile skin) is decoupled from the part that must stay guaranteed
(topology).

## When true grid-level WFC would actually be worth it

If "weirder tiles" later means new *topology*, not just skins — e.g. wider
rooms, diagonal shortcuts, one-way doors, teleporters — a tile-skin pool
isn't enough, since those change what's reachable, not just what it looks
like. At that point, real WFC (or a similar constraint solver) earns its
keep, but only with a connectivity guard: generate, then BFS-check full
reachability from start, and retry/patch on failure (this is how public WFC
maze demos usually get away with it — the raw algorithm doesn't guarantee it
either). Worth building later, not needed for the current ask.

## Proposed near-term plan

- Keep `generate_maze(cols, rows) -> grid` as the stable interface (already
  true today, and already what the README's roadmap note assumed).
- Land the iterative-carve fix (done — see `controls-audit.md`) so any
  future algorithm swap isn't reintroducing the same recursion-limit bug.
- When ready to add visual/gameplay tile variety: add a tile-skin pick pass
  driven by each cell's fixed edge signature, not a topology-level WFC pass.
- Revisit real grid-level WFC only if/when a concrete "changes reachability"
  tile idea comes up.

Let me know if this matches what you had in mind, or if the "weirder tiles"
you're picturing are more the topology-changing kind — that changes which of
the above to build first.

---

## Update: "not enough branching paths" — switched DFS → Growing Tree

Follow-up complaint about the DFS carver specifically (independent of the
WFC question above): not enough branching. Measured it rather than guessing.

### Measurement

Built a comparison harness (`scripts` not checked in — quick empirical
throwaway) generating 21x21 mazes, 200 trials per algorithm, measuring the
fraction of open cells that are junctions (3+ open neighbours):

| algorithm | junction % | dead-end % | connected |
|---|---|---|---|
| DFS (old default) | 4.8% | 5.9% | yes |
| randomized Prim's | 13.0% | 15.9% | yes |
| randomized Kruskal's | 12.6% | 15.3% | yes |
| Wilson's | 12.1% | 14.5% | yes |
| Growing Tree, newest_prob=1.0 | 5.0% | 6.1% | yes (identical to DFS — expected, see below) |
| Growing Tree, newest_prob=0.5 | 10.2% | 11.9% | yes |
| Growing Tree, newest_prob=0.0 | 11.9% | 13.9% | yes |
| Kruskal's + braid(0.3) | 14.2% | 8.9% | yes |

DFS really was the worst option here by a wide margin — confirms the
complaint wasn't just a feeling.

### Why Growing Tree over switching to Prim's/Kruskal's/Wilson's outright

Growing Tree is a **generalization**, not a different algorithm: it
maintains a set of "active" cells and, at each step, extends either the
*most recently added* one (`newest_prob=1.0`, which is *exactly* the old DFS
carver — same algorithm, same output distribution, confirmed identical in
the table above) or a *uniformly random* one from the active set
(`newest_prob=0.0`, close to Prim's). Values in between blend continuously.

That means: one implementation, one tunable float, and the old behavior is
still reachable as an exact special case rather than being a separate code
path to maintain. It also means this parameter is a natural fit for a future
sidebar control if we ever want to expose "branchiness" alongside maze
dimensions.

### Braiding

Found (and fixed) a real bug while testing the optional braid pass: it
checked whether the *neighbour cell* was a wall, but every odd,odd cell is
already carved open by the time generation finishes, so that check was
always false — the pass silently did nothing at any probability. Fixed to
check the *wall segment between* the dead end and its neighbour instead.
After the fix, `braid_prob=1.0` eliminates nearly all dead ends (some are
now deliberately left alone — see "Isolated wall pillars" below).
Braiding only ever adds edges to an already-connected graph, so it can't
break connectivity — verified with a dedicated test
(`test_braid_only_adds_edges_so_connectivity_is_preserved`).

### Isolated wall pillars (found via playtesting)

Found by actually playing it, not by a test: occasionally a "square" path
would loop all the way around a single standalone wall cell. Root cause —
every wall pixel sits at either a *segment* position (between two maze
cells, one axis odd) or a grid *intersection* (both axes even, never
carved by generation itself). An intersection has 4 neighbouring segments;
if all 4 happen to be open, that one wall pixel ends up fully surrounded by
floor, with a 1-cell loop running around it. The base spanning tree can
never do this (a tree has zero cycles, confirmed empirically: 0 occurrences
across 200 trials with `braid_prob=0.0`) — it's specifically something
`braid()` can cause, since braiding's whole purpose is adding extra loops.
Measured 200 mazes at the default `braid_prob=0.25`: ~1.5 isolated pillars
per maze before the fix, 0 after (confirmed 0 even at `braid_prob=1.0`
across sizes 9/21/35, the worst-case stress test).

Fixed by having `braid()` check, for each candidate wall segment, whether
opening it would leave either of its two neighbouring intersections fully
surrounded (i.e. this would be the 4th of that intersection's 4 segments)
— and rejecting that candidate if so. This is why braiding no longer
guarantees *eliminating every* dead end at `braid_prob=1.0`: a dead end
whose only candidate would isolate a pillar is now deliberately left alone
rather than braided at the cost of that visual artifact.

### Decision

`generate_maze` now takes `newest_prob` (default `0.4`) and `braid_prob`
(default `0.25`), implemented as Growing Tree + optional braid. Chose 0.4
rather than going all the way to 0.0 to keep some long-corridor character
rather than fully uniform Kruskal-like texture — a judgment call, easy to
retune (it's one constant, `DEFAULT_NEWEST_PROB` in `maze.py`) or expose as
a live control if it doesn't feel right in play.

### Bug: goal could be placed somewhere unreachable

`farthest_reachable_cell` (used by both free-play and labyrinth mode to
place the goal) picked whichever cell BFS visited last, without checking
whether the sliding movement could ever stop there. `player.slide()` only
stops at a wall ahead or a junction (3+ open neighbours) — a plain
2-neighbour corridor/turn cell can never be landed on, the player always
slides straight through it. When BFS's "farthest" cell happened to be one
of those, the maze was unsolvable: confirmed in ~18% of generated mazes
(500-trial measurement). Fixed by restricting "farthest" to cells the
sliding mechanic can actually stop on. Full writeup, plus a related
under-counting bug in the labyrinth mode's time-limit estimate, in
`docs/progression.md`.

## Update: teleporting squares shipped using exactly the predicted pattern

The "When true grid-level WFC would actually be worth it" section above
named teleporters directly as the kind of topology-changing tile that
would need "real WFC/constraint-solving with a generate → BFS-connectivity-
check → retry loop," not just the tile-skin-pool idea — since it changes
what's *reachable*, not just what a cell looks like. That's exactly what
`progression/augments/teleporters.py` does now: it's a post-process step
over `generate_maze()`'s output (not a change to the generator itself, so
`generate_maze(cols, rows) -> grid` stays the stable interface this doc
already committed to), which seals off a pocket of the maze, verifies the
result with `bfs_reachable()` *and* a real-move simulation (plain
grid-adjacency reachability isn't sufficient once entering a cell can
force an unconditional redirect — see `docs/progression.md`'s "Maze
augments" section for why), and rejects-and-retries on failure. Not
literal Wave Function Collapse, but the same shape the escalation path
here anticipated — closing that open thread with what actually got built.
## Update: rotating maze, fog of war, and shifting rooms have since shipped

All three named above as the remaining maze-augment backlog are now built
(`docs/progression.md`'s "Maze augments" section has the full writeup for
each). Rotating maze turned out to need *none* of the WFC-style
generate-verify-retry machinery this doc anticipated -- a rigid rotation
is a genuine isometry, exactly as solvable after as before, so it's
purely a runtime effect with no generation-time verification at all. Fog
of war is likewise purely presentational, no generation-time changes.
Shifting rooms *did* need the anticipated shape, but with a twist this doc
didn't foresee: unlike teleporters (a decorative "extra edge" over an
otherwise-normal grid), a shifting-room pocket is sealed by a genuinely
closed wall until its pad fires, which meant planning code (goal
placement, par-time estimation) needed to explicitly plan against a
copy of the grid with every pad pre-opened, rather than the literal,
currently-sealed grid -- see `docs/progression.md`'s "Shifting room"
section for the concrete bugs this surfaced and how they were fixed.

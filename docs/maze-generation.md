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
After the fix, `braid_prob=1.0` eliminates 100% of dead ends, as expected.
Braiding only ever adds edges to an already-connected graph, so it can't
break connectivity — verified with a dedicated test
(`test_braid_only_adds_edges_so_connectivity_is_preserved`).

### Decision

`generate_maze` now takes `newest_prob` (default `0.4`) and `braid_prob`
(default `0.25`), implemented as Growing Tree + optional braid. Chose 0.4
rather than going all the way to 0.0 to keep some long-corridor character
rather than fully uniform Kruskal-like texture — a judgment call, easy to
retune (it's one constant, `DEFAULT_NEWEST_PROB` in `maze.py`) or expose as
a live control if it doesn't feel right in play.

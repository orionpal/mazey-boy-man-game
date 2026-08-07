"""
twin_goals.py
-------------
A second, independently-reachable goal cell per maze -- touching either
one clears it. A small bonus pellet cluster spawns near whichever of the
two gets randomly chosen (see progression/run.py::_begin_maze() and
progression/entities/hazards.py::spawn_pellet_cluster_near()), so the two
goals aren't purely equivalent even though both end the maze.

Doesn't fit the gating/ or runtime/ shape any other augment here uses:
its real placement work can't happen inside apply() at all, because it
needs the *finalized* primary goal (ctx.goal after _finalize_goal() runs)
as one of its two distance anchors -- something no individual augment's
apply() has access to, since goal finalization happens once, centrally,
after every augment has run (see augments/__init__.py's AugmentContext/
_finalize_goal() docstrings). apply() here is therefore a near no-op: it
just sets ctx.extra["twin_goals_active"], a signal augments/__init__.py's
run_pipeline() checks *after* _finalize_goal() to decide whether to run
the real work (_resolve_secondary_goal()) at all.

Shipped mutually exclusive with Doors/Teleporters (see
augments/__init__.py's offer_augment_cards()) -- see
_resolve_secondary_goal()'s docstring for why an unconstrained secondary
goal risks making a mandatory gate skippable.
"""

from __future__ import annotations

from maze_game.constants import TWIN_GOAL_PELLET_FREQUENCY_MULTIPLIER, TWIN_GOAL_PELLET_VALUE_MULTIPLIER
from maze_game.progression.augments import Augment, AugmentContext


class TwinGoalsAugment(Augment):
    id = "twin_goals"
    name = "Twin Goals"
    description = (
        "A second goal appears somewhere else in the maze -- reach either one to clear it. "
        "One of the two hides a small bonus pellet cluster."
    )
    pellet_frequency_multiplier = TWIN_GOAL_PELLET_FREQUENCY_MULTIPLIER
    pellet_value_multiplier = TWIN_GOAL_PELLET_VALUE_MULTIPLIER

    def apply(self, ctx: AugmentContext) -> None:
        ctx.extra["twin_goals_active"] = True

"""
run/breaks.py
-------------
Everything about the pauses *between* mazes, split off from run/state.py as
one cohesive responsibility: the group-boundary "power-up" shop pick, the
"modifier" augment pick, the one-time 3D arena interlude, and the in-maze
walk-to shop tile -- plus the queue machinery (``_pending_breaks``,
``_resume_after_break``) that makes several breaks landing on the same
maze index stack sequentially instead of clobbering each other.

``BreakSequenceMixin`` is mixed into ``LabyrinthRun`` (run/state.py); it
reads/writes state the base ``__init__`` sets up (``break_kind``,
``_pending_breaks``, ``time``, ``build``, ``gold`` ...) and calls back into
``_begin_maze()`` when the queue drains.
"""

from __future__ import annotations

from maze_game.constants import (
    LABYRINTH_TOTAL_MAZES, LABYRINTH_GROUP_SIZE, SHOP_PAUSE_SECONDS,
)
from maze_game.progression.economy.shop import (
    offer_shop_cards, MAZE_SHOP_ITEMS, purchase_maze_shop_item,
)
from maze_game.progression.economy.meta import save_gold_total
from maze_game.progression.augments import offer_augment_cards
from maze_game.progression.run.model import (
    FirstMazeRecord, TimeResource, START_POS, _breaks_due_after,
)


class BreakSequenceMixin:
    """Break-cursor + break-queue behaviour for LabyrinthRun. Not usable standalone."""

    # ── Between-maze break cards (shop / augment / arena) ─────────────────

    @property
    def on_break(self) -> bool:
        return self.break_kind is not None

    def move_break_cursor(self, delta: int) -> None:
        """Move the keyboard-selected break card left/right (wraps), for whichever break (shop or augment) is currently active."""
        choices = self._current_break_choices()
        if choices is None:
            return
        self.break_cursor = (self.break_cursor + delta) % len(choices)

    def choose_break_card(self, index: int) -> None:
        """Single entry point for confirming a break-card pick -- dispatches to whichever break is currently active."""
        if self.break_kind == "shop":
            self.choose_shop_card(index)
        elif self.break_kind == "augment":
            self.choose_augment_card(index)
        elif self.break_kind == "arena":
            # The arena is a full alternate mode, normally resolved by
            # progression/app.py handing off to arena/app.py. With no
            # interactive layer (a headless full-run test, or a stray
            # confirm press), treat it as skipped and move on.
            self.finish_arena()

    def choose_shop_card(self, index: int) -> None:
        """Apply the chosen perk, then resume (the next queued break, or the next maze)."""
        if self.break_kind != "shop" or self.shop_choices is None:
            return
        self.build.acquire(self.shop_choices[index])
        self.shop_choices = None
        self.events.append("card_select")
        self._resume_after_break()

    def choose_augment_card(self, index: int) -> None:
        """Apply the chosen maze modifier (augment), then resume (the next queued break, or the next maze)."""
        if self.break_kind != "augment" or self.augment_choices is None:
            return
        self.augment_build.acquire(self.augment_choices[index])
        self.augment_choices = None
        self.events.append("card_select")
        self._resume_after_break()

    def _current_break_choices(self) -> list | None:
        if self.break_kind == "shop":
            return self.shop_choices
        if self.break_kind == "augment":
            return self.augment_choices
        return None

    # ── In-maze walk-to shop tile ────────────────────────────────────────

    def enter_shop(self) -> None:
        """
        Called by ShopTile.on_contact() -- pauses the real time resource
        (update() skips TimeResource.tick() while in_shop, mirroring
        on_break) and starts a second, independent TimeResource just for the
        shop's own SHOP_PAUSE_SECONDS countdown. Does not touch self.time at
        all here; _exit_shop() resync()s it once the shop closes, same
        staleness-avoidance pattern as _resume_after_break().
        """
        self.in_shop = True
        self.shop_cursor = 0
        self.shop_time = TimeResource(SHOP_PAUSE_SECONDS)
        self.events.append("shop_enter")

    def _exit_shop(self) -> None:
        """The shop's own countdown hit zero -- resume the real timer exactly where it left off, never early."""
        self.in_shop = False
        self.shop_time = None
        self.time.resync()
        self.events.append("shop_exit")

    def move_shop_cursor(self, delta: int) -> None:
        """Move the keyboard-selected shop item left/right (wraps). No-op when the shop isn't open."""
        if not self.in_shop:
            return
        self.shop_cursor = (self.shop_cursor + delta) % len(MAZE_SHOP_ITEMS)

    def buy_shop_item(self, index: int) -> None:
        """Attempt to purchase MAZE_SHOP_ITEMS[index] with gold. Silently no-ops if unaffordable or the shop isn't open."""
        if not self.in_shop or not (0 <= index < len(MAZE_SHOP_ITEMS)):
            return
        self.shop_cursor = index
        if purchase_maze_shop_item(self, MAZE_SHOP_ITEMS[index]):
            self.events.append("card_select")

    # ── Queue machinery ──────────────────────────────────────────────────

    def _advance(self) -> None:
        if self.maze_index >= LABYRINTH_TOTAL_MAZES:
            self.completed_run = True
            return
        if self.maze_index == 1:
            # Snapshot maze 1 *now*, before _begin_maze() overwrites grid/trail.
            self.first_maze_record = FirstMazeRecord(
                grid=[row[:] for row in self.grid],
                goal=self.goal,
                trail=list(self.trail),
                start=START_POS,
            )
        breaks = _breaks_due_after(self.maze_index)
        if self.maze_index == LABYRINTH_GROUP_SIZE and not self._arena_shown:
            # One-time 3D replay of maze 1, ahead of this group's shop pick.
            self._arena_shown = True
            breaks.insert(0, "arena")
        self._pending_breaks = breaks
        self._resume_after_break()

    def finish_arena(self) -> None:
        """
        Called by arena/app.py when the 3D interlude ends (win, loss, timeout
        or quit). The arena never touches the run's time resource; the only
        thing it carries back is treasure gold, banked here. Then the normal
        break sequence resumes (this group's shop pick).
        """
        if self.break_kind != "arena":
            return
        if self.arena_gold_pending:
            self.gold += self.arena_gold_pending
            save_gold_total(self.gold, self.gold_path)
            self.arena_gold_pending = 0
        self.events.append("card_select")
        self._resume_after_break()

    def _resume_after_break(self) -> None:
        """
        Pop the next queued break (if any) and show it; once the queue is
        empty, actually advance to the next maze. This is what makes
        multiple breaks on the same maze index stack sequentially (e.g.
        maze 30: power-up screen, then modifier screen, then maze 30
        begins) instead of one replacing another -- and, critically, only
        resyncs the clock *once* the whole queue is drained, not after each
        individual break, avoiding the exact TimeResource staleness bug
        docs/progression.md already documents once (a stale tick reference
        point charging the entire paused stretch in one lump the instant
        play resumes).
        """
        if self._pending_breaks:
            self.break_kind = self._pending_breaks.pop(0)
            self.break_cursor = 0
            if self.break_kind == "shop":
                self.shop_choices = offer_shop_cards(rng=self.rng)
            elif self.break_kind == "augment":
                self.augment_choices = offer_augment_cards(self.augment_build, rng=self.rng)
            # "arena" is a full alternate mode, not a card-pick overlay:
            # progression/app.py hands off to arena/app.py and calls
            # finish_arena() when it returns. Nothing to prepare here.
            return
        self.break_kind = None
        self.time.resync()  # the break(s) paused the clock; don't charge their duration on the next tick()
        self.maze_index += 1
        self._begin_maze()  # seamless when no break was due -- no pause within a group

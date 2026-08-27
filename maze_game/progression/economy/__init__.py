"""
economy/__init__.py
-------------------
The run's gold-spending systems, grouped: ``meta/`` (permanent upgrades
bought in the Base between runs) and ``shop/`` (the per-run perk cards
offered at group breaks, plus the paid in-maze walk-to shop catalog). Both
draw on the same gold total (``gold.json``) and the same
``shop/perks.py`` Build/EFFECTS machinery; grouping them here keeps
``progression/`` within its directory cap without splitting that shared
lineage across the tree.

Pure move -- no behaviour change. Import paths are
``maze_game.progression.economy.meta`` / ``.economy.shop``.
"""

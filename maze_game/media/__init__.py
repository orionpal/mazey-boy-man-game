# maze_game/media/__init__.py
"""
Asset-readiness layer: sound.py and sprites.py each do lazy, cached
lookups against assets/sounds/ and assets/icons/ respectively, both
returning a harmless "nothing to play/draw" result when a file doesn't
exist yet. See docs/assets.md for the full design writeup and the
complete event-name/icon-name vocabulary.
"""

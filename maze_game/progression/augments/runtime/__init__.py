"""
augments/runtime/
------------------
Pure runtime augments: Augment.apply() is a no-op for these (nothing to do
at generation time), and LabyrinthRun reads augment_build.level_of(id)
directly at runtime instead, mirroring the pattern renderer.py's augment
sidebar already uses to read active augment levels independent of
AugmentContext. Split out from augments/ alongside gating/ (see that
package's docstring) once this project's directory-size convention
required a flat augments/ to be reorganized.

Re-exports the concrete Augment subclasses so augments/__init__.py's
registration step doesn't need to know about this split.
"""

"""Trial design knobs for the reflected-maze pilot.

Change schedule sizes, deadlines, and cue balances here. Geometry constants
(grid size, start/goal) stay in ``maze.py``. Narrative design notes live in
``TRIAL_DESIGN.md``.
"""

from __future__ import annotations

from typing import Literal

type Side = Literal["left", "right"]
type Symbol = Literal["circle", "diamond"]
type ProbeKind = Literal["symbol-only", "aligned", "conflicting"]
type Guidance = Literal["full", "fade"]

# --- Timing (playable export) -------------------------------------------------
# Offline player times every first move. Override per export with --deadline-ms.
DEFAULT_DEADLINE_MS = 800
DEADLINE_CALIBRATION_PERCENTILE = 0.7
DEADLINE_FLOOR_MS = 400

# --- Maze fixtures used by schedules ------------------------------------------
# Detour lengths map to shortcut savings of 6, 4, and 2 moves.
DETOUR_LENGTHS: tuple[int, ...] = (1, 2, 3)
LAYOUT_VARIANT_COUNT = 4
TRAINING_DETOUR = 2
TRAINING_VARIANT = 0
PROBE_DETOUR = 2
# Fading guidance shows this many cells of the learned route (includes start).
FADE_GUIDANCE_PREFIX_CELLS = 3

# --- Pilot phase --------------------------------------------------------------
# Training: both reflections × each guidance level → 4 trials.
TRAINING_GUIDANCES: tuple[Guidance, ...] = ("full", "fade")
TRAINING_REFLECTIONS: tuple[bool, ...] = (False, True)
# Cue probes: each kind × both orientations × this many replicates.
PROBE_KINDS: tuple[ProbeKind, ...] = ("symbol-only", "aligned", "conflicting")
PROBE_TRIALS_PER_ORIENTATION = 4

# --- Test phase ---------------------------------------------------------------
# Each block: DETOUR_LENGTHS × BLOCK_TRIALS_PER_SAVINGS trials (default 6).
BLOCK_TRIALS_PER_SAVINGS = 2

# --- Cue mapping --------------------------------------------------------------
SYMBOLS: dict[Side, Symbol] = {"left": "circle", "right": "diamond"}
SIDES: tuple[Side, Side] = ("left", "right")


def training_trial_count() -> int:
    """Return how many training trials the pilot schedule prepends."""
    return len(TRAINING_GUIDANCES) * len(TRAINING_REFLECTIONS)


def probe_trial_count() -> int:
    """Return total cue-probe trials per pilot session."""
    return len(PROBE_KINDS) * 2 * PROBE_TRIALS_PER_ORIENTATION


def block_trial_count() -> int:
    """Return trials in one test block."""
    return len(DETOUR_LENGTHS) * BLOCK_TRIALS_PER_SAVINGS

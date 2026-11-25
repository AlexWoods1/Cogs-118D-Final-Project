import argparse
import json
from dataclasses import dataclass
from random import Random
from typing import Literal

from .maze import (
    GOAL,
    HEIGHT,
    INITIAL_VISIBLE_CELLS,
    START,
    WIDTH,
    Edge,
    Maze,
    build_template,
    edge_between,
    verify_maze,
)
from .session_cli import (
    add_phase_arg,
    add_seed_participant_args,
    reject_negative_participant_index,
)
from .trial_config import (
    BLOCK_TRIALS_PER_SAVINGS,
    DETOUR_LENGTHS,
    LAYOUT_VARIANT_COUNT,
    PROBE_DETOUR,
    PROBE_KINDS,
    PROBE_TRIALS_PER_ORIENTATION,
    SIDES,
    SYMBOLS,
    ProbeKind,
    Side,
    Symbol,
)

type Phase = Literal["test", "pilot"]

BEACON_EDGES = {
    "left": edge_between((3, 1), (3, 2)),
    "right": edge_between((9, 1), (9, 2)),
}


@dataclass(frozen=True)
class Condition:
    """The two factors assigned to a test block."""

    landmark: Literal["informative", "uninformative"]
    timed: bool


CONDITIONS = (
    Condition("informative", False),
    Condition("informative", True),
    Condition("uninformative", False),
    Condition("uninformative", True),
)
BLOCK_ORDERS = ((0, 1, 3, 2), (1, 2, 0, 3), (2, 3, 1, 0), (3, 0, 2, 1))


@dataclass(frozen=True)
class Trial:
    """A verified layout and its rendered cue assignment."""

    maze: Maze
    reflected: bool
    beacon_side: Side | None
    shortcut_savings: int

    @property
    def learned_side(self) -> Side:
        """Return the learned first turn in participant coordinates."""
        # Use the geometry after reflection so the scoring side follows the layout.
        return _learned_side(self.maze)

    @property
    def orientation_symbol(self) -> Symbol:
        """Return the symbol participants learn for this orientation."""
        # The symbol stays valid in every beacon condition.
        return SYMBOLS[self.learned_side]

    @property
    def beacon_edge(self) -> Edge | None:
        """Return the beacon wall boundary in participant coordinates, if any."""
        return BEACON_EDGES[self.beacon_side] if self.beacon_side else None


@dataclass(frozen=True)
class Block:
    """A set of trials with one landmark and timing condition."""

    condition: Condition
    trials: tuple[Trial, ...]


@dataclass(frozen=True)
class Probe:
    """An untimed trial for evaluating a particular cue pairing."""

    kind: ProbeKind
    trial: Trial


def _learned_side(maze: Maze) -> Side:
    """Read the initial side from the maze's learned route."""
    # The verifier ensures the first move leaves the center column horizontally.
    return "left" if maze.learned_route[1][0] < START[0] else "right"


def _trial_maze(detour: int, variant: int, reflected: bool) -> Maze:
    """Build the fixture in the orientation assigned to a trial."""
    template = build_template(detour, variant)
    # Apply reflection once so both cues and scoring can use the final geometry.
    return template.reflected() if reflected else template


def _session_rng(seed: int, participant_index: int, phase: Phase) -> Random:
    """Create an independent random stream for a session phase."""
    if participant_index < 0:
        raise ValueError("Participant index must be nonnegative")
    # Including the phase makes test and pilot exports independent of call order.
    return Random(f"{seed}:{participant_index}:{phase}")


def _block_trials(condition: Condition, variant: int, rng: Random) -> tuple[Trial, ...]:
    """Generate verified trials at each savings level for a block."""
    detours = list(DETOUR_LENGTHS) * BLOCK_TRIALS_PER_SAVINGS
    rng.shuffle(detours)
    trials = []
    for detour in detours:
        reflected = bool(rng.getrandbits(1))
        maze = _trial_maze(detour, variant, reflected)
        # In the uninformative condition the beacon draw is independent of the turn.
        beacon_side = (
            _learned_side(maze)
            if condition.landmark == "informative"
            else rng.choice(SIDES)
        )
        trials.append(Trial(maze, reflected, beacon_side, verify_maze(maze)))
    return tuple(trials)


def generate_blocks(seed: int, participant_index: int) -> tuple[Block, ...]:
    """Generate the four test blocks for a zero-based participant index."""
    rng = _session_rng(seed, participant_index, "test")
    layout_cycle, order_index = divmod(participant_index, len(BLOCK_ORDERS))
    blocks = []
    for condition_index in BLOCK_ORDERS[order_index]:
        condition = CONDITIONS[condition_index]
        # Rotate the geometry assignment independently of the block presentation order.
        variant = (condition_index + layout_cycle) % len(CONDITIONS)
        blocks.append(Block(condition, _block_trials(condition, variant, rng)))
    return tuple(blocks)


def _probe_beacon_side(kind: ProbeKind, learned_side: Side) -> Side | None:
    """Assign the beacon for the probe's cue pairing."""
    if kind == "symbol-only":
        return None
    if kind == "aligned":
        return learned_side
    # A conflicting beacon points toward the opposite first turn.
    return "right" if learned_side == "left" else "left"


def generate_probes(seed: int, participant_index: int) -> tuple[Probe, ...]:
    """Mix untimed cue probes with both orientations represented in each cue type."""
    rng = _session_rng(seed, participant_index, "pilot")
    probes = []
    for kind in PROBE_KINDS:
        # Balance reflections for each probe type before mixing presentation order.
        orientations = [False] * PROBE_TRIALS_PER_ORIENTATION + [
            True
        ] * PROBE_TRIALS_PER_ORIENTATION
        rng.shuffle(orientations)
        for index, reflected in enumerate(orientations):
            maze = _trial_maze(PROBE_DETOUR, index % LAYOUT_VARIANT_COUNT, reflected)
            beacon_side = _probe_beacon_side(kind, _learned_side(maze))
            probes.append(
                Probe(kind, Trial(maze, reflected, beacon_side, verify_maze(maze)))
            )
    rng.shuffle(probes)
    return tuple(probes)


def _trial_record(trial: Trial) -> dict[str, object]:
    """Convert a trial to the JSON export fields."""
    # Sort openings to provide stable output from the maze's unordered edge set.
    return {
        "template_id": trial.maze.template_id,
        "reflected": trial.reflected,
        "open_edges": sorted(trial.maze.open_edges),
        "orientation_symbol": trial.orientation_symbol,
        "beacon_side": trial.beacon_side,
        "beacon_edge": trial.beacon_edge,
        "learned_side": trial.learned_side,
        "learned_route": trial.maze.learned_route,
        "later_junction": trial.maze.later_junction,
        "shortcut_savings": trial.shortcut_savings,
    }


def grid_metadata() -> dict[str, object]:
    """Return the shared grid fields used by JSON and offline exports."""
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "start": START,
        "goal": GOAL,
        "initial_visible_cells": sorted(INITIAL_VISIBLE_CELLS),
    }


def _parse_args() -> argparse.Namespace:
    """Parse and validate the generator command-line options."""
    parser = argparse.ArgumentParser(description="Generate verified edge-maze trials.")
    add_seed_participant_args(parser, seed_required=True)
    add_phase_arg(parser, default="test")
    args = parser.parse_args()
    # Surface the same constraint used by the scheduler as a command-line error.
    reject_negative_participant_index(parser, args)
    return args


def _session_record(
    seed: int, participant_index: int, phase: Phase
) -> dict[str, object]:
    """Build the JSON payload for the selected phase."""
    result = {
        "seed": seed,
        "participant_index": participant_index,
        "phase": phase,
        "grid": grid_metadata(),
    }
    # Test trials export in blocks, while pilot probes export in presentation order.
    if phase == "test":
        result["blocks"] = [
            {
                "landmark": block.condition.landmark,
                "timed": block.condition.timed,
                "trials": [_trial_record(trial) for trial in block.trials],
            }
            for block in generate_blocks(seed, participant_index)
        ]
    else:
        result["probes"] = [
            {"kind": probe.kind, "timed": False, **_trial_record(probe.trial)}
            for probe in generate_probes(seed, participant_index)
        ]
    return result


def main() -> None:
    """Write the generated session as JSON to standard output."""
    args = _parse_args()
    # Keep standard output suitable for piping into another program.
    print(
        json.dumps(
            _session_record(args.seed, args.participant_index, args.phase), indent=2
        )
    )


if __name__ == "__main__":
    main()

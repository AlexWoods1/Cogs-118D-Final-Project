import argparse
import json
from pathlib import Path
from typing import TypedDict

from maze import (
    CENTER_ENTRY,
    GOAL,
    HEIGHT,
    INITIAL_VISIBLE_CELLS,
    START,
    WIDTH,
    Cell,
    Edge,
    Maze,
)
from maze_trials import (
    BEACON_EDGES,
    ProbeKind,
    Symbol,
    Trial,
    generate_blocks,
    generate_probes,
)

PROBE_LABELS: dict[ProbeKind, str] = {
    "symbol-only": "Symbol only",
    "aligned": "Aligned beacon",
    "conflicting": "Conflicting beacon",
}


class PreviewTrial(TypedDict):
    """Render-ready geometry, cue placement, and route overlays for a trial."""

    label: str
    reflected: bool
    symbol: Symbol
    beacon: Edge | None
    edges: list[Edge]
    learned: tuple[Cell, ...]
    shortcut: list[Cell]
    junction: Cell


class PreviewData(TypedDict):
    """Session metadata and both schedules embedded in an offline preview."""

    seed: str
    participantIndex: str
    width: int
    height: int
    start: Cell
    goal: Cell
    visible: list[Cell]
    test: list[PreviewTrial]
    pilot: list[PreviewTrial]


def _shortcut(maze: Maze) -> list[Cell]:
    """Trace one shortest route through the center exit."""
    distances = maze.distances_to_goal()
    # The verifier guarantees the center exit is on a shortest route.
    path = [START, CENTER_ENTRY]
    while path[-1] != GOAL:
        cell = path[-1]
        path.append(
            next(
                neighbor
                for neighbor in maze.neighbors(cell)
                if distances[neighbor] == distances[cell] - 1
            )
        )
    return path


def _preview_trial(trial: Trial, label: str) -> PreviewTrial:
    """Build the browser payload for one generated trial."""
    # Export coordinates in participant space so the renderer applies no reflection.
    return {
        "label": label,
        "reflected": trial.reflected,
        "symbol": trial.orientation_symbol,
        "beacon": BEACON_EDGES[trial.beacon_side] if trial.beacon_side else None,
        "edges": sorted(trial.maze.open_edges),
        "learned": trial.maze.learned_route,
        "shortcut": _shortcut(trial.maze),
        "junction": trial.maze.later_junction,
    }


def _preview_test_trials(seed: int, participant_index: int) -> list[PreviewTrial]:
    """Label test trials in block presentation order."""
    trials = []
    for number, block in enumerate(generate_blocks(seed, participant_index), 1):
        cue = block.condition.landmark.capitalize() + " beacon"
        pressure = "Timed" if block.condition.timed else "Untimed"
        # Keep the condition visible even when browsing trials out of sequence.
        for index, trial in enumerate(block.trials, 1):
            label = f"Block {number}, trial {index} · {cue} · {pressure}"
            trials.append(_preview_trial(trial, label))
    return trials


def _preview_data(seed: int, participant_index: int) -> PreviewData:
    """Collect both generated schedules and their shared grid metadata."""
    return {
        # Decimal strings preserve Python integers outside JavaScript's safe range.
        "seed": str(seed),
        "participantIndex": str(participant_index),
        "width": WIDTH,
        "height": HEIGHT,
        "start": START,
        "goal": GOAL,
        "visible": sorted(INITIAL_VISIBLE_CELLS),
        "test": _preview_test_trials(seed, participant_index),
        "pilot": [
            _preview_trial(probe.trial, f"Probe {number} · {PROBE_LABELS[probe.kind]}")
            for number, probe in enumerate(generate_probes(seed, participant_index), 1)
        ],
    }


def _write_preview(data: PreviewData, output: Path) -> None:
    """Embed data and rendering code in a self-contained HTML file."""
    source = Path(__file__).parent
    template = (source / "maze_viz.html").read_text(encoding="utf-8")
    script = (source / "maze_viz.js").read_text(encoding="utf-8")
    json_data = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    # Inline both sources so the exported preview can run from a file URL offline.
    html = template.replace("<!-- TRIAL_DATA -->", json_data).replace(
        "<!-- PREVIEW_SCRIPT -->", script
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    """Read and validate the preview export options."""
    parser = argparse.ArgumentParser(description="Export an interactive maze preview.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--participant-index", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("build/maze-preview.html"))
    args = parser.parse_args()
    # Match the participant indexing accepted by the trial generator.
    if args.participant_index < 0:
        parser.error("--participant-index must be nonnegative")
    return args


def main() -> None:
    """Export the requested preview and print its location."""
    args = _parse_args()
    _write_preview(_preview_data(args.seed, args.participant_index), args.output)
    # Print the absolute path so the file can be located from any working directory.
    print(args.output.resolve())


if __name__ == "__main__":
    main()

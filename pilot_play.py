"""Export a playable offline pilot session and score participant decisions."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Literal, TypedDict

from maze import (
    CENTER_ENTRY,
    GOAL,
    HEIGHT,
    INITIAL_VISIBLE_CELLS,
    START,
    WIDTH,
    Cell,
    Edge,
    build_template,
    edge_between,
    verify_maze,
)
from maze_trials import (
    BEACON_EDGES,
    Phase,
    Side,
    Symbol,
    Trial,
    generate_blocks,
    generate_probes,
)

type FirstChoice = Literal["learned", "shortcut", "other", "timeout"]
type Continuation = Literal["learned", "alternate", "none"]
type Guidance = Literal["full", "fade", "none"]


class PlayTrial(TypedDict):
    """Participant-facing geometry plus scoring fields for logging."""

    label: str
    kind: str | None
    landmark: str | None
    timed: bool
    deadline_ms: int | None
    guidance: Guidance
    reflected: bool
    symbol: Symbol
    beacon: Edge | None
    edges: list[Edge]
    learned_side: Side
    learned_route: tuple[Cell, ...]
    later_junction: Cell
    shortcut_savings: int


class PlayData(TypedDict):
    """Offline session payload embedded in the playable HTML export."""

    seed: str
    participantIndex: str
    phase: Phase
    width: int
    height: int
    start: Cell
    goal: Cell
    centerEntry: Cell
    initialVisible: list[Cell]
    trials: list[PlayTrial]


def classify_first_choice(
    destination: Cell,
    learned_side: Side,
    *,
    timed_out: bool = False,
) -> FirstChoice:
    """Classify the first leave-start move for scoring."""
    if timed_out:
        return "timeout"
    if destination == CENTER_ENTRY:
        return "shortcut"
    side: Side = "left" if destination[0] < START[0] else "right"
    if destination[1] == START[1] and side == learned_side:
        return "learned"
    return "other"


def classify_later_continuation(
    junction: Cell,
    next_cell: Cell,
    learned_route: tuple[Cell, ...],
) -> Continuation:
    """Score the first departure from the later junction along the learned route."""
    if junction not in learned_route:
        return "none"
    index = learned_route.index(junction)
    if index + 1 >= len(learned_route):
        return "none"
    # Only the trained forward step counts as the learned continuation.
    return "learned" if next_cell == learned_route[index + 1] else "alternate"


def can_step(open_edges: frozenset[Edge], first: Cell, second: Cell) -> bool:
    """Check whether a participant move uses a legal opening."""
    return edge_between(first, second) in open_edges


def reveal_after_visit(visible: frozenset[Cell], cell: Cell) -> frozenset[Cell]:
    """Expand fog by recording the newly occupied cell."""
    # Openings become visible once either endpoint leaves the fog.
    return visible | {cell}


def beacon_visible(beacon: Edge | None, visible: frozenset[Cell]) -> bool:
    """Return whether either beacon endpoint is currently in view."""
    if beacon is None:
        return False
    first, second = beacon
    return first in visible or second in visible


def guidance_cells(route: tuple[Cell, ...], guidance: Guidance) -> tuple[Cell, ...]:
    """Return the learned-route prefix shown during training."""
    if guidance == "none":
        return ()
    if guidance == "fade":
        # Keep the first turn and the next corridor step, then withdraw the rest.
        return route[:3]
    return route


def calibrate_deadline_ms(
    response_times_ms: list[int],
    *,
    percentile: float = 0.7,
    floor_ms: int = 400,
) -> int:
    """Pick a deadline below typical untimed RTs while keeping most responses."""
    if not response_times_ms:
        raise ValueError("Need untimed response times to calibrate a deadline")
    if not 0 < percentile <= 1:
        raise ValueError("Percentile must fall in (0, 1]")
    ordered = sorted(response_times_ms)
    # Linear index into the sorted untimed RTs keeps most responses under the cut.
    index = min(len(ordered) - 1, max(0, int(percentile * (len(ordered) - 1))))
    return max(floor_ms, ordered[index])


def summarize_first_choices(
    records: list[dict[str, object]],
    *,
    group_key: str = "kind",
) -> dict[str, dict[str, object]]:
    """Aggregate first decisions and mean RT by cue or landmark group."""
    buckets: dict[str, list[dict[str, object]]] = {}
    for record in records:
        key = str(record.get(group_key) or "unknown")
        buckets.setdefault(key, []).append(record)
    summary: dict[str, dict[str, object]] = {}
    for key, group in buckets.items():
        counts = Counter(str(item.get("firstChoice") or "none") for item in group)
        times = [
            int(item["firstChoiceRtMs"])
            for item in group
            if isinstance(item.get("firstChoiceRtMs"), int)
        ]
        summary[key] = {
            "n": len(group),
            "choices": dict(counts),
            "mean_rt_ms": mean(times) if times else None,
        }
    return summary


def learned_choice_delta(
    timed_records: list[dict[str, object]],
    untimed_records: list[dict[str, object]],
) -> float | None:
    """Return timed-minus-untimed change in learned first-choice rate."""
    if not timed_records or not untimed_records:
        return None

    def rate(rows: list[dict[str, object]]) -> float:
        return sum(1 for row in rows if row.get("firstChoice") == "learned") / len(rows)

    return rate(timed_records) - rate(untimed_records)


MOVE_CSV_FIELDS = (
    "seed",
    "participant_index",
    "phase",
    "trial_index",
    "trial_attempt",
    "label",
    "kind",
    "landmark",
    "timed",
    "guidance",
    "move_index",
    "event",
    "t_ms",
    "from_x",
    "from_y",
    "to_x",
    "to_y",
    "dx",
    "dy",
    "legal",
    "first_choice",
    "later_continuation",
    "beacon_visible_at_junction",
    "reached_goal",
)


def moves_to_csv(rows: Sequence[Mapping[str, object]]) -> str:
    """Serialize attempted-move records to CSV text with a header row."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=MOVE_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in MOVE_CSV_FIELDS})
    return buffer.getvalue()


def _play_trial(
    trial: Trial,
    *,
    label: str,
    timed: bool,
    kind: str | None = None,
    landmark: str | None = None,
    guidance: Guidance = "none",
    deadline_ms: int | None = None,
) -> PlayTrial:
    """Build one playable trial record in participant coordinates."""
    return {
        "label": label,
        "kind": kind,
        "landmark": landmark,
        "timed": timed,
        "deadline_ms": deadline_ms,
        "guidance": guidance,
        "reflected": trial.reflected,
        "symbol": trial.orientation_symbol,
        "beacon": BEACON_EDGES[trial.beacon_side] if trial.beacon_side else None,
        "edges": sorted(trial.maze.open_edges),
        "learned_side": trial.learned_side,
        "learned_route": trial.maze.learned_route,
        "later_junction": trial.maze.later_junction,
        "shortcut_savings": trial.shortcut_savings,
    }


def _training_trial(reflected: bool, guidance: Guidance, label: str) -> PlayTrial:
    """Build one symbol-only training trial in a fixed layout orientation."""
    maze = build_template(2, 0)
    if reflected:
        maze = maze.reflected()
    trial = Trial(maze, reflected, None, verify_maze(maze))
    return _play_trial(
        trial,
        label=label,
        timed=False,
        kind="train",
        guidance=guidance,
    )


def training_trials() -> list[PlayTrial]:
    """Train both reflections with full guidance, then fade the path cue."""
    trials: list[PlayTrial] = []
    for reflected in (False, True):
        orientation = "reflected" if reflected else "original"
        trials.append(
            _training_trial(
                reflected,
                "full",
                f"Train · full guidance · {orientation}",
            )
        )
    for reflected in (False, True):
        orientation = "reflected" if reflected else "original"
        trials.append(
            _training_trial(
                reflected,
                "fade",
                f"Train · fading guidance · {orientation}",
            )
        )
    return trials


def play_session(
    seed: int,
    participant_index: int,
    phase: Phase,
    *,
    deadline_ms: int | None = None,
) -> PlayData:
    """Assemble the playable schedule for one phase."""
    if phase == "pilot":
        trials = training_trials()
        trials.extend(
            _play_trial(
                probe.trial,
                label=f"Probe {number} · {probe.kind}",
                timed=False,
                kind=probe.kind,
                guidance="none",
            )
            for number, probe in enumerate(generate_probes(seed, participant_index), 1)
        )
    else:
        trials = []
        for number, block in enumerate(generate_blocks(seed, participant_index), 1):
            cue = f"{block.condition.landmark} beacon"
            pressure = "timed" if block.condition.timed else "untimed"
            block_deadline = deadline_ms if block.condition.timed else None
            for index, trial in enumerate(block.trials, 1):
                trials.append(
                    _play_trial(
                        trial,
                        label=f"Block {number}, trial {index} · {cue} · {pressure}",
                        timed=block.condition.timed,
                        landmark=block.condition.landmark,
                        guidance="none",
                        deadline_ms=block_deadline,
                    )
                )
    return {
        "seed": str(seed),
        "participantIndex": str(participant_index),
        "phase": phase,
        "width": WIDTH,
        "height": HEIGHT,
        "start": START,
        "goal": GOAL,
        "centerEntry": CENTER_ENTRY,
        "initialVisible": sorted(INITIAL_VISIBLE_CELLS),
        "trials": trials,
    }


def write_playable(data: PlayData, output: Path) -> None:
    """Embed session data and the participant client in one HTML file."""
    source = Path(__file__).parent
    template = (source / "pilot_play.html").read_text(encoding="utf-8")
    script = (source / "pilot_play.js").read_text(encoding="utf-8")
    json_data = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    html = template.replace("<!-- SESSION_DATA -->", json_data).replace(
        "<!-- PLAY_SCRIPT -->", script
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    """Read and validate the playable export options."""
    parser = argparse.ArgumentParser(
        description="Export an offline playable maze pilot session."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--participant-index", type=int, default=0)
    parser.add_argument("--phase", choices=("test", "pilot"), default="pilot")
    parser.add_argument(
        "--deadline-ms",
        type=int,
        default=None,
        help="First-move deadline for timed test blocks (milliseconds).",
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=None,
        help="Optional cap on exported trials after training/probes are built.",
    )
    parser.add_argument("--output", type=Path, default=Path("build/maze-pilot.html"))
    args = parser.parse_args()
    if args.participant_index < 0:
        parser.error("--participant-index must be nonnegative")
    if args.deadline_ms is not None and args.deadline_ms <= 0:
        parser.error("--deadline-ms must be positive")
    if args.max_trials is not None and args.max_trials <= 0:
        parser.error("--max-trials must be positive")
    return args


def main() -> None:
    """Export the playable session and print its absolute path."""
    args = _parse_args()
    session = play_session(
        args.seed,
        args.participant_index,
        args.phase,
        deadline_ms=args.deadline_ms,
    )
    if args.max_trials is not None:
        session["trials"] = session["trials"][: args.max_trials]
    write_playable(session, args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()

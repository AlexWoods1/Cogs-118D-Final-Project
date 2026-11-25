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

from .maze import (
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
from .maze_trials import (
    Phase,
    Side,
    Symbol,
    Trial,
    generate_blocks,
    generate_probes,
)
from .offline_html import write_offline_html
from .session_cli import (
    add_output_arg,
    add_phase_arg,
    add_seed_participant_args,
    reject_negative_participant_index,
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


def _group_records(
    records: list[dict[str, object]], group_key: str
) -> dict[str, list[dict[str, object]]]:
    """Bucket trial records by a string field, defaulting missing values to unknown."""
    buckets: dict[str, list[dict[str, object]]] = {}
    for record in records:
        key = str(record.get(group_key) or "unknown")
        buckets.setdefault(key, []).append(record)
    return buckets


def summarize_first_choices(
    records: list[dict[str, object]],
    *,
    group_key: str = "kind",
) -> dict[str, dict[str, object]]:
    """Aggregate first decisions and mean RT by cue or landmark group."""
    summary: dict[str, dict[str, object]] = {}
    for key, group in _group_records(records, group_key).items():
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


def summarize_later_continuations(
    records: list[dict[str, object]],
    *,
    group_key: str = "landmark",
) -> dict[str, dict[str, object]]:
    """Aggregate later-junction continuation choices separately from first moves."""
    summary: dict[str, dict[str, object]] = {}
    for key, group in _group_records(records, group_key).items():
        counts = Counter(str(item.get("laterContinuation") or "none") for item in group)
        summary[key] = {"n": len(group), "continuations": dict(counts)}
    return summary


def analyze_session_log(payload: Mapping[str, object]) -> dict[str, object]:
    """Build condition-level reports and a calibrated deadline from a play log."""
    trials = [
        dict(item) for item in payload.get("trials", []) if isinstance(item, Mapping)
    ]
    probes = [
        trial
        for trial in trials
        if trial.get("kind") in {"symbol-only", "aligned", "conflicting"}
    ]
    test_trials = [trial for trial in trials if trial.get("landmark") is not None]
    timed = [trial for trial in test_trials if trial.get("timed")]
    untimed = [trial for trial in test_trials if not trial.get("timed")]
    probe_rts = [
        int(trial["firstChoiceRtMs"])
        for trial in probes
        if isinstance(trial.get("firstChoiceRtMs"), int)
        and trial.get("firstChoice") != "timeout"
    ]
    by_landmark = summarize_first_choices(test_trials, group_key="landmark")
    deltas = {
        landmark: learned_choice_delta(
            [trial for trial in timed if trial.get("landmark") == landmark],
            [trial for trial in untimed if trial.get("landmark") == landmark],
        )
        for landmark in sorted(
            {
                str(trial.get("landmark"))
                for trial in test_trials
                if trial.get("landmark") is not None
            }
        )
    }
    return {
        "seed": payload.get("seed"),
        "participant_index": payload.get("participantIndex")
        or payload.get("participant_index"),
        "phase": payload.get("phase"),
        "n_trials": len(trials),
        "by_cue_kind": summarize_first_choices(probes, group_key="kind"),
        "by_landmark": by_landmark,
        "learned_choice_delta_by_landmark": deltas,
        "later_continuations": summarize_later_continuations(
            test_trials or probes, group_key="landmark" if test_trials else "kind"
        ),
        "calibrated_deadline_ms": (
            calibrate_deadline_ms(probe_rts) if probe_rts else None
        ),
    }


def _append_mapping_section(lines: list[str], title: str, mapping: object) -> None:
    """Append a titled section that lists mapping entries or (none)."""
    lines.extend(["", title])
    if isinstance(mapping, Mapping) and mapping:
        for key, value in mapping.items():
            lines.append(f"  {key}: {value}")
    else:
        lines.append("  (none)")


def format_analysis_report(report: Mapping[str, object]) -> str:
    """Render a plain-text condition report for the terminal or download."""
    lines = [
        f"Seed {report.get('seed')} · Participant {report.get('participant_index')} · "
        f"Phase {report.get('phase')} · Trials {report.get('n_trials')}",
    ]
    _append_mapping_section(
        lines, "First choices by cue kind:", report.get("by_cue_kind")
    )
    _append_mapping_section(
        lines, "First choices by landmark:", report.get("by_landmark")
    )
    _append_mapping_section(
        lines,
        "Timed − untimed learned-choice delta by landmark:",
        report.get("learned_choice_delta_by_landmark"),
    )
    _append_mapping_section(
        lines, "Later continuations:", report.get("later_continuations")
    )
    deadline = report.get("calibrated_deadline_ms")
    lines.extend(
        [
            "",
            f"Calibrated deadline (ms): {deadline if deadline is not None else 'n/a'}",
        ]
    )
    return "\n".join(lines) + "\n"


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
        "beacon": trial.beacon_edge,
        "edges": sorted(trial.maze.open_edges),
        "learned_side": trial.learned_side,
        "learned_route": trial.maze.learned_route,
        "later_junction": trial.maze.later_junction,
        "shortcut_savings": trial.shortcut_savings,
    }


def _training_trial(
    reflected: bool,
    guidance: Guidance,
    label: str,
    *,
    deadline_ms: int,
) -> PlayTrial:
    """Build one symbol-only training trial in a fixed layout orientation."""
    maze = build_template(2, 0)
    if reflected:
        maze = maze.reflected()
    trial = Trial(maze, reflected, None, verify_maze(maze))
    return _play_trial(
        trial,
        label=label,
        timed=True,
        kind="train",
        guidance=guidance,
        deadline_ms=deadline_ms,
    )


def training_trials(*, deadline_ms: int) -> list[PlayTrial]:
    """Train both reflections with full guidance, then fade the path cue."""
    trials: list[PlayTrial] = []
    guidances: tuple[Guidance, ...] = ("full", "fade")
    for guidance in guidances:
        guidance_label = "full guidance" if guidance == "full" else "fading guidance"
        for reflected in (False, True):
            orientation = "reflected" if reflected else "original"
            trials.append(
                _training_trial(
                    reflected,
                    guidance,
                    f"Train · {guidance_label} · {orientation}",
                    deadline_ms=deadline_ms,
                )
            )
    return trials


DEFAULT_DEADLINE_MS = 800


def play_session(
    seed: int,
    participant_index: int,
    phase: Phase,
    *,
    deadline_ms: int | None = None,
) -> PlayData:
    """Assemble the playable schedule for one phase."""
    # Playable export times every first move; CLI default keeps calibration simple.
    first_move_deadline = (
        deadline_ms if deadline_ms is not None else DEFAULT_DEADLINE_MS
    )
    if phase == "pilot":
        trials = training_trials(deadline_ms=first_move_deadline)
        trials.extend(
            _play_trial(
                probe.trial,
                label=f"Probe {number} · {probe.kind}",
                timed=True,
                kind=probe.kind,
                guidance="none",
                deadline_ms=first_move_deadline,
            )
            for number, probe in enumerate(generate_probes(seed, participant_index), 1)
        )
    else:
        trials = []
        for number, block in enumerate(generate_blocks(seed, participant_index), 1):
            cue = f"{block.condition.landmark} beacon"
            for index, trial in enumerate(block.trials, 1):
                trials.append(
                    _play_trial(
                        trial,
                        label=(f"Block {number}, trial {index} · {cue} · timed"),
                        timed=True,
                        landmark=block.condition.landmark,
                        guidance="none",
                        deadline_ms=first_move_deadline,
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
    write_offline_html(
        template_path=source / "pilot_play.html",
        script_path=source / "pilot_play.js",
        data=data,
        output=output,
        data_marker="<!-- SESSION_DATA -->",
        script_marker="<!-- PLAY_SCRIPT -->",
    )


def _parse_args() -> argparse.Namespace:
    """Read and validate the playable export options."""
    parser = argparse.ArgumentParser(
        description="Export or analyze an offline playable maze pilot session."
    )
    add_seed_participant_args(parser)
    add_phase_arg(parser, default="pilot")
    parser.add_argument(
        "--deadline-ms",
        type=int,
        default=DEFAULT_DEADLINE_MS,
        help="First-move deadline for every exported trial (milliseconds).",
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=None,
        help="Optional cap on exported trials after training/probes are built.",
    )
    parser.add_argument(
        "--analyze",
        type=Path,
        default=None,
        help="Analyze a downloaded JSON play log instead of exporting HTML.",
    )
    add_output_arg(parser, default=Path("build/maze-pilot.html"))
    args = parser.parse_args()
    reject_negative_participant_index(parser, args)
    if args.deadline_ms is not None and args.deadline_ms <= 0:
        parser.error("--deadline-ms must be positive")
    if args.max_trials is not None and args.max_trials <= 0:
        parser.error("--max-trials must be positive")
    return args


def main() -> None:
    """Export a playable session or print an analysis report for a saved log."""
    args = _parse_args()
    if args.analyze is not None:
        payload = json.loads(args.analyze.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SystemExit("Play log must be a JSON object")
        print(format_analysis_report(analyze_session_log(payload)), end="")
        return
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

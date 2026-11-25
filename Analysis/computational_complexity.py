"""Empirical computational complexity (InfoRL control information) for pilot logs.

Lancia et al. (2023) define control information as the expected KL divergence
between the agent's policy and a default policy. Here the default is the
trained learned route. For a single deterministic path this reduces to:

    I_hat = sum_t -log2 rho(a_t | s_t)

with a smoothed default so off-route actions stay finite.

Policy complexity I(S;A) (Lai & Gershman, 2024) needs many state-action
samples per condition. A single pilot path log is too sparse for a stable
Hutter MI estimate, so this script reports control information only.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maze_pilot.maze import GOAL, START, Cell, Maze, build_template  # noqa: E402
from maze_pilot.maze_trials import generate_blocks, generate_probes  # noqa: E402

Action = tuple[int, int]


def _delta(first: Cell, second: Cell) -> Action:
    return second[0] - first[0], second[1] - first[1]


def default_action_probs(
    maze: Maze,
    cell: Cell,
    *,
    prefer_mass: float = 0.9,
) -> dict[Action, float]:
    """Build a smoothed default policy at *cell* from the learned route."""
    neighbors = maze.neighbors(cell)
    if not neighbors or cell == GOAL:
        return {}

    actions = [_delta(cell, neighbor) for neighbor in neighbors]
    learned = maze.learned_route
    preferred: Action | None = None
    if cell in learned:
        index = learned.index(cell)
        if index + 1 < len(learned):
            nxt = learned[index + 1]
            if nxt in neighbors:
                preferred = _delta(cell, nxt)

    if preferred is None or preferred not in actions:
        mass = 1.0 / len(actions)
        return {action: mass for action in actions}

    leftover = 1.0 - prefer_mass
    other = [action for action in actions if action != preferred]
    other_mass = leftover / len(other) if other else 0.0
    probs = {preferred: prefer_mass if other else 1.0}
    for action in other:
        probs[action] = other_mass
    return probs


def path_control_information(
    maze: Maze,
    path: Sequence[Sequence[int]],
    *,
    prefer_mass: float = 0.9,
) -> dict[str, float | int]:
    """Return path length and empirical control information in bits."""
    cells = [(int(point[0]), int(point[1])) for point in path]
    if len(cells) < 2:
        return {"steps": 0, "control_information_bits": 0.0, "default_follow_rate": 1.0}

    cost = 0.0
    followed = 0
    decisions = 0
    for current, nxt in zip(cells, cells[1:]):
        if current == GOAL:
            break
        action = _delta(current, nxt)
        probs = default_action_probs(maze, current, prefer_mass=prefer_mass)
        if not probs:
            continue
        decisions += 1
        preferred = max(probs, key=probs.get)
        if action == preferred:
            followed += 1
        probability = probs.get(action)
        if probability is None or probability <= 0:
            # Illegal under maze edges: treat as max-smoothed off-default mass.
            probability = min(probs.values())
        cost += -math.log2(probability)

    return {
        "steps": len(cells) - 1,
        "control_information_bits": cost,
        "default_follow_rate": followed / decisions if decisions else 1.0,
    }


def trial_schedule(
    seed: int, participant_index: int, phase: str = "test"
) -> list[Maze]:
    """Return mazes in the same order as the playable export for *phase*."""
    if phase == "pilot":
        training: list[Maze] = []
        for _guidance in ("full", "fade"):
            for reflected in (False, True):
                maze = build_template(2, 0)
                training.append(maze.reflected() if reflected else maze)
        return training + [
            probe.trial.maze for probe in generate_probes(seed, participant_index)
        ]
    return [
        trial.maze
        for block in generate_blocks(seed, participant_index)
        for trial in block.trials
    ]


def final_attempts(
    trials: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Keep the last logged attempt for each trial index (restarts overwrite)."""
    by_index: dict[int, Mapping[str, object]] = {}
    for trial in trials:
        by_index[int(trial["trialIndex"])] = trial
    return [by_index[index] for index in sorted(by_index)]


def analyze_log(
    payload: Mapping[str, object],
    *,
    prefer_mass: float = 0.9,
) -> list[dict[str, object]]:
    """Score each logged trial's path against its learned default policy."""
    seed = int(payload["seed"])
    participant_index = int(
        payload.get("participantIndex") or payload.get("participant_index") or 0
    )
    phase = str(payload.get("phase") or "test")
    mazes = trial_schedule(seed, participant_index, phase)
    raw = [item for item in payload.get("trials", []) if isinstance(item, Mapping)]
    rows: list[dict[str, object]] = []
    for trial in final_attempts(raw):
        index = int(trial["trialIndex"])
        if index >= len(mazes):
            continue
        path = trial.get("path") or []
        if not isinstance(path, Sequence) or len(path) < 2:
            continue
        metrics = path_control_information(mazes[index], path, prefer_mass=prefer_mass)
        rows.append(
            {
                "seed": seed,
                "participant_index": participant_index,
                "phase": phase,
                "trial_index": index,
                "trial_number": index + 1,
                "kind": trial.get("kind"),
                "label": trial.get("label"),
                "landmark": trial.get("landmark"),
                "timed": bool(trial.get("timed")),
                "first_choice": trial.get("firstChoice"),
                "first_choice_rt_ms": trial.get("firstChoiceRtMs"),
                "later_continuation": trial.get("laterContinuation"),
                "reached_goal": bool(trial.get("reachedGoal")),
                "start": list(START),
                "goal": list(GOAL),
                **metrics,
            }
        )
    return rows


def write_csv(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    """Write one complexity row per trial."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plot_control_information(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    """Bar plot of control information by trial, colored by first choice."""
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    colors = {
        "shortcut": "#1f77b4",
        "learned": "#2ca02c",
        "other": "#d62728",
        "timeout": "#7f7f7f",
        "none": "#7f7f7f",
    }
    xs = [int(row["trial_number"]) for row in rows]
    ys = [float(row["control_information_bits"]) for row in rows]
    bar_colors = [colors.get(str(row["first_choice"]), "#7f7f7f") for row in rows]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)
    ax = axes[0]
    ax.bar(xs, ys, color=bar_colors, edgecolor="#333333", linewidth=0.4)
    ax.set_xlabel("Trial number")
    ax.set_ylabel("Control information (bits)")
    ax.set_title("Computational complexity by trial")
    ax.set_xticks(xs)
    for choice, color in (
        ("shortcut", colors["shortcut"]),
        ("learned", colors["learned"]),
        ("other", colors["other"]),
    ):
        ax.plot([], [], color=color, linewidth=6, label=choice)
    ax.legend(title="First choice", frameon=False)

    ax2 = axes[1]
    timed_vals = [
        float(row["control_information_bits"]) for row in rows if row["timed"]
    ]
    untimed_vals = [
        float(row["control_information_bits"]) for row in rows if not row["timed"]
    ]
    if timed_vals and untimed_vals:
        ax2.boxplot(
            [untimed_vals, timed_vals],
            tick_labels=["Untimed", "Timed"],
            patch_artist=True,
            boxprops={"facecolor": "#dddddd"},
        )
        ax2.set_title("Timed vs untimed")
    else:
        # Playable exports currently time every first move; group by cue kind instead.
        groups: dict[str, list[float]] = {}
        for row in rows:
            key = str(row.get("kind") or row.get("landmark") or "trial")
            groups.setdefault(key, []).append(float(row["control_information_bits"]))
        labels = sorted(groups)
        ax2.boxplot(
            [groups[label] for label in labels],
            tick_labels=labels,
            patch_artist=True,
            boxprops={"facecolor": "#dddddd"},
        )
        ax2.tick_params(axis="x", rotation=20)
        ax2.set_title(
            "By cue kind" if any(row.get("kind") for row in rows) else "By group"
        )
    ax2.set_ylabel("Control information (bits)")
    fig.suptitle(
        f"InfoRL control information · seed {rows[0]['seed']} · "
        f"participant {rows[0]['participant_index']}",
        fontsize=12,
    )
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot InfoRL computational complexity from a maze pilot log."
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "Data" / "maze-pilot-log-42-0.json",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "Results",
        help="Directory for the CSV table (default: Results/).",
    )
    parser.add_argument(
        "--media-dir",
        type=Path,
        default=ROOT / "media",
        help="Directory for the PNG plot (default: media/).",
    )
    parser.add_argument(
        "--prefer-mass",
        type=float,
        default=0.9,
        help="Default-policy mass on the next learned-route step (rest split).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    payload = json.loads(args.log.read_text(encoding="utf-8"))
    rows = analyze_log(payload, prefer_mass=args.prefer_mass)
    if not rows:
        raise SystemExit("No scored trials found in log.")

    args.results_dir.mkdir(parents=True, exist_ok=True)
    args.media_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.results_dir / "computational-complexity-42-0.csv"
    plot_path = args.media_dir / "computational-complexity-42-0.png"
    write_csv(rows, csv_path)
    plot_control_information(rows, plot_path)

    mean_bits = sum(float(row["control_information_bits"]) for row in rows) / len(rows)
    print(f"trials={len(rows)}")
    print(f"mean_control_information_bits={mean_bits:.3f}")
    print(csv_path)
    print(plot_path)


if __name__ == "__main__":
    main()

"""Plot logged pilot paths into media/ and Results/."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(PROJECT))

from maze_pilot.maze import HEIGHT, WIDTH, Maze, build_template  # noqa: E402
from maze_pilot.maze_trials import generate_blocks, generate_probes  # noqa: E402
from maze_pilot.trial_config import PARTICIPANT_EXPORT_COUNT  # noqa: E402

CHOICE_COLOR = {
    "shortcut": "#1f77b4",
    "learned": "#2ca02c",
    "other": "#d62728",
    "timeout": "#7f7f7f",
    "none": "#7f7f7f",
}


def trial_schedule(seed: int, participant_index: int, phase: str) -> list[Maze]:
    """Match playable export order for the logged phase."""
    slot = participant_index % PARTICIPANT_EXPORT_COUNT
    if phase == "pilot":
        training: list[Maze] = []
        for _guidance in ("full", "fade"):
            for reflected in (False, True):
                maze = build_template(2, 0)
                training.append(maze.reflected() if reflected else maze)
        return training + [probe.trial.maze for probe in generate_probes(seed, slot)]
    return [
        trial.maze for block in generate_blocks(seed, slot) for trial in block.trials
    ]


def final_attempts(
    trials: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Keep the last logged attempt for each trial index."""
    by_index: dict[int, Mapping[str, object]] = {}
    for trial in trials:
        by_index[int(trial["trialIndex"])] = trial
    return [by_index[index] for index in sorted(by_index)]


def plot_log(log_path: Path, media_dir: Path, results_dir: Path) -> tuple[Path, Path]:
    """Render one session path grid; return media and Results PNG paths."""
    log = json.loads(log_path.read_text(encoding="utf-8"))
    phase = str(log.get("phase") or "test")
    seed = int(log["seed"])
    participant = int(log.get("participantIndex") or log.get("participant_index") or 0)
    mazes = trial_schedule(seed, participant, phase)
    trials = final_attempts(
        [item for item in log["trials"] if isinstance(item, Mapping)]
    )
    scored = [
        (trial, mazes[int(trial["trialIndex"])])
        for trial in trials
        if int(trial["trialIndex"]) < len(mazes)
        and isinstance(trial.get("path"), Sequence)
        and len(trial["path"]) >= 2
    ]
    if not scored:
        raise SystemExit(f"No scored paths found in {log_path}")

    cols = 4
    nrows = math.ceil(len(scored) / cols)
    fig, axes = plt.subplots(
        nrows, cols, figsize=(3.4 * cols, 2.6 * nrows), constrained_layout=True
    )
    flat = list(axes.ravel()) if hasattr(axes, "ravel") else [axes]
    fig.suptitle(
        f"{phase.capitalize()} session paths · seed {seed} · participant {participant}",
        fontsize=14,
    )

    for ax in flat[len(scored) :]:
        ax.set_visible(False)

    for ax, (trial, maze) in zip(flat, scored, strict=False):
        for first, second in maze.open_edges:
            ax.plot(
                [first[0], second[0]],
                [first[1], second[1]],
                color="#dddddd",
                lw=6,
                solid_capstyle="round",
                zorder=1,
            )
        path = trial["path"]
        xs = [point[0] for point in path]
        ys = [point[1] for point in path]
        color = CHOICE_COLOR.get(str(trial.get("firstChoice") or "none"), "#7f7f7f")
        ax.plot(xs, ys, color=color, lw=2.2, zorder=3)
        ax.scatter([xs[0]], [ys[0]], c="#111111", s=28, zorder=4)
        ax.scatter([xs[-1]], [ys[-1]], c="#e67e22", s=36, marker="*", zorder=4)
        short = str(trial.get("label") or "").replace(" · ", "\n")
        ax.set_title(
            f"T{int(trial['trialIndex']) + 1}: {trial.get('firstChoice')}\n{short}",
            fontsize=7,
        )
        ax.set_xlim(-0.5, WIDTH - 0.5)
        ax.set_ylim(HEIGHT - 0.5, -0.5)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    stem = f"trial-paths-{seed}-{participant}.png"
    media_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    out = media_dir / stem
    results_copy = results_dir / stem
    fig.savefig(out, dpi=160)
    fig.savefig(results_copy, dpi=160)
    plt.close(fig)
    return out, results_copy


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot maze paths from a pilot log.")
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "maze-pilot-log-42-0.json",
    )
    parser.add_argument("--media-dir", type=Path, default=PROJECT / "media")
    parser.add_argument("--results-dir", type=Path, default=PROJECT / "Results")
    args = parser.parse_args()
    out, results_copy = plot_log(args.log, args.media_dir, args.results_dir)
    print(out)
    print(results_copy)


if __name__ == "__main__":
    main()

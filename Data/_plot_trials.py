"""One-off plot of logged pilot paths (seed 42, participant 0)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(PROJECT))

from maze_pilot.maze import HEIGHT, WIDTH  # noqa: E402
from maze_pilot.maze_trials import generate_blocks  # noqa: E402

LOG = ROOT / "maze-pilot-log-42-0 (1).json"
OUT = PROJECT / "media" / "trial-paths-42-0.png"

CHOICE_COLOR = {
    "shortcut": "#1f77b4",
    "learned": "#2ca02c",
    "other": "#d62728",
    "none": "#7f7f7f",
}


def main() -> None:
    log = json.loads(LOG.read_text(encoding="utf-8"))
    mazes = [trial.maze for block in generate_blocks(42, 0) for trial in block.trials]
    trials = log["trials"]
    if len(trials) != len(mazes):
        raise SystemExit(
            f"trial count mismatch: log={len(trials)} schedule={len(mazes)}"
        )

    fig, axes = plt.subplots(3, 4, figsize=(14, 10), constrained_layout=True)
    fig.suptitle("Pilot session paths · seed 42 · participant 0", fontsize=14)

    for ax, trial, maze in zip(axes.ravel(), trials, mazes, strict=True):
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
        color = CHOICE_COLOR.get(trial.get("firstChoice") or "none", "#7f7f7f")
        ax.plot(xs, ys, color=color, lw=2.2, zorder=3)
        ax.scatter([xs[0]], [ys[0]], c="#111111", s=28, zorder=4)
        ax.scatter([xs[-1]], [ys[-1]], c="#e67e22", s=36, marker="*", zorder=4)
        short = (trial.get("label") or "").replace(" · ", "\n")
        ax.set_title(
            f"T{trial['trialIndex'] + 1}: {trial.get('firstChoice')}\n{short}",
            fontsize=7,
        )
        ax.set_xlim(-0.5, WIDTH - 0.5)
        ax.set_ylim(HEIGHT - 0.5, -0.5)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    fig.savefig(OUT, dpi=160)
    print(OUT)


if __name__ == "__main__":
    main()

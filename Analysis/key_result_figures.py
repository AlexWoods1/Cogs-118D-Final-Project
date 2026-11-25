"""Two summary figures for the pilot cohort key results."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Data"
RESULTS = ROOT / "Results"
PROBE_KINDS = ("symbol-only", "aligned", "conflicting")
KIND_LABELS = {
    "symbol-only": "Symbol only",
    "aligned": "Aligned beacon",
    "conflicting": "Conflicting beacon",
}


def load_probes() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(DATA.glob("maze-pilot-log-42-200*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("completed") is not True:
            continue
        tsn = str(payload.get("participantIndex") or payload.get("participant_index"))
        for trial in payload.get("trials") or []:
            if trial.get("kind") not in PROBE_KINDS:
                continue
            rows.append(
                {
                    "tsn": tsn,
                    "kind": trial["kind"],
                    "choice": trial.get("firstChoice") or "none",
                    "rt": trial.get("firstChoiceRtMs"),
                }
            )
    return rows


def figure_cue_effect(probes: list[dict], path: Path) -> None:
    """Key result 1: cue type shifts learned vs shortcut first choices."""
    learned_rates = []
    shortcut_rates = []
    for kind in PROBE_KINDS:
        subset = [row for row in probes if row["kind"] == kind]
        n = len(subset) or 1
        learned_rates.append(sum(1 for row in subset if row["choice"] == "learned") / n)
        shortcut_rates.append(
            sum(1 for row in subset if row["choice"] == "shortcut") / n
        )

    x = np.arange(len(PROBE_KINDS))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 4.4), constrained_layout=True)
    ax.bar(
        x - width / 2,
        learned_rates,
        width,
        label="Learned route",
        color="#2ca02c",
        edgecolor="#222222",
        linewidth=0.5,
    )
    ax.bar(
        x + width / 2,
        shortcut_rates,
        width,
        label="Shortcut",
        color="#1f77b4",
        edgecolor="#222222",
        linewidth=0.5,
    )
    ax.set_xticks(x)
    ax.set_xticklabels([KIND_LABELS[k] for k in PROBE_KINDS])
    ax.set_ylim(0, 0.55)
    ax.set_ylabel("Proportion of probe first choices")
    ax.set_title("Cue type shifts first-choice strategy (N = 3, 72 probes)")
    ax.legend(frameon=False, loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for i, (learn, short) in enumerate(zip(learned_rates, shortcut_rates, strict=True)):
        ax.text(i - width / 2, learn + 0.015, f"{learn:.0%}", ha="center", fontsize=9)
        ax.text(i + width / 2, short + 0.015, f"{short:.0%}", ha="center", fontsize=9)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def figure_individual_strategies(probes: list[dict], path: Path) -> None:
    """Key result 2: participants use very different strategies."""
    by_tsn: dict[str, list[dict]] = defaultdict(list)
    for row in probes:
        by_tsn[row["tsn"]].append(row)
    tsns = sorted(by_tsn)

    learned = []
    shortcut = []
    other = []
    timeout = []
    tick_labels = []
    for tsn in tsns:
        counts = Counter(row["choice"] for row in by_tsn[tsn])
        n = len(by_tsn[tsn]) or 1
        learned.append(counts.get("learned", 0) / n)
        shortcut.append(counts.get("shortcut", 0) / n)
        other.append(counts.get("other", 0) / n)
        timeout.append(counts.get("timeout", 0) / n)
        dominant, n_dom = counts.most_common(1)[0]
        tick_labels.append(f"TSN {tsn}\n{dominant} {n_dom}/{n}")

    x = np.arange(len(tsns))
    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    bottoms = np.zeros(len(tsns))
    layers = [
        ("Learned", learned, "#2ca02c"),
        ("Shortcut", shortcut, "#1f77b4"),
        ("Other", other, "#d62728"),
        ("Timeout", timeout, "#7f7f7f"),
    ]
    for label, heights, color in layers:
        ax.bar(
            x,
            heights,
            bottom=bottoms,
            label=label,
            color=color,
            edgecolor="#222222",
            linewidth=0.4,
            width=0.62,
        )
        bottoms = bottoms + np.array(heights)

    ax.set_xticks(x)
    ax.set_xticklabels(tick_labels, fontsize=9)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Proportion of probe first choices")
    ax.set_title("Large between-person strategy differences", pad=12)
    ax.legend(
        frameon=False,
        ncol=4,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        columnspacing=1.4,
        handlelength=1.2,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.subplots_adjust(bottom=0.28, top=0.9)
    fig.savefig(path, dpi=180)
    plt.close(fig)


def main() -> None:
    probes = load_probes()
    if not probes:
        raise SystemExit("No completed probe trials found under Data/.")
    RESULTS.mkdir(parents=True, exist_ok=True)
    cue_path = RESULTS / "key-result-cue-first-choice.png"
    strategy_path = RESULTS / "key-result-individual-strategy.png"
    figure_cue_effect(probes, cue_path)
    figure_individual_strategies(probes, strategy_path)
    print(cue_path)
    print(strategy_path)
    print(f"probes={len(probes)}")


if __name__ == "__main__":
    main()

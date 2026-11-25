"""Aggregate Neon/local pilot logs into cohort tables and summary plots.

Reads completed session JSON under Data/ (or paths passed on the CLI), scores
control information with ``computational_complexity.analyze_log``, and writes
cohort CSV plus first-choice / RT / complexity figures under Results/.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = Path(__file__).resolve().parent
for path in (ROOT, ANALYSIS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from computational_complexity import analyze_log  # noqa: E402

PROBE_KINDS = ("symbol-only", "aligned", "conflicting")
CHOICE_ORDER = ("learned", "shortcut", "other", "timeout")
CHOICE_COLORS = {
    "learned": "#2ca02c",
    "shortcut": "#1f77b4",
    "other": "#d62728",
    "timeout": "#7f7f7f",
}


def discover_logs(data_dir: Path) -> list[Path]:
    """Prefer completed Neon exports; fall back to every maze-pilot-log JSON."""
    paths = sorted(data_dir.glob("maze-pilot-log-*.json"))
    completed: list[Path] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if payload.get("completed") is True:
            completed.append(path)
    return completed or paths


def load_rows(paths: Sequence[Path]) -> list[dict[str, object]]:
    """Score every log and tag rows with source path."""
    rows: list[dict[str, object]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scored = analyze_log(payload)
        for row in scored:
            row["source"] = path.name
            rows.append(row)
    return rows


def write_csv(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    """Write the cohort trial table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def summarize_participant(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """One row of per-participant descriptive stats."""
    participant = rows[0]["participant_index"]
    seed = rows[0]["seed"]
    choices = Counter(str(row["first_choice"]) for row in rows)
    rts = [
        float(row["first_choice_rt_ms"])
        for row in rows
        if isinstance(row.get("first_choice_rt_ms"), (int, float))
    ]
    bits = [float(row["control_information_bits"]) for row in rows]
    steps = [int(row["steps"]) for row in rows]
    probes = [row for row in rows if row.get("kind") in PROBE_KINDS]
    by_kind: dict[str, dict[str, object]] = {}
    for kind in PROBE_KINDS:
        subset = [row for row in probes if row.get("kind") == kind]
        kind_choices = Counter(str(row["first_choice"]) for row in subset)
        kind_rts = [
            float(row["first_choice_rt_ms"])
            for row in subset
            if isinstance(row.get("first_choice_rt_ms"), (int, float))
        ]
        by_kind[kind] = {
            "n": len(subset),
            "learned": kind_choices.get("learned", 0),
            "shortcut": kind_choices.get("shortcut", 0),
            "other": kind_choices.get("other", 0),
            "timeout": kind_choices.get("timeout", 0),
            "mean_rt_ms": _mean(kind_rts),
        }
    return {
        "participant_index": participant,
        "seed": seed,
        "n_trials": len(rows),
        "n_probes": len(probes),
        "choices": dict(choices),
        "mean_rt_ms": _mean(rts),
        "median_rt_ms": _median(rts),
        "mean_steps": _mean([float(s) for s in steps]),
        "mean_control_bits": _mean(bits),
        "median_control_bits": _median(bits),
        "by_kind": by_kind,
        "calibrated_deadline_hint_ms": (
            int(round(statistics.quantiles(rts, n=10)[6])) if len(rts) >= 10 else None
        ),
    }


def cohort_probe_table(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    """Aggregate probe first choices across participants."""
    probes = [row for row in rows if row.get("kind") in PROBE_KINDS]
    out: dict[str, dict[str, object]] = {}
    for kind in PROBE_KINDS:
        subset = [row for row in probes if row.get("kind") == kind]
        choices = Counter(str(row["first_choice"]) for row in subset)
        rts = [
            float(row["first_choice_rt_ms"])
            for row in subset
            if isinstance(row.get("first_choice_rt_ms"), (int, float))
        ]
        bits = [float(row["control_information_bits"]) for row in subset]
        out[kind] = {
            "n": len(subset),
            "learned": choices.get("learned", 0),
            "shortcut": choices.get("shortcut", 0),
            "other": choices.get("other", 0),
            "timeout": choices.get("timeout", 0),
            "mean_rt_ms": _mean(rts),
            "mean_control_bits": _mean(bits),
        }
    return out


def plot_cohort(
    rows: Sequence[Mapping[str, object]],
    path: Path,
) -> None:
    """First-choice rates, RTs, and control information by cue kind."""
    import matplotlib.pyplot as plt
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    probes = [row for row in rows if row.get("kind") in PROBE_KINDS]
    participants = sorted({int(row["participant_index"]) for row in probes})
    kinds = list(PROBE_KINDS)

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), constrained_layout=True)

    # Panel 1: stacked first-choice rates by cue kind (cohort).
    ax = axes[0]
    bottoms = np.zeros(len(kinds))
    for choice in CHOICE_ORDER:
        heights = []
        for kind in kinds:
            subset = [row for row in probes if row.get("kind") == kind]
            n = len(subset) or 1
            count = sum(1 for row in subset if row.get("first_choice") == choice)
            heights.append(count / n)
        ax.bar(
            kinds,
            heights,
            bottom=bottoms,
            color=CHOICE_COLORS[choice],
            edgecolor="#333333",
            linewidth=0.4,
            label=choice,
        )
        bottoms = bottoms + np.array(heights)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Proportion of first choices")
    ax.set_title("Probe first choices by cue")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.tick_params(axis="x", rotation=15)

    # Panel 2: mean RT by cue × participant.
    ax = axes[1]
    width = 0.8 / max(len(participants), 1)
    x = np.arange(len(kinds))
    for index, participant in enumerate(participants):
        means = []
        for kind in kinds:
            rts = [
                float(row["first_choice_rt_ms"])
                for row in probes
                if int(row["participant_index"]) == participant
                and row.get("kind") == kind
                and isinstance(row.get("first_choice_rt_ms"), (int, float))
            ]
            means.append(_mean(rts) or 0.0)
        ax.bar(
            x + index * width - 0.4 + width / 2,
            means,
            width=width,
            label=str(participant),
            edgecolor="#333333",
            linewidth=0.3,
        )
    ax.set_xticks(x)
    ax.set_xticklabels(kinds, rotation=15)
    ax.set_ylabel("Mean first-choice RT (ms)")
    ax.set_title("RT by cue and participant")
    ax.legend(title="TSN", frameon=False, fontsize=7)

    # Panel 3: control information by cue kind.
    ax = axes[2]
    groups = [
        [
            float(row["control_information_bits"])
            for row in probes
            if row.get("kind") == kind
        ]
        for kind in kinds
    ]
    ax.boxplot(
        groups,
        tick_labels=kinds,
        patch_artist=True,
        boxprops={"facecolor": "#dddddd"},
    )
    ax.set_ylabel("Control information (bits)")
    ax.set_title("Path complexity by cue")
    ax.tick_params(axis="x", rotation=15)

    fig.suptitle(
        f"Pilot cohort · {len(participants)} participants · {len(probes)} probes",
        fontsize=12,
    )
    fig.savefig(path, dpi=160)
    plt.close(fig)


def write_markdown_summary(
    participant_summaries: Sequence[Mapping[str, object]],
    probe_table: Mapping[str, Mapping[str, object]],
    path: Path,
) -> None:
    """Machine-readable companion for the human RESULTS note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "n_participants": len(participant_summaries),
        "participants": list(participant_summaries),
        "probe_aggregate": dict(probe_table),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate pilot logs into cohort Results artifacts."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "Data",
        help="Directory with maze-pilot-log-*.json exports.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "Results",
    )
    parser.add_argument(
        "logs",
        nargs="*",
        type=Path,
        help="Optional explicit log paths (default: completed logs in Data/).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    paths = (
        [path.resolve() for path in args.logs]
        if args.logs
        else discover_logs(args.data_dir)
    )
    if not paths:
        raise SystemExit("No pilot logs found.")

    rows = load_rows(paths)
    if not rows:
        raise SystemExit("No scored trials in the provided logs.")

    args.results_dir.mkdir(parents=True, exist_ok=True)
    cohort_csv = args.results_dir / "pilot-cohort-trials.csv"
    write_csv(rows, cohort_csv)

    by_participant: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        by_participant[int(row["participant_index"])].append(row)
    summaries = [
        summarize_participant(by_participant[pid]) for pid in sorted(by_participant)
    ]
    probe_table = cohort_probe_table(rows)

    summary_json = args.results_dir / "pilot-cohort-summary.json"
    write_markdown_summary(summaries, probe_table, summary_json)

    plot_path = args.results_dir / "pilot-cohort-summary.png"
    plot_cohort(rows, plot_path)

    print(f"participants={len(summaries)}")
    print(f"trials={len(rows)}")
    for summary in summaries:
        print(
            f"TSN {summary['participant_index']}: "
            f"choices={summary['choices']} "
            f"mean_rt={summary['mean_rt_ms']:.0f}ms "
            f"mean_bits={summary['mean_control_bits']:.2f}"
        )
    print(cohort_csv)
    print(summary_json)
    print(plot_path)


if __name__ == "__main__":
    main()

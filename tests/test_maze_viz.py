import json
import re
import sys
from itertools import pairwise
from pathlib import Path

import pytest

import maze_pilot.maze_viz as maze_viz
from maze_pilot.maze import (
    CENTER_ENTRY,
    GOAL,
    HEIGHT,
    INITIAL_VISIBLE_CELLS,
    START,
    WIDTH,
)
from maze_pilot.maze_trials import BEACON_EDGES, generate_blocks, generate_probes


@pytest.mark.parametrize(
    "seed, participant_index", [(42, 0), (-(2**53 + 1), 2**53 + 5)]
)
def test_preview_export_matches_the_generated_schedule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    seed: int,
    participant_index: int,
) -> None:
    """Check that the offline preview encodes both schedules and valid paths."""
    output = tmp_path / "nested" / "preview.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maze_viz",
            "--output",
            str(output),
            "--seed",
            str(seed),
            "--participant-index",
            str(participant_index),
        ],
    )
    maze_viz.main()

    assert capsys.readouterr().out.strip() == str(output.resolve())
    html = output.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<!-- PREVIEW_SCRIPT -->" not in html
    assert "function drawMaze(" in html
    embedded = re.search(
        r'<script type="application/json" id="data">(.*?)</script>', html
    )
    assert embedded is not None
    data = json.loads(embedded[1])
    assert (data["seed"], data["participantIndex"]) == (
        str(seed),
        str(participant_index),
    )
    assert (data["width"], data["height"]) == (WIDTH, HEIGHT)
    assert (data["start"], data["goal"]) == (list(START), list(GOAL))
    assert list(map(tuple, data["visible"])) == sorted(INITIAL_VISIBLE_CELLS)

    blocks = generate_blocks(seed, participant_index)
    probes = generate_probes(seed, participant_index)
    test_trials = [trial for block in blocks for trial in block.trials]
    for phase, expected in [
        ("test", test_trials),
        ("pilot", [p.trial for p in probes]),
    ]:
        for record, trial in zip(data[phase], expected, strict=True):
            assert record["reflected"] is trial.reflected
            assert record["symbol"] == trial.orientation_symbol
            beacon = BEACON_EDGES[trial.beacon_side] if trial.beacon_side else None
            assert record["beacon"] == (list(map(list, beacon)) if beacon else None)
            assert [tuple(map(tuple, edge)) for edge in record["edges"]] == sorted(
                trial.maze.open_edges
            )
            assert tuple(map(tuple, record["learned"])) == trial.maze.learned_route
            assert tuple(record["junction"]) == trial.maze.later_junction
            # A visually plausible shortcut still has to follow open edges.
            shortcut = tuple(map(tuple, record["shortcut"]))
            assert shortcut[:2] == (START, CENTER_ENTRY)
            assert shortcut[-1] == GOAL
            assert all(trial.maze.can_move(a, b) for a, b in pairwise(shortcut))
            assert (
                len(trial.maze.learned_route) - len(shortcut) == trial.shortcut_savings
            )

    offset = 0
    for block_index, block in enumerate(blocks, 1):
        cue = block.condition.landmark.capitalize()
        pressure = "Timed" if block.condition.timed else "Untimed"
        for trial_index in range(1, len(block.trials) + 1):
            assert data["test"][offset]["label"] == (
                f"Block {block_index}, trial {trial_index} · {cue} beacon · {pressure}"
            )
            offset += 1

    probe_labels = {
        "symbol-only": "Symbol only",
        "aligned": "Aligned beacon",
        "conflicting": "Conflicting beacon",
    }
    assert [record["label"] for record in data["pilot"]] == [
        f"Probe {index} · {probe_labels[probe.kind]}"
        for index, probe in enumerate(probes, 1)
    ]


def test_preview_cli_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check the default output path and default session parameters."""
    # Isolate the relative build path so the test cannot overwrite a local preview.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["maze_viz"])

    maze_viz.main()

    html = (tmp_path / "build" / "maze-preview.html").read_text(encoding="utf-8")
    assert '"seed":"42"' in html
    assert '"participantIndex":"0"' in html


def test_preview_rejects_a_negative_participant_index(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Check that an invalid participant index produces a CLI usage error."""
    monkeypatch.setattr(sys, "argv", ["maze_viz", "--participant-index", "-1"])

    with pytest.raises(SystemExit) as error:
        maze_viz.main()

    # Argparse should stop at validation before generating any files.
    assert error.value.code == 2
    assert "--participant-index must be nonnegative" in capsys.readouterr().err


def test_write_preview_uses_lowercase_asset_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline export must open the committed lowercase HTML and JS assets."""
    calls: list[dict[str, object]] = []

    def capture(**kwargs: object) -> None:
        calls.append(kwargs)
        output = kwargs["output"]
        assert isinstance(output, Path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(maze_viz, "write_offline_html", capture)
    maze_viz._write_preview(maze_viz._preview_data(42, 0), tmp_path / "out.html")
    assert calls[0]["template_path"].name == "maze_viz.html"
    assert calls[0]["script_path"].name == "maze_viz.js"

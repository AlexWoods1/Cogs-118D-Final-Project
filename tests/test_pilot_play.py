import json
import re
import sys
from pathlib import Path

import pytest

import maze_pilot.pilot_play as pilot_play
from maze_pilot.maze import (
    CENTER_ENTRY,
    GOAL,
    INITIAL_VISIBLE_CELLS,
    START,
    edge_between,
)
from maze_pilot.maze_trials import generate_blocks, generate_probes


def test_classify_first_choice_distinguishes_learned_shortcut_and_other() -> None:
    """Score the first leave-start move using learned_side and the center exit."""
    assert (
        pilot_play.classify_first_choice((START[0] - 1, START[1]), "left") == "learned"
    )
    assert (
        pilot_play.classify_first_choice((START[0] + 1, START[1]), "right") == "learned"
    )
    assert pilot_play.classify_first_choice(CENTER_ENTRY, "left") == "shortcut"
    assert pilot_play.classify_first_choice((START[0] + 1, START[1]), "left") == "other"
    assert (
        pilot_play.classify_first_choice(CENTER_ENTRY, "left", timed_out=True)
        == "timeout"
    )


def test_classify_later_continuation_uses_learned_route() -> None:
    """Score the first departure from the later junction against the trained path."""
    route = (START, (7, 2), (8, 2), (8, 3), GOAL)
    junction = (8, 2)
    assert pilot_play.classify_later_continuation(junction, (8, 3), route) == "learned"
    assert (
        pilot_play.classify_later_continuation(junction, (9, 2), route) == "alternate"
    )


def test_movement_and_fog_helpers_follow_open_edges() -> None:
    """Legal moves require open edges; fog expands by visited cells."""
    open_edges = frozenset({edge_between(START, CENTER_ENTRY)})
    assert pilot_play.can_step(open_edges, START, CENTER_ENTRY)
    assert not pilot_play.can_step(open_edges, START, (START[0] - 1, START[1]))
    visible = frozenset(INITIAL_VISIBLE_CELLS)
    revealed = pilot_play.reveal_after_visit(visible, GOAL)
    assert GOAL in revealed
    assert INITIAL_VISIBLE_CELLS <= revealed


def test_guidance_cells_fade_to_the_first_turn() -> None:
    """Full guidance keeps the route; fade keeps the opening turn only."""
    route = (START, (7, 2), (8, 2), (8, 3), GOAL)
    assert pilot_play.guidance_cells(route, "none") == ()
    assert pilot_play.guidance_cells(route, "fade") == route[:3]
    assert pilot_play.guidance_cells(route, "full") == route


def test_deadline_calibration_uses_untimed_response_times() -> None:
    """Choose a deadline that compresses slow untimed first moves."""
    assert (
        pilot_play.calibrate_deadline_ms([500, 700, 900, 1200], percentile=0.5) == 700
    )
    assert pilot_play.calibrate_deadline_ms([200], floor_ms=400) == 400
    with pytest.raises(ValueError, match="Need untimed response times"):
        pilot_play.calibrate_deadline_ms([])


def test_beacon_visibility_helper() -> None:
    """Beacon cues disappear once both endpoints leave the revealed set."""
    beacon = edge_between((3, 1), (3, 2))
    assert pilot_play.beacon_visible(beacon, frozenset({(3, 1)}))
    assert not pilot_play.beacon_visible(beacon, frozenset({START}))
    assert not pilot_play.beacon_visible(None, frozenset(INITIAL_VISIBLE_CELLS))


def test_moves_to_csv_writes_one_row_per_attempt() -> None:
    """CSV export keeps one line for each attempted move, including blocked ones."""
    csv_text = pilot_play.moves_to_csv(
        [
            {
                "seed": "42",
                "participant_index": "0",
                "phase": "pilot",
                "trial_index": 0,
                "trial_attempt": 1,
                "label": "Train",
                "kind": "train",
                "landmark": "",
                "timed": False,
                "guidance": "full",
                "move_index": 1,
                "event": "move",
                "t_ms": 120,
                "from_x": 6,
                "from_y": 2,
                "to_x": 7,
                "to_y": 2,
                "dx": 1,
                "dy": 0,
                "legal": True,
                "first_choice": "learned",
                "later_continuation": "",
                "beacon_visible_at_junction": "",
                "reached_goal": False,
            },
            {
                "seed": "42",
                "participant_index": "0",
                "phase": "pilot",
                "trial_index": 0,
                "trial_attempt": 1,
                "label": "Train",
                "kind": "train",
                "landmark": "",
                "timed": False,
                "guidance": "full",
                "move_index": 2,
                "event": "move",
                "t_ms": 180,
                "from_x": 7,
                "from_y": 2,
                "to_x": 7,
                "to_y": 1,
                "dx": 0,
                "dy": -1,
                "legal": False,
                "first_choice": "",
                "later_continuation": "",
                "beacon_visible_at_junction": "",
                "reached_goal": False,
            },
        ]
    )
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("seed,participant_index,phase,")
    assert len(lines) == 3
    assert "learned" in lines[1]
    assert lines[2].endswith("False")


def test_summarize_and_delta_compare_cue_conditions() -> None:
    """Aggregate first choices by cue kind and timed-minus-untimed learned rate."""
    records = [
        {"kind": "symbol-only", "firstChoice": "learned", "firstChoiceRtMs": 600},
        {"kind": "symbol-only", "firstChoice": "shortcut", "firstChoiceRtMs": 500},
        {"kind": "aligned", "firstChoice": "learned", "firstChoiceRtMs": 400},
        {"kind": "aligned", "firstChoice": "learned", "firstChoiceRtMs": 450},
    ]
    summary = pilot_play.summarize_first_choices(records)
    assert summary["symbol-only"]["n"] == 2
    assert summary["symbol-only"]["choices"] == {"learned": 1, "shortcut": 1}
    assert summary["aligned"]["mean_rt_ms"] == 425
    timed = [{"firstChoice": "learned"}, {"firstChoice": "shortcut"}]
    untimed = [{"firstChoice": "shortcut"}, {"firstChoice": "shortcut"}]
    assert pilot_play.learned_choice_delta(timed, untimed) == 0.5


def test_analyze_session_log_reports_conditions_and_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Analysis covers cue kinds, landmark deltas, continuations, and calibration."""
    payload = {
        "seed": "42",
        "participantIndex": "0",
        "phase": "test",
        "trials": [
            {
                "kind": "symbol-only",
                "landmark": None,
                "timed": False,
                "firstChoice": "learned",
                "firstChoiceRtMs": 700,
                "laterContinuation": "learned",
            },
            {
                "kind": None,
                "landmark": "informative",
                "timed": False,
                "firstChoice": "shortcut",
                "firstChoiceRtMs": 800,
                "laterContinuation": "alternate",
            },
            {
                "kind": None,
                "landmark": "informative",
                "timed": True,
                "firstChoice": "learned",
                "firstChoiceRtMs": 500,
                "laterContinuation": "learned",
            },
            {
                "kind": None,
                "landmark": "uninformative",
                "timed": False,
                "firstChoice": "learned",
                "firstChoiceRtMs": 650,
                "laterContinuation": "none",
            },
            {
                "kind": None,
                "landmark": "uninformative",
                "timed": True,
                "firstChoice": "learned",
                "firstChoiceRtMs": 450,
                "laterContinuation": "learned",
            },
        ],
    }
    report = pilot_play.analyze_session_log(payload)
    assert report["by_cue_kind"]["symbol-only"]["choices"] == {"learned": 1}
    assert report["learned_choice_delta_by_landmark"]["informative"] == 1.0
    assert report["learned_choice_delta_by_landmark"]["uninformative"] == 0.0
    assert report["later_continuations"]["informative"]["continuations"]["learned"] == 1
    assert report["calibrated_deadline_ms"] == 700
    log_path = tmp_path / "log.json"
    log_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pilot_play", "--analyze", str(log_path)])
    pilot_play.main()
    text = capsys.readouterr().out
    assert "Timed − untimed learned-choice delta" in text
    assert "Calibrated deadline (ms): 700" in text


def test_play_session_includes_training_then_probes() -> None:
    """Pilot sessions train both reflections before the cue probes."""
    pilot = pilot_play.play_session(42, 0, "pilot")
    probes = generate_probes(42, 0)
    train = [trial for trial in pilot["trials"] if trial["kind"] == "train"]
    probe_trials = [trial for trial in pilot["trials"] if trial["kind"] != "train"]
    assert len(train) == 4
    assert {trial["guidance"] for trial in train} == {"full", "fade"}
    assert {trial["reflected"] for trial in train} == {False, True}
    assert all(trial["timed"] and trial["deadline_ms"] == 800 for trial in train)
    assert len(probe_trials) == len(probes)
    for record, probe in zip(probe_trials, probes, strict=True):
        assert record["kind"] == probe.kind
        assert record["guidance"] == "none"
        assert record["timed"] is True
        assert record["deadline_ms"] == 800
        assert record["learned_side"] == probe.trial.learned_side
        assert tuple(record["learned_route"]) == probe.trial.maze.learned_route
        assert tuple(record["later_junction"]) == probe.trial.maze.later_junction


def test_test_session_times_every_trial() -> None:
    """Playable test exports apply the first-move deadline to every trial."""
    session = pilot_play.play_session(42, 0, "test", deadline_ms=800)
    blocks = generate_blocks(42, 0)
    expected = [trial for block in blocks for trial in block.trials]
    assert len(session["trials"]) == len(expected)
    for record, block in zip(
        session["trials"],
        [block for block in blocks for _ in block.trials],
        strict=True,
    ):
        assert record["landmark"] == block.condition.landmark
        assert record["timed"] is True
        assert record["deadline_ms"] == 800


def test_playable_cli_exports_offline_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Export embeds the schedule and participant client without placeholders."""
    output = tmp_path / "nested" / "pilot.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pilot_play",
            "--seed",
            "42",
            "--participant-index",
            "0",
            "--phase",
            "pilot",
            "--output",
            str(output),
        ],
    )
    pilot_play.main()
    assert capsys.readouterr().out.strip() == str(output.resolve())
    html = output.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "<!-- PLAY_SCRIPT -->" not in html
    assert "function tryMove(" in html
    assert "function drawGuidance(" in html
    assert "function movesCsv(" in html
    assert "function renderSessionReport(" in html
    assert 'id="download-csv"' in html
    assert 'id="report"' in html
    embedded = re.search(
        r'<script type="application/json" id="data">(.*?)</script>', html
    )
    assert embedded is not None
    data = json.loads(embedded[1])
    assert data["phase"] == "pilot"
    assert data["seed"] == "42"
    assert len(data["trials"]) == 4 + len(generate_probes(42, 0))


def test_playable_cli_rejects_negative_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a negative participant index before exporting."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["pilot_play", "--seed", "1", "--participant-index", "-1"],
    )
    with pytest.raises(SystemExit):
        pilot_play.main()

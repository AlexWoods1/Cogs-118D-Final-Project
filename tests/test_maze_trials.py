import json
import sys
from collections import Counter
from dataclasses import replace
from itertools import pairwise
from random import Random
from unittest.mock import patch

import pytest

from maze_pilot.maze import (
    CENTER_ENTRY,
    Edge,
    GOAL,
    HEIGHT,
    INITIAL_VISIBLE_CELLS,
    START,
    WIDTH,
    build_template,
    edge_between,
    reflect_cell,
    verify_maze,
)
from maze_pilot.maze_trials import (
    BEACON_EDGES,
    Phase,
    Trial,
    generate_blocks,
    generate_probes,
    main,
)


@pytest.mark.parametrize("detour, savings", [(1, 6), (2, 4), (3, 2)])
def test_layouts_keep_the_initial_view_and_route_cost_under_reflection(
    detour: int, savings: int
) -> None:
    """Check visibility and cost across every variant of a layout."""
    # Invariant endpoints and fog boundaries carry no reflection information.
    assert reflect_cell(START) == START and reflect_cell(GOAL) == GOAL
    assert set(map(reflect_cell, INITIAL_VISIBLE_CELLS)) == INITIAL_VISIBLE_CELLS
    visible_views = set()
    full_layouts = set()
    for variant in range(4):
        maze = build_template(detour, variant)
        mirror = maze.reflected()
        assert mirror.reflected() == maze
        assert mirror.open_edges != maze.open_edges
        assert mirror.initial_visible_edges() == maze.initial_visible_edges()
        assert mirror.learned_route[1][0] < START[0] < maze.learned_route[1][0]
        assert maze.later_junction not in INITIAL_VISIBLE_CELLS
        assert maze.later_junction[1] - START[1] >= 3
        assert verify_maze(maze) == verify_maze(mirror) == savings
        assert len(maze.learned_route) - 1 == 13
        assert maze.distances_to_goal()[CENTER_ENTRY] + 1 == 13 - savings
        assert not any(maze.can_move(*edge) for edge in BEACON_EDGES.values())
        visible_views.add(maze.initial_visible_edges())
        full_layouts.update((maze.open_edges, mirror.open_edges))
    assert len(visible_views) == 1
    assert len(full_layouts) == 8


def test_verifier_rejects_a_wall_that_leaks_orientation() -> None:
    """Reject an extra opening that discloses a hidden orientation."""
    maze = build_template(2, 0)
    # Add a visible opening on only one side of the mirror axis.
    revealing_edge = edge_between((7, 2), (7, 3))
    broken = replace(maze, open_edges=maze.open_edges | {revealing_edge})
    with pytest.raises(
        ValueError, match="^Visible walls reveal the reflection at the first decision$"
    ):
        verify_maze(broken)


@pytest.mark.parametrize(
    "invalid_edge",
    [((-1, 0), (0, 0)), ((0, 0), (1, 1)), ((1, 0), (0, 0))],
    ids=["out-of-bounds", "diagonal", "noncanonical"],
)
def test_verifier_rejects_invalid_edges(invalid_edge: Edge) -> None:
    """Reject openings that cannot represent one canonical grid boundary."""
    maze = build_template(2, 0)
    # Append a malformed edge without disturbing the normal traversable routes.
    broken = replace(maze, open_edges=maze.open_edges | {invalid_edge})
    with pytest.raises(ValueError, match="Invalid open edge"):
        verify_maze(broken)


def test_verifier_requires_the_center_start_exit() -> None:
    """Require the center option at the first decision."""
    maze = build_template(2, 0)
    # Close the center opening, which lies on the mirror axis.
    blocked = edge_between(START, CENTER_ENTRY)
    broken = replace(maze, open_edges=maze.open_edges - {blocked})
    with pytest.raises(ValueError, match="start must have exactly three exits"):
        verify_maze(broken)


def test_verifier_requires_positive_shortcut_savings() -> None:
    """Reject a center route that does not save any moves."""
    maze = build_template(1, 0)
    # Disconnect the shortcut beyond the start while preserving both side routes.
    blocked = edge_between((6, 4), (6, 5))
    broken = replace(maze, open_edges=maze.open_edges - {blocked})
    with pytest.raises(ValueError, match="center entry must provide a shorter route"):
        verify_maze(broken)


def test_verifier_rejects_a_closed_learned_route() -> None:
    """Reject a layout that blocks the learned path."""
    maze = build_template(2, 0)
    # The blocked edge is outside the first view and precedes the later junction.
    blocked_edge = edge_between((10, 5), (10, 6))
    broken = replace(maze, open_edges=maze.open_edges - {blocked_edge})
    with pytest.raises(ValueError, match="learned route"):
        verify_maze(broken)


def test_verifier_requires_an_equally_short_later_choice() -> None:
    """Reject a junction that has only one shortest continuation."""
    maze = build_template(2, 0)
    # Keep the learned continuation open while closing the competing continuation.
    blocked_edge = edge_between((10, 7), (9, 7))
    broken = replace(maze, open_edges=maze.open_edges - {blocked_edge})
    with pytest.raises(ValueError, match="equally short alternative"):
        verify_maze(broken)


def test_schedule_is_reproducible_and_balances_layouts_and_order() -> None:
    """Check scheduling assignments across a complete counterbalance cycle."""
    assert generate_blocks(42, 0) == generate_blocks(42, 0)
    assert generate_blocks(42, 0) != generate_blocks(43, 0)
    block_positions = Counter()
    transitions = Counter()
    layout_assignments = Counter()
    random_cues = set()
    # Sixteen participant indices cover four orders by four variant assignments.
    for participant_index in range(16):
        blocks = generate_blocks(42, participant_index)
        assert len({block.condition for block in blocks}) == 4
        assert len({t.maze.template_id for block in blocks for t in block.trials}) == 12
        for first, second in pairwise(blocks):
            transitions[first.condition, second.condition] += 1
        for position, block in enumerate(blocks):
            block_positions[block.condition, position] += 1
            assert sorted(trial.shortcut_savings for trial in block.trials) == [
                2,
                2,
                4,
                4,
                6,
                6,
            ]
            for trial in block.trials:
                layout_assignments[block.condition, trial.maze.template_id] += 1
                if block.condition.landmark == "informative":
                    assert trial.beacon_side == trial.learned_side
                else:
                    random_cues.add((trial.learned_side, trial.beacon_side))

    assert len(block_positions) == 16 and set(block_positions.values()) == {4}
    assert len(transitions) == 12 and set(transitions.values()) == {4}
    assert len(layout_assignments) == 48 and set(layout_assignments.values()) == {8}
    assert random_cues == {
        ("left", "left"),
        ("left", "right"),
        ("right", "left"),
        ("right", "right"),
    }


def test_probes_cover_both_orientations_for_every_cue_type() -> None:
    """Check coverage and placement for all three pilot cue pairings."""
    probes = generate_probes(42, 0)
    assert probes == generate_probes(42, 0)
    coverage = Counter()
    for probe in probes:
        trial = probe.trial
        # The symbol always follows the geometry, including on conflicting probes.
        coverage[probe.kind, trial.reflected] += 1
        assert trial.orientation_symbol == ("circle" if trial.reflected else "diamond")
        if probe.kind == "symbol-only":
            assert trial.beacon_side is None
        elif probe.kind == "aligned":
            assert trial.beacon_side == trial.learned_side
        else:
            assert trial.beacon_side not in (None, trial.learned_side)
    assert len(coverage) == 6 and set(coverage.values()) == {4}


def _assert_trial_record(record: dict[str, object], trial: Trial) -> None:
    """Check the exported geometry, cues, and scoring fields for one trial."""
    maze = trial.maze
    beacon = BEACON_EDGES[trial.beacon_side] if trial.beacon_side else None
    # JSON represents coordinate pairs and edges as arrays.
    assert record["template_id"] == maze.template_id
    assert record["reflected"] is trial.reflected
    assert record["orientation_symbol"] == trial.orientation_symbol
    assert record["beacon_side"] == trial.beacon_side
    assert record["beacon_edge"] == (list(map(list, beacon)) if beacon else None)
    assert record["open_edges"] == [
        list(map(list, edge)) for edge in sorted(maze.open_edges)
    ]
    assert record["learned_side"] == trial.learned_side
    assert record["learned_route"] == list(map(list, maze.learned_route))
    assert record["later_junction"] == list(maze.later_junction)
    assert record["shortcut_savings"] == trial.shortcut_savings


@pytest.mark.parametrize("phase", ["test", "pilot"])
def test_generator_cli_exports_scoring_metadata(
    phase: Phase, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify the JSON contract used by a downstream participant task."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["maze_trials", "--seed", "81", "--participant-index", "3", "--phase", phase],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert (result["seed"], result["participant_index"], result["phase"]) == (
        81,
        3,
        phase,
    )
    grid = result["grid"]
    assert (grid["width"], grid["height"]) == (WIDTH, HEIGHT)
    assert (grid["start"], grid["goal"]) == (list(START), list(GOAL))
    assert list(map(tuple, grid["initial_visible_cells"])) == sorted(
        INITIAL_VISIBLE_CELLS
    )

    # Check the schedule wrappers before inspecting the common trial fields.
    if phase == "test":
        assert "probes" not in result
        for record, block in zip(result["blocks"], generate_blocks(81, 3), strict=True):
            assert record["landmark"] == block.condition.landmark
            assert record["timed"] is block.condition.timed
            for trial_record, trial in zip(record["trials"], block.trials, strict=True):
                _assert_trial_record(trial_record, trial)
    else:
        assert "blocks" not in result
        for record, probe in zip(result["probes"], generate_probes(81, 3), strict=True):
            assert record["kind"] == probe.kind
            assert record["timed"] is False
            _assert_trial_record(record, probe.trial)


def test_generator_cli_rejects_negative_index(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report a negative participant index through the CLI parser."""
    monkeypatch.setattr(
        sys, "argv", ["maze_trials", "--seed", "81", "--participant-index", "-1"]
    )
    with pytest.raises(SystemExit) as error:
        main()
    # Argparse reports invalid usage on stderr with exit code 2.
    assert error.value.code == 2
    assert "--participant-index must be nonnegative" in capsys.readouterr().err


def test_generator_cli_defaults_to_the_first_test_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Check the JSON defaults when only a seed is supplied."""
    # The seed is the only required option for exporting the first participant.
    monkeypatch.setattr(sys, "argv", ["maze_trials", "--seed", "42"])
    main()
    result = json.loads(capsys.readouterr().out)
    assert (result["seed"], result["participant_index"], result["phase"]) == (
        42,
        0,
        "test",
    )


def test_generate_blocks_uses_the_test_phase_stream() -> None:
    """Block scheduling must key the RNG with the test phase label."""
    with patch("maze_pilot.maze_trials._session_rng", return_value=Random(0)) as rng:
        generate_blocks(11, 2)
    rng.assert_called_once_with(11, 2, "test")


def test_generate_probes_uses_the_pilot_phase_stream() -> None:
    """Probe scheduling must key the RNG with the pilot phase and seed."""
    with patch("maze_pilot.maze_trials._session_rng", return_value=Random(0)) as rng:
        generate_probes(11, 2)
    rng.assert_called_once_with(11, 2, "pilot")

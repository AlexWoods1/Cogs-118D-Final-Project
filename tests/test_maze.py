"""Direct unit tests for maze geometry and verification helpers."""

from dataclasses import replace

import pytest

from maze import (
    CENTER_ENTRY,
    GOAL,
    INITIAL_VISIBLE_CELLS,
    SIDE_EXITS,
    START,
    Maze,
    _path,
    _verify_edges,
    _verify_learned_route,
    _verify_start_exits,
    build_template,
    edge_between,
    reflect_cell,
    verify_maze,
)
from maze_trials import _learned_side, _session_rng, grid_metadata


def test_edge_between_uses_lexicographic_order() -> None:
    """Canonical edge pairs must be independent of endpoint order."""
    first, second = (1, 0), (0, 0)
    canonical = ((0, 0), (1, 0))
    assert edge_between(first, second) == edge_between(second, first) == canonical
    # Distinct equal-priority pairs still canonicalize with a strict `<` check.
    assert edge_between((2, 1), (2, 0)) == ((2, 0), (2, 1))


def test_reflect_cell_fixes_the_center_column() -> None:
    """Mirror coordinates twice returns the original cell."""
    left = (5, 4)
    assert reflect_cell(reflect_cell(left)) == left
    assert reflect_cell(START) == START


def test_neighbors_and_can_move_follow_open_edges() -> None:
    """Movement queries consult only the stored open-edge set."""
    maze = build_template(2, 0)
    assert maze.can_move(START, CENTER_ENTRY)
    # Exact STEPS order catches left/right or up/down sign flips.
    assert maze.neighbors(START) == (
        (START[0] - 1, START[1]),
        (START[0] + 1, START[1]),
        CENTER_ENTRY,
    )
    assert maze.neighbors(CENTER_ENTRY) == (
        START,
        (CENTER_ENTRY[0], CENTER_ENTRY[1] + 1),
    )
    assert maze.can_move(START, GOAL) is False


def test_distances_to_goal_honors_avoid() -> None:
    """Excluding the goal returns no reachable distances."""
    maze = build_template(2, 0)
    assert maze.distances_to_goal(avoid=GOAL) == {}


def test_distances_to_goal_continues_after_an_avoided_neighbor() -> None:
    """Avoiding one goal neighbor must not stop the search at that cell."""
    maze = build_template(2, 0)
    avoid = (GOAL[0] - 1, GOAL[1])
    distances = maze.distances_to_goal(avoid=avoid)
    assert avoid not in distances
    assert START in distances
    assert (GOAL[0] + 1, GOAL[1]) in distances


def test_distances_to_goal_reaches_start_without_revisit_loops() -> None:
    """BFS must reach S with finite distances and never re-expand cells."""
    maze = build_template(2, 0)
    distances = maze.distances_to_goal()
    assert START in distances
    assert distances[GOAL] == 0
    assert distances[CENTER_ENTRY] == distances[START] - 1
    assert len(distances) <= len(maze.open_edges) + 1


def test_path_expands_axis_aligned_segments() -> None:
    """Corridor helpers move one cell at a time in either axis direction."""
    assert _path((6, 5), (6, 2)) == ((6, 5), (6, 4), (6, 3), (6, 2))
    assert _path((10, 2), (7, 2)) == ((10, 2), (9, 2), (8, 2), (7, 2))
    with pytest.raises(
        ValueError, match="^A corridor segment must follow a grid axis$"
    ):
        _path((0, 0), (1, 1))


def test_verify_edges_allows_the_left_grid_boundary() -> None:
    """Column 0 remains a legal open-edge coordinate."""
    maze = build_template(2, 0)
    boundary = edge_between((0, 3), (1, 3))
    _verify_edges(replace(maze, open_edges=maze.open_edges | {boundary}))


def test_verify_start_exits_uses_the_exact_error_message() -> None:
    """Start-exit failures keep a stable participant-facing message."""
    maze = build_template(2, 0)
    blocked = edge_between(START, CENTER_ENTRY)
    broken = replace(maze, open_edges=maze.open_edges - {blocked})
    with pytest.raises(
        ValueError,
        match="^The start must have exactly three exits: left, right, down$",
    ):
        _verify_start_exits(broken)


def test_verify_learned_route_rejects_a_revisit_that_still_ends_at_goal() -> None:
    """A detour that revisits a cell is invalid even when G remains last."""
    maze = build_template(2, 0)
    route = maze.learned_route
    index = 4
    revisited = (
        route[: index + 1] + (route[index - 1], route[index]) + route[index + 1 :]
    )
    broken = replace(maze, learned_route=revisited)
    with pytest.raises(
        ValueError,
        match="^The learned route must be a simple, open side route to goal$",
    ):
        _verify_learned_route(broken)


def test_build_template_rejects_invalid_parameters() -> None:
    """Template construction validates detour and variant bounds."""
    with pytest.raises(
        ValueError, match="^Use a detour of 1–3 cells and a variant of 0–3$"
    ):
        build_template(4, 0)
    with pytest.raises(
        ValueError, match="^Use a detour of 1–3 cells and a variant of 0–3$"
    ):
        build_template(2, 4)


def test_learned_side_reads_first_horizontal_move() -> None:
    """Scoring side follows the first move away from the center column."""
    # Templates train the right-side route; reflection flips scoring to left.
    original = build_template(2, 0)
    mirrored = original.reflected()
    assert _learned_side(original) == "right"
    assert _learned_side(mirrored) == "left"


def test_session_rng_rejects_negative_participant_index() -> None:
    """Each session phase gets an independent RNG keyed by participant index."""
    with pytest.raises(ValueError, match="^Participant index must be nonnegative$"):
        _session_rng(42, -1, "test")


def test_session_rng_streams_differ_by_phase() -> None:
    """Test and pilot phases must not share a random stream."""
    assert _session_rng(7, 0, "test").sample(range(20), 5) != _session_rng(
        7, 0, "pilot"
    ).sample(range(20), 5)


def test_initial_visible_edges_match_reflection() -> None:
    """The starting view must not reveal orientation."""
    maze = build_template(2, 1)
    visible = maze.initial_visible_edges()
    assert visible == maze.reflected().initial_visible_edges()
    # Openings that leave the fog stay visible from the near side.
    assert any(
        (first in INITIAL_VISIBLE_CELLS) != (second in INITIAL_VISIBLE_CELLS)
        for first, second in visible
    )


def test_grid_metadata_matches_maze_constants() -> None:
    """JSON grid block must expose the shared layout constants."""
    from maze import HEIGHT, WIDTH

    grid = grid_metadata()
    assert grid == {
        "width": WIDTH,
        "height": HEIGHT,
        "start": START,
        "goal": GOAL,
        "initial_visible_cells": sorted(INITIAL_VISIBLE_CELLS),
    }


def test_verified_savings_matches_learned_route_length() -> None:
    """Verifier returns shortcut savings consistent with route length."""
    maze = build_template(1, 0)
    savings = verify_maze(maze)
    shortest = len(maze.learned_route) - 1 - savings
    assert maze.distances_to_goal()[START] == shortest
    assert START in SIDE_EXITS or maze.learned_route[1] in SIDE_EXITS


def test_maze_reflected_swaps_open_edges_but_preserves_template_id() -> None:
    """Reflection swaps edges while keeping the template identifier stable."""
    maze = build_template(3, 2)
    mirror = maze.reflected()
    assert mirror.template_id == maze.template_id
    assert mirror.open_edges != maze.open_edges
    assert verify_maze(mirror) == verify_maze(maze)

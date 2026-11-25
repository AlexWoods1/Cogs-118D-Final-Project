"""Direct unit tests for maze geometry and verification helpers."""

import pytest

from maze import (
    CENTER_ENTRY,
    GOAL,
    SIDE_EXITS,
    START,
    Maze,
    build_template,
    edge_between,
    reflect_cell,
    verify_maze,
)
from maze_trials import _learned_side, _session_rng


def test_edge_between_uses_lexicographic_order() -> None:
    """Canonical edge pairs must be independent of endpoint order."""
    first, second = (1, 0), (0, 0)
    canonical = ((0, 0), (1, 0))
    assert edge_between(first, second) == edge_between(second, first) == canonical


def test_reflect_cell_fixes_the_center_column() -> None:
    """Mirror coordinates twice returns the original cell."""
    left = (5, 4)
    assert reflect_cell(reflect_cell(left)) == left
    assert reflect_cell(START) == START


def test_neighbors_and_can_move_follow_open_edges() -> None:
    """Movement queries consult only the stored open-edge set."""
    maze = build_template(2, 0)
    assert maze.can_move(START, CENTER_ENTRY)
    assert CENTER_ENTRY in maze.neighbors(START)
    assert maze.can_move(START, GOAL) is False


def test_distances_to_goal_honors_avoid() -> None:
    """Excluding the goal returns no reachable distances."""
    maze = build_template(2, 0)
    assert maze.distances_to_goal(avoid=GOAL) == {}


def test_build_template_rejects_invalid_parameters() -> None:
    """Template construction validates detour and variant bounds."""
    with pytest.raises(ValueError, match="detour"):
        build_template(4, 0)
    with pytest.raises(ValueError, match="variant"):
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
    with pytest.raises(ValueError, match="nonnegative"):
        _session_rng(42, -1, "test")


def test_initial_visible_edges_match_reflection() -> None:
    """The starting view must not reveal orientation."""
    maze = build_template(2, 1)
    assert maze.initial_visible_edges() == maze.reflected().initial_visible_edges()


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

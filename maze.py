from collections import deque
from dataclasses import dataclass
from itertools import pairwise

type Cell = tuple[int, int]
type Edge = tuple[Cell, Cell]

WIDTH = 13
HEIGHT = 9
START = (6, 2)
GOAL = (6, 7)
CENTER_ENTRY = (6, 3)
SIDE_EXITS = ((START[0] - 1, START[1]), (START[0] + 1, START[1]))
INITIAL_VISIBLE_CELLS = frozenset((x, y) for x in range(2, 11) for y in range(1, 5))
STEPS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def edge_between(first: Cell, second: Cell) -> Edge:
    """Return the canonical representation of an undirected edge."""
    # Movement in either direction must look up the same pair.
    return (first, second) if first < second else (second, first)


def reflect_cell(cell: Cell) -> Cell:
    """Mirror a cell across the central column."""
    x, y = cell
    # Reversing the zero-based column keeps the center fixed.
    return WIDTH - 1 - x, y


@dataclass(frozen=True)
class Maze:
    """A grid layout and the route metadata used to score it."""

    template_id: str
    open_edges: frozenset[Edge]
    learned_route: tuple[Cell, ...]
    later_junction: Cell

    def neighbors(self, cell: Cell) -> tuple[Cell, ...]:
        """Return cells reachable in one legal move."""
        x, y = cell
        # Only stored open edges permit movement, including at the grid boundary.
        adjacent = ((x + dx, y + dy) for dx, dy in STEPS)
        return tuple(other for other in adjacent if self.can_move(cell, other))

    def can_move(self, first: Cell, second: Cell) -> bool:
        """Check whether a move uses an open edge."""
        # Canonicalize the pair because a move can traverse either direction.
        return edge_between(first, second) in self.open_edges

    def reflected(self) -> "Maze":
        """Mirror the geometry and scoring coordinates together."""
        # The source template ID stays stable across orientations.
        return Maze(
            self.template_id,
            frozenset(
                edge_between(reflect_cell(first), reflect_cell(second))
                for first, second in self.open_edges
            ),
            tuple(map(reflect_cell, self.learned_route)),
            reflect_cell(self.later_junction),
        )

    def initial_visible_edges(self) -> frozenset[Edge]:
        """Return openings incident to the starting field of view."""
        # An edge leaving the visible region is visible from its near side.
        return frozenset(
            (first, second)
            for first, second in self.open_edges
            if first in INITIAL_VISIBLE_CELLS or second in INITIAL_VISIBLE_CELLS
        )

    def distances_to_goal(self, *, avoid: Cell | None = None) -> dict[Cell, int]:
        """Compute minimum moves to the goal while excluding an optional cell."""
        if avoid == GOAL:
            return {}
        # Search outwards from the goal because every open edge is bidirectional.
        frontier = deque([GOAL])
        distances = {GOAL: 0}
        # Bound expansions so a broken revisit check cannot loop forever.
        max_expansions = WIDTH * HEIGHT
        expansions = 0
        while frontier:
            expansions += 1
            if expansions > max_expansions:
                raise RuntimeError("Distance search exceeded the grid cell bound")
            cell = frontier.popleft()
            for neighbor in self.neighbors(cell):
                if neighbor == avoid:
                    continue
                if neighbor in distances:
                    continue
                distances[neighbor] = distances[cell] + 1
                frontier.append(neighbor)
        return distances


def _verify_edges(maze: Maze) -> None:
    """Check that every open edge is a valid grid boundary."""
    for first, second in maze.open_edges:
        bounded = all(0 <= x < WIDTH and 0 <= y < HEIGHT for x, y in (first, second))
        # Unit Manhattan distance excludes diagonal moves and self-loops.
        adjacent = abs(first[0] - second[0]) + abs(first[1] - second[1]) == 1
        if not (bounded and adjacent and first < second):
            raise ValueError(f"Invalid open edge {first, second} in {maze.template_id}")


def _verify_start_exits(maze: Maze) -> None:
    """Check that the first decision offers the two turns and the center exit."""
    # Both side routes start beside S, and the shortcut starts below it.
    if set(maze.neighbors(START)) != {*SIDE_EXITS, CENTER_ENTRY}:
        raise ValueError("The start must have exactly three exits: left, right, down")


def _verify_learned_route(maze: Maze) -> None:
    """Check that the learned side route reaches the goal without revisits."""
    route = maze.learned_route
    # The learned first move must be horizontal, even when the center is shorter.
    if (
        len(route) < 3
        or route[0] != START
        or route[1] not in SIDE_EXITS
        or route[-1] != GOAL
        or len(set(route)) != len(route)
        or not all(maze.can_move(first, second) for first, second in pairwise(route))
    ):
        raise ValueError("The learned route must be a simple, open side route to goal")


def _verify_later_junction(maze: Maze) -> None:
    """Check that the learned junction has an equally short alternative."""
    route = maze.learned_route
    if maze.later_junction not in route[2:-1]:
        raise ValueError("The later junction must occur on the learned route after S")
    junction_index = route.index(maze.later_junction)
    previous, continuation = route[junction_index - 1], route[junction_index + 1]
    alternatives = set(maze.neighbors(maze.later_junction)) - {previous, continuation}
    # Exclude return trips through the junction when comparing the alternatives.
    forward_distances = maze.distances_to_goal(avoid=maze.later_junction)
    if not any(
        forward_distances.get(cell) == forward_distances[continuation]
        for cell in alternatives
    ):
        raise ValueError("The later junction must offer an equally short alternative")


def _verified_savings(maze: Maze) -> int:
    """Return the move savings after checking the center exit is shortest."""
    distances = maze.distances_to_goal()
    shortest = distances[START]
    # The route includes both the start and goal, so moves are one fewer than cells.
    savings = len(maze.learned_route) - 1 - shortest
    if savings <= 0 or 1 + distances[CENTER_ENTRY] != shortest:
        raise ValueError("The center entry must provide a shorter route to the goal")
    return savings


def verify_maze(maze: Maze) -> int:
    """Validate the maze against the pilot design and return shortcut savings."""
    _verify_edges(maze)
    _verify_start_exits(maze)
    _verify_learned_route(maze)
    _verify_later_junction(maze)
    # Starting walls must give the same information in both orientations.
    if maze.initial_visible_edges() != maze.reflected().initial_visible_edges():
        raise ValueError("Visible walls reveal the reflection at the first decision")
    return _verified_savings(maze)


def _path(*corners: Cell) -> tuple[Cell, ...]:
    """Expand axis-aligned route waypoints into adjacent cells."""
    cells = [corners[0]]
    for (x, y), (next_x, next_y) in pairwise(corners):
        dx = (next_x > x) - (next_x < x)
        dy = (next_y > y) - (next_y < y)
        if dx and dy:
            raise ValueError("A corridor segment must follow a grid axis")
        # Skip the segment's first cell because the previous segment added it.
        for step in range(1, abs(next_x - x) + abs(next_y - y) + 1):
            cells.append((x + dx * step, y + dy * step))
    return tuple(cells)


def build_template(detour: int, variant: int) -> Maze:
    """Build one layout for each detour length and hidden wall variant."""
    if detour not in (1, 2, 3) or variant not in range(4):
        raise ValueError("Use a detour of 1–3 cells and a variant of 0–3")

    # Vary the hidden turn while keeping the center entry and side routes fixed.
    side, turn_row = ((-1, 5), (1, 5), (1, 6), (-1, 6))[variant]
    detour_column = START[0] + side * detour
    junction = (10, 6)
    learned = _path(START, (10, 2), junction, (9, 6), (9, 7), GOAL)
    alternate = _path(junction, (10, 7), (9, 7))
    center = _path(
        START, (6, turn_row), (detour_column, turn_row), (detour_column, GOAL[1]), GOAL
    )
    paths = (
        learned,
        tuple(map(reflect_cell, learned)),
        alternate,
        tuple(map(reflect_cell, alternate)),
        center,
    )
    # Distinguish the mirrored detours with symmetric alcoves beyond the first view.
    if variant % 2:
        alcove = ((2, 5), (1, 5))
        paths += (alcove, tuple(map(reflect_cell, alcove)))
    open_edges = frozenset(
        edge_between(first, second)
        for path in paths
        for first, second in pairwise(path)
    )
    return Maze(f"detour-{detour}-variant-{variant}", open_edges, learned, junction)

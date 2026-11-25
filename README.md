# Cogs-118D-Final-Project

Seeded trial generation for the reflected-maze pilot. Each cell is a position, and
movement between adjacent cells requires an open edge.

```sh
uv sync --locked --dev
uv run python -m maze_trials --seed 42 --participant-index 0
uv run python -m maze_trials --seed 42 --participant-index 0 --phase pilot
```

The default command emits JSON for four test blocks. Each block crosses landmark
reliability and a timed or untimed first decision, and contains one trial at each
of the fixture's three savings levels (2, 4, and 6 moves). Use consecutive,
zero-based participant indices to balance block order and layout assignments
across groups of 16. The pilot command emits untimed symbol-only, aligned-beacon,
and conflicting-beacon probes, with both reflections represented for each cue
type. The sample trial counts are for generator verification. Calibrate the
deadline and choose the study trial count during pilot work.

Coordinates are zero-based pairs `[column, row]` measured from the top left. Each
trial's `open_edges` contains unordered pairs of adjacent cells in participant
coordinates, after reflection. All other boundaries are walls. The initial view
includes edges incident to `initial_visible_cells`. The beacon is drawn on its
designated boundary without opening it. `learned_route`, `learned_side`,
`later_junction`, and `shortcut_savings` are scoring metadata.

## Maze preview

Generate and open the local preview to compare the participant's starting view
with the full layout. The full view overlays the learned route and a shortest
shortcut through the center exit, and marks the later junction.

```sh
uv run python -m maze_viz --seed 42 --participant-index 0
```

Open `build/maze-preview.html` in a browser. The phase and trial selectors cover
all test blocks and pilot probes for the chosen seed and participant index. The
preview works offline. Use `--output` to save it to a different path.

## Playable pilot

Export an offline participant session with edge-checked movement, expanding fog,
cue display, training guidance, timed first-move deadlines, and decision logging.
Scoring uses `learned_side`, `learned_route`, and `later_junction` from the
generator.

```sh
uv run python -m pilot_play --seed 42 --participant-index 0 --phase pilot
uv run python -m pilot_play --seed 42 --participant-index 0 --phase test --deadline-ms 800
uv run python -m pilot_play --seed 42 --participant-index 0 --phase pilot --max-trials 8
```

Open `build/maze-pilot.html` in a browser. Arrow keys or WASD move the agent.
Pilot sessions train both reflections with full then fading guidance before the
cue probes. **Download JSON** keeps trial summaries plus every move attempt;
**Download CSV** writes one row per attempted move (legal and blocked), including
timeouts. After all trials, the page shows a condition report and a calibrated
deadline. Analyze a saved log from the CLI:

```sh
uv run python -m pilot_play --analyze path/to/maze-pilot-log.json
```

Use `--max-trials` to cap the exported schedule while calibrating.

## Testing

```sh
uv run black --check .
uv run pytest
```

Run mutation tests locally. On Windows, use the spawn-based shim (set `PYTHONUTF8=1`
if mutant generation hits a console encoding error):

```sh
uv run --locked --group mutation python mutmut_windows.py run
uv run --locked --group mutation python mutmut_windows.py results
```

On Linux or macOS you can use `mutmut run` directly.

The [Cursor handoff](HANDOFF.md) records the study design and the remaining
playable pilot milestones.

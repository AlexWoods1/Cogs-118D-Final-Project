# Cogs-118D-Final-Project

Seeded trial generation for the reflected-maze pilot. Each cell is a position, and
movement between adjacent cells requires an open edge.

```sh
uv sync --locked --dev
uv run python -m maze_pilot.maze_trials --seed 42 --participant-index 0
uv run python -m maze_pilot.maze_trials --seed 42 --participant-index 0 --phase pilot
```

Source lives under [`maze_pilot/`](maze_pilot/).

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
uv run python -m maze_pilot.maze_viz --seed 42 --participant-index 0
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
uv run python -m maze_pilot.pilot_play --seed 42 --participant-index 0 --phase pilot
uv run python -m maze_pilot.pilot_play --seed 42 --participant-index 0 --phase test --deadline-ms 800
uv run python -m maze_pilot.pilot_play --seed 42 --participant-index 0 --phase pilot --max-trials 8
```

Open `build/maze-pilot.html` in a browser. Enter **Participant TSN** on the start
form; any non-negative integer works. The schedule uses `TSN % N` over the embedded
counterbalance set (default export embeds slots `0`–`15`). Arrow keys or WASD move
the agent.
Pilot sessions train both reflections with full then fading guidance before the
cue probes. **Download JSON** keeps trial summaries plus every move attempt;
**Download CSV** writes one row per attempted move (legal and blocked), including
timeouts. After all trials, the page shows a condition report and a calibrated
deadline. Analyze a saved log from the CLI:

```sh
uv run python -m maze_pilot.pilot_play --analyze path/to/maze-pilot-log.json
```

Use `--max-trials` to cap the exported schedule while calibrating.

## Deploy (Vercel + Neon)

Live app: [https://cogs-118d-maze-pilot.vercel.app](https://cogs-118d-maze-pilot.vercel.app)

After each completed trial the browser POSTs the session log to `/api/sessions`,
which upserts into Neon Postgres (`pilot_sessions`) keyed by Participant TSN
(`participant_index`). A new session with an existing TSN replaces the prior
row. Downloads remain available as a backup. Rebuild the static export before
redeploying:

```sh
npm install
npm run build
vercel --prod
```

List saved sessions (requires `SESSIONS_ADMIN_TOKEN`):

```sh
curl -H "Authorization: Bearer $SESSIONS_ADMIN_TOKEN" \
  https://cogs-118d-maze-pilot.vercel.app/api/sessions
```

`POST /api/sessions` accepts same-origin browser saves only (CORS allowlist),
validates TSN/phase/size, and stores a whitelisted payload. Set
`SESSIONS_ALLOWED_ORIGIN` if the production host differs from the Vercel default.
Keep `SESSIONS_ADMIN_TOKEN` long and random; never commit `.env.local`.

## Session data and analysis

Export Neon rows to local JSON (gitignored under `Data/`):

```sh
node scripts/export-sessions.mjs          # completed sessions
node scripts/export-sessions.mjs --all    # every row
```

Score control information, plot paths, and build the cohort summary:

```sh
uv run --with matplotlib python Analysis/computational_complexity.py --log Data/maze-pilot-log-42-<TSN>.json
uv run --with matplotlib python Data/_plot_trials.py --log Data/maze-pilot-log-42-<TSN>.json
uv run --with matplotlib python Analysis/pilot_cohort.py
```

Write-up and figures: [`Results/INITIAL_RESULTS.md`](Results/INITIAL_RESULTS.md).
Cohort table: `Results/pilot-cohort-trials.csv`.

## Testing

```sh
uv run black --check .
uv run pytest
```

Run mutation tests locally. On Windows, use the spawn-based shim (set `PYTHONUTF8=1`
if mutant generation hits a console encoding error):

```sh
uv run --locked --group mutation python tools/mutmut_windows.py run
uv run --locked --group mutation python tools/mutmut_windows.py results
```

On Linux or macOS you can use `mutmut run` directly.

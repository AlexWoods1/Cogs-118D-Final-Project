# Reflected maze pilot handoff for Cursor

Open this project folder in Cursor and use this file as the project context. The maze generator, verifier, and offline visual preview are ready. The next implementation milestone is a playable pilot that uses the generated schedules, records participant decisions, and supports deadline calibration.

## Study design

The study asks whether time pressure increases learned-route choices more when a beacon reliably points toward the learned route. The four test blocks cross informative versus uninformative beacon placement with a timed versus untimed first decision. The orientation symbol remains available in every condition. In an informative block, the beacon marks the learned side. In an uninformative block, its left or right position is drawn independently of the reflection.

- The maze is a 13 by 9 grid. Coordinates are zero-based `[column, row]` from the top left. Left, right, and down are legal at S. S and G lie on the reflection axis.
- `open_edges` gives the legal moves. An opening is visible at the start if at least one endpoint is in `initial_visible_cells`. The initial walls and fog are mirror-symmetric. The beacon is drawn on a wall boundary and has no effect on movement.
- Each test trial draws its reflection independently. The sample schedule presents three trials per block, with shortcut savings of 2, 4, and 6 moves. Consecutive indices in groups of 16 counterbalance block order and layout assignment.
- The 12 untimed pilot probes cover symbol-only, aligned-beacon, and conflicting-beacon trials. Each type has two trials in each reflection. A circle indicates the learned left turn and a diamond indicates the learned right turn.
- The learned route stays traversable. Its later junction has an equally short alternative so following the trained continuation can be measured separately from making the first learned turn.

## Project files

| File | Role |
| --- | --- |
| [`maze.py`](maze.py) | Defines the grid, edge legality, reflection, distance calculation, and layout verification. |
| [`maze_trials.py`](maze_trials.py) | Generates seeded test blocks and pilot probes. Its CLI exports participant-space geometry and scoring metadata as JSON. |
| [`maze_viz.py`](maze_viz.py) | Generates an offline HTML preview for both schedules. |
| [`maze_viz.html`](maze_viz.html) and [`maze_viz.js`](maze_viz.js) | Define the preview layout and render the starting view and full route overlays. |
| [`tests/`](tests/) | Covers geometry, verification, schedule balance, both JSON export phases, and the offline preview payload. |
| [`pyproject.toml`](pyproject.toml) and [`uv.lock`](uv.lock) | Define Python 3.14, pytest, Black, and the optional mutmut dependency group. |

This local project was extracted from the prior chat’s ZIP. It has no `.git` metadata. If the goal is to work on a Git branch, apply these files to a Git checkout first.

## Run and verify

From the project folder, run the following commands and open `build/maze-preview.html` in a browser. The preview is for inspecting fixtures. Its phase and trial selectors include condition labels and the full panel includes scoring overlays.

```sh
uv sync --locked --dev
uv run --locked python -m maze_trials --seed 42 --participant-index 0
uv run --locked python -m maze_trials --seed 42 --participant-index 0 --phase pilot
uv run --locked python -m maze_viz --seed 42 --participant-index 0
uv run --locked pytest -q
uv run --locked black --check .
```

Run mutmut on Linux, macOS, or Ubuntu under WSL. In a checkout shared between Windows and WSL, set `UV_PROJECT_ENVIRONMENT=build/.venv-wsl` in the WSL shell so the two platforms use separate virtual environments.

```sh
uv run --locked --group mutation mutmut run
uv run --locked --group mutation mutmut results
```

The final checks passed 22 pytest tests and Black. Chrome verified the selectors
and the fog boundary at narrow and desktop widths. Mutmut on Ubuntu WSL evaluated
814 Python mutants. The tests killed 704, 107 survived, and 3 timed out.

Keep functions focused on one purpose. Add Python type hints and docstrings, JavaScript JSDoc, and comments that explain maze rules or implementation choices. Reuse the generator and its scoring fields when adding participant-facing code.

## Playable pilot milestones

1. **Done:** [`pilot_play.py`](pilot_play.py) / [`pilot_play.html`](pilot_play.html) / [`pilot_play.js`](pilot_play.js) — edge-checked movement, expanding fog, seeded schedule, cues, scoring via `learned_side` / `learned_route` / `later_junction`.
2. **Done:** Pilot export prepends training (both reflections, full then fade guidance) before cue probes; `summarize_first_choices` compares RTs and first decisions by cue kind.
3. **Done (export + client):** Timed blocks take `--deadline-ms`; deadline starts when cues appear and stops on the first legal move; logs learned / shortcut / other / timeout + RT.
4. **Done:** Later-junction continuation logged on first visit with `beaconVisibleAtJunction`. `calibrate_deadline_ms` for post-probe calibration. `--max-trials` caps exported trial count.
5. **Done (helpers):** `learned_choice_delta` and `summarize_first_choices` aggregate choice types / RTs by cue or landmark; use downloaded logs for condition reports.

```sh
uv run python -m pilot_play --seed 42 --participant-index 0 --phase pilot
```

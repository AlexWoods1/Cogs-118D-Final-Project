# Reflected maze — trial design

Hand this to anyone running or coding the pilot. It covers the study question, maze rules, schedules, cues, and scoring — not repo setup.

## Study question

Does **time pressure** increase **learned-route** first choices more when a **beacon** reliably points to the learned side than when the beacon is random?

Planned test conditions cross two factors:

| Factor | Levels |
| --- | --- |
| Landmark reliability | **Informative** (beacon on learned side) vs **uninformative** (beacon left/right independent of learning) |
| First-move pressure | **Timed** vs **untimed** (design factor in the generator) |

The **orientation symbol** is available in every condition.

> **Playable export note:** the offline player currently times **every** first move (default **800 ms**, override with `--deadline-ms`). Generator JSON still labels which test *blocks* were designed as timed vs untimed for analysis.

## Maze geometry

- Grid: **13 × 9** cells. Coordinates are zero-based `[column, row]` from the **top left**.
- **S** (start) = `[6, 2]`, **G** (goal) = `[6, 7]`. Both sit on the vertical reflection axis.
- At S, legal first moves are **left**, **right**, and **down** (center shortcut entry).
- Movement uses undirected **open edges** only. The beacon is drawn on a **wall** boundary and never opens a corridor.
- Initial fog / visible cells are mirror-symmetric so the starting view does not reveal reflection.
- An opening is visible at start if at least one endpoint is in `initial_visible_cells`.

## What participants learn

- Each layout has a **learned side route** from S to G (longer than the center shortcut).
- **Teal circle** (bullseye) = learned first turn **left**; **coral diamond** = learned first turn **right**.
- The **beacon** is an amber star on a wall boundary (never opens a corridor). Reference art lives in [`media/`](media/).
- Training shows the learned path (full guidance, then fading).
- A **later junction** on the learned route has an equally short alternative, so you can score “kept going on the trained continuation” separately from “took the learned first turn.”

## Schedules

Numeric schedule knobs (deadline, trial counts, detours, calibration) live in
[`maze_pilot/trial_config.py`](maze_pilot/trial_config.py). Edit that file to
change pilot/test lengths or the default first-move deadline.

### Seed and participant index

- Schedules are deterministic given `--seed` and zero-based `--participant-index`.
- Indices in groups of **16** counterbalance **block order** and **layout variant** assignment.

### Pilot phase (`--phase pilot`)

Used to train and probe cues (and to calibrate deadlines from untimed RTs when you collect them).

1. **Training (4 trials)**  
   Both reflections × full guidance, then both reflections × fading guidance.
2. **Cue probes (24 trials)**  
   Three kinds × balanced reflections:
   - **symbol-only** — no beacon  
   - **aligned** — beacon on the learned side  
   - **conflicting** — beacon on the opposite side  

   Four trials per kind × reflection. Probe order is shuffled per session.

### Test phase (`--phase test`)

Four blocks (one per landmark × timing design cell). Each block has **6 trials**, two at each shortcut-savings level:

| Detour length | Shortcut savings (moves) |
| ---: | ---: |
| 1 | 6 |
| 2 | 4 |
| 3 | 2 |

Each trial draws reflection independently. Informative blocks put the beacon on the learned side; uninformative blocks sample beacon side at random.

## Scoring fields (use these; do not reinvent)

| Field | Meaning |
| --- | --- |
| `learned_side` | `"left"` or `"right"` — first learned turn in participant coordinates |
| `orientation_symbol` | `"circle"` or `"diamond"` |
| `beacon_side` / `beacon_edge` | Cue placement (or null) |
| `learned_route` | Cell sequence for the trained path |
| `later_junction` | Cell where continuation vs alternate is scored |
| `shortcut_savings` | Learned-route length minus shortest path length |
| First leave-S choice | `learned` · `shortcut` (center) · `other` · `timeout` |
| Later continuation | `learned` · `alternate` · `none` (first departure from the junction along the learned route) |

Deadline (when timed): starts when cues appear; stops on the **first legal** move.

## What to run (teammates)

```sh
# Inspect JSON schedules
uv run python -m maze_pilot.maze_trials --seed 42 --participant-index 0
uv run python -m maze_pilot.maze_trials --seed 42 --participant-index 0 --phase pilot

# Offline layout preview
uv run python -m maze_pilot.maze_viz --seed 42 --participant-index 0
# → open build/maze-preview.html

# Playable session (all first moves timed by default)
uv run python -m maze_pilot.pilot_play --seed 42 --participant-index 0 --phase pilot
uv run python -m maze_pilot.pilot_play --seed 42 --participant-index 0 --phase test --deadline-ms 800
# → open build/maze-pilot.html

# Analyze a downloaded play log
uv run python -m maze_pilot.pilot_play --analyze path/to/maze-pilot-log.json
```

Controls in the player: **arrow keys / WASD**, then **Next trial**. Download **JSON** (trial summaries + moves) or **CSV** (one row per attempted move).

## Design invariants (quick check)

- S and G fixed under left–right reflection.
- Starting fog does not reveal orientation.
- Learned route stays open; center path is strictly shorter.
- Later junction offers an equally short non-trained continuation.
- Informative beacon ↔ learned side; uninformative beacon ⊥ learned side (independent draw).

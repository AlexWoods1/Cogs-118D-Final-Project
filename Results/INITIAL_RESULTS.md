# Initial pilot results

**Session:** seed `42`, participant `0`, test phase  
**Date generated from log:** `Data/maze-pilot-log-42-0 (1).json`  
**N trials:** 12 (all reached goal)

This note summarizes one self-pilot of the reflected-maze task. It is descriptive only: one participant, no inferential tests.

## Study question (brief)

Does time pressure increase learned-route first choices more when the beacon is informative (aligned with the learned side) than when it is uninformative?

## Session summary

| Measure | Value |
| --- | --- |
| First choices | shortcut 9 · learned 2 · other 1 |
| Mean / median first-choice RT | 455 ms / 407 ms |
| Mean / median path steps | 13.3 / 15 |
| Mean / median control information | 13.9 bits / 12.3 bits |

### First choice by condition

| Landmark | Timing | Learned / N | Mean first-choice RT |
| --- | ---: | ---: | ---: |
| Informative | Untimed | 1 / 3 | 563 ms |
| Informative | Timed | 1 / 3 | 354 ms |
| Uninformative | Untimed | 0 / 3 | 438 ms |
| Uninformative | Timed | 0 / 3 | 464 ms |

Timed blocks were faster at the first move in the informative half of the session, but learned-route rate did not increase under time pressure in this single pilot (1/3 in both informative cells; 0/3 in both uninformative cells). Shortcut dominated overall.

## Path trajectories

Figure 1 shows the taken path on each trial’s maze geometry. Blue = shortcut first choice, green = learned, red = other. Start is the filled marker; goal is the star.

![Pilot session paths for seed 42 participant 0](trial-paths-42-0.png)

*Figure 1. Paths for all 12 test trials.*

## Computational complexity (control information)

Following Lancia et al. (2023), **computational complexity** here is empirical **control information**: how many bits a path costs relative to a default policy that prefers the trained learned route.

For a deterministic logged path:

\[
\hat{I} = \sum_t -\log_2 \rho(a_t \mid s_t)
\]

where \(\rho\) puts most mass on the next learned-route step when the agent is on that route (else uniform over legal moves). Code: [`analysis/computational_complexity.py`](../analysis/computational_complexity.py). Per-trial table: [`computational-complexity-42-0.csv`](computational-complexity-42-0.csv).

![Control information by trial and timed vs untimed](computational-complexity-42-0.png)

*Figure 2. Left: control information (bits) by trial, colored by first choice. Right: timed vs untimed distributions.*

### Per-trial values

| Trial | Condition | First choice | RT (ms) | Steps | Control info (bits) | Default-follow rate |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | Informative · untimed | shortcut | 783 | 7 | 10.91 | 0.14 |
| 2 | Informative · untimed | shortcut | 533 | 15 | 12.32 | 0.87 |
| 3 | Informative · untimed | learned | 373 | 13 | 1.98 | 1.00 |
| 4 | Informative · timed | shortcut | 416 | 15 | 12.32 | 0.87 |
| 5 | Informative · timed | learned | 307 | 15 | 11.32 | 0.87 |
| 6 | Informative · timed | other | 340 | 13 | 18.08 | 0.31 |
| 7 | Uninformative · timed | shortcut | 398 | 7 | 10.91 | 0.14 |
| 8 | Uninformative · timed | shortcut | 314 | 9 | 12.91 | 0.22 |
| 9 | Uninformative · timed | shortcut | 681 | 17 | 22.08 | 0.41 |
| 10 | Uninformative · untimed | shortcut | 492 | 15 | 12.32 | 0.87 |
| 11 | Uninformative · untimed | shortcut | 324 | 19 | 29.74 | 0.37 |
| 12 | Uninformative · untimed | shortcut | 499 | 15 | 12.32 | 0.87 |

### Pattern notes

- Staying on the learned route keeps control information low (trial 3 ≈ 2 bits).
- Shortcut and exploratory paths cost more bits; the highest costs are trials with backtracking / wandering (9 and 11).
- Mean control information was similar for timed (14.6 bits) and untimed (13.3 bits) in this session; the interesting structure is by path type, not timing alone.

## What is not estimated yet

**Policy complexity** \(I(S;A)\) (Lai & Gershman, 2024) — mutual information between states and actions — needs many repeated visits per state within a condition. Twelve trials are too sparse for a stable Hutter / Dirichlet MI estimate, so that metric is omitted from these initial results.

## Reproduce

```sh
uv run --with matplotlib python analysis/computational_complexity.py
```

Inputs: `Data/maze-pilot-log-42-0 (1).json` (and matching move CSV).  
Outputs written under `results/`.

## References

- Lancia, G. L., Eluchans, M., D’Alessandro, M., Spiers, H. J., & Pezzulo, G. (2023). Humans account for cognitive costs when finding shortcuts: An information-theoretic analysis of navigation. *PLOS Computational Biology*.
- Lai, L., & Gershman, S. J. (2024). Human decision making balances reward maximization and policy compression. *PLOS Computational Biology*.

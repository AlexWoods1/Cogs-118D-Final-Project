"""Shim: prefer `python -m maze_pilot.maze_trials`."""

from maze_pilot.maze_trials import *  # noqa: F403
from maze_pilot.maze_trials import main

if __name__ == "__main__":
    main()

"""Shim: prefer `python -m maze_pilot.maze_viz`."""

from maze_pilot.maze_viz import *  # noqa: F403
from maze_pilot.maze_viz import main

if __name__ == "__main__":
    main()

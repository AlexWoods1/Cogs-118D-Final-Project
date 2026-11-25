"""Shim: prefer `python -m maze_pilot.pilot_play`."""

from maze_pilot.pilot_play import *  # noqa: F403
from maze_pilot.pilot_play import main

if __name__ == "__main__":
    main()

"""Shared argparse helpers for seeded participant session commands."""

from __future__ import annotations

import argparse
from pathlib import Path


def add_seed_participant_args(
    parser: argparse.ArgumentParser,
    *,
    seed_required: bool = False,
    seed_default: int = 42,
) -> None:
    """Add ``--seed`` and ``--participant-index`` with shared validation later."""
    if seed_required:
        parser.add_argument("--seed", type=int, required=True)
    else:
        parser.add_argument("--seed", type=int, default=seed_default)
    parser.add_argument("--participant-index", type=int, default=0)


def add_phase_arg(
    parser: argparse.ArgumentParser,
    *,
    default: str = "test",
) -> None:
    """Add the test/pilot phase selector."""
    parser.add_argument("--phase", choices=("test", "pilot"), default=default)


def add_output_arg(parser: argparse.ArgumentParser, *, default: Path) -> None:
    """Add the HTML or artifact output path."""
    parser.add_argument("--output", type=Path, default=default)


def reject_negative_participant_index(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Surface the nonnegative participant-index rule as an argparse error."""
    if args.participant_index < 0:
        parser.error("--participant-index must be nonnegative")

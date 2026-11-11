"""Fixtures shared across test files."""

import dataclasses

import pytest

from fogline import run
from fogline.config import Config

TOWN_RUN_TICKS = 200


@pytest.fixture(scope="session")
def town_run_dir(tmp_path_factory):
    """Seed 1 supplied at 50,000 with events off (ADR 0004), written as a run folder.

    Returns (folder, final state, summary). test_runs checks the towns from the summary and
    test_viewer reads the same snapshots, so CI plays this world once."""
    folder = tmp_path_factory.mktemp("runs") / "town-run"
    config = dataclasses.replace(Config(), events_enabled=False, supply_floor=50_000)
    state, summary = run.play(config, 1, TOWN_RUN_TICKS, out=folder)
    return folder, state, summary


@pytest.fixture(scope="session")
def town_run(town_run_dir):
    return town_run_dir[1], town_run_dir[2]

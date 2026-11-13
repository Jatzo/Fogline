"""Fixtures shared across test files."""

import dataclasses
import subprocess

import pytest

from fogline import run
from fogline.config import Config

TOWN_RUN_TICKS = 200
REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch):
    """No test may start `claude`: a live call spends the operator's plan usage (CLAUDE.md).
    A test that fakes the subprocess sets its own stand-in after this one, which wins."""
    def guarded(argv, *args, **kwargs):
        if argv and "claude" in str(argv[0]).lower():
            pytest.fail(f"a test tried to start a live call: {argv[0]}")
        return REAL_RUN(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", guarded)


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

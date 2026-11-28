import pytest

from tsppredictor.calendar import TSPCalendar
from tsppredictor.data.snapshot import load_snapshot


@pytest.fixture(scope="session")
def snap():
    return load_snapshot()


@pytest.fixture(scope="session")
def prices(snap):
    return snap.daily[["G", "F", "C", "S", "I"]].copy()


@pytest.fixture(scope="session")
def tsp_calendar(snap):
    return TSPCalendar(snap.daily.index)



@pytest.fixture(scope="session")
def built():
    """One real build shared by every test module that needs dist/."""
    from tsppredictor.build import run_build

    return run_build()

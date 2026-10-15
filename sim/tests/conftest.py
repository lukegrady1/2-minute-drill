import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sim.data import load
from sim.engine import Ctx, Engine


@pytest.fixture(scope="session")
def data():
    return load()


@pytest.fixture
def engine(data):
    return Engine(data, Ctx())


@pytest.fixture
def playoff_engine(data):
    return Engine(data, Ctx(playoff=True))

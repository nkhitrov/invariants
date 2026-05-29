from collections.abc import Iterator

import pytest

from invariants.mappers import StateMapper


@pytest.fixture(autouse=True)
def fx_reset_registry() -> Iterator[None]:
    StateMapper.clear_registry()
    yield
    StateMapper.clear_registry()

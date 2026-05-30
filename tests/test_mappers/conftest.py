from collections.abc import Iterator

import pytest

from invariants.mappers import Mapper


@pytest.fixture(autouse=True)
def fx_reset_registry() -> Iterator[None]:
    Mapper.clear_registry()
    yield
    Mapper.clear_registry()

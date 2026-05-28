from collections.abc import Iterator

import pytest

from invariants.mappers import reset_mapper_registry


@pytest.fixture(autouse=True)
def fx_reset_registry() -> Iterator[None]:
    reset_mapper_registry()
    yield
    reset_mapper_registry()


import pytest

from polyfactory.factories.base import BaseFactory

from invariants.factories import StateFactory
from invariants.factories.sqlalchemy import SQLAlchemyStateFactory
from invariants.state import State
from tests.support.orm import Base

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import Session


@pytest.fixture()
def engine() -> Engine:
    return create_engine("sqlite:///:memory:")


@pytest.fixture(autouse=True)
def fx_drop_create_meta(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    yield


# TODO make interface for resetting factories mapping
@pytest.fixture(autouse=True)
def session(engine: Engine) -> Iterator[Session]:
    BaseFactory._factory_type_mapping = {}

    session = Session(bind=engine)
    SQLAlchemyStateFactory.__session__ = session
    yield session
    session.close()

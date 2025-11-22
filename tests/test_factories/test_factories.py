from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from dirty_equals import IsPositiveInt
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from polyfactory import ConfigurationException
from invariants.factories import StateFactory
from invariants.factories.sqlalchemy import SQLAlchemyStateFactory
from tests.support.orm import Base
from tests.support.states import LoanState, ActiveLoan, ActiveDebt, ClosedLoan, ClosedDebt


class TestStateFactory:
    def test_factory_validation(self) -> None:
        with pytest.raises(TypeError):
            class InvalidFactory(StateFactory[LoanState]): ...

    def test_factory_build(self) -> None:
        class ActiveLoanFactory(StateFactory[ActiveLoan]): ...

        loan = ActiveLoanFactory.build()
        assert isinstance(loan, ActiveLoan)
        assert loan.status == "active"
        assert isinstance(loan.id, int)
        assert isinstance(loan.postponement_date, datetime)


class TestSqlalchemyStateFactoryValidation:
    def test_abstract_sql_model_raises(self) -> None:
        with pytest.raises(ConfigurationException, match="abstract model"):
            class BadFactory(SQLAlchemyStateFactory[ActiveLoan, Base]): ...


class TestSqlalchemyStateFactory:
    class LoanORM(Base):
        __tablename__ = "loans_state_test"
        id = Column(Integer, primary_key=True)
        status: Mapped[str]
        postponement_date: Mapped[datetime]

    class LoanOrmFactory(SQLAlchemyStateFactory[ActiveLoan, LoanORM]): ...

    def test_build_one_instance(self) -> None:
        loan = self.LoanOrmFactory.build()
        self.assert_built_loan_orm(loan)

    def test_create_sync(self) -> None:
        loan = self.LoanOrmFactory.create_sync()
        self.assert_loan_orm(loan)

    def test_create_sync_batch(self) -> None:
        batch_result = self.LoanOrmFactory.create_batch_sync(size=2)
        assert len(batch_result) == 2
        for loan in batch_result:
            self.assert_loan_orm(loan)

    def assert_built_loan_orm(self, loan: LoanORM) -> None:
        assert isinstance(loan, self.LoanORM)
        assert loan.id == IsPositiveInt()
        assert loan.status == "active"
        assert isinstance(loan.postponement_date, datetime)
        assert not sa_inspect(loan).persistent

    def assert_loan_orm(self, loan: LoanORM) -> None:
        assert isinstance(loan, self.LoanORM)
        assert loan.id == IsPositiveInt()
        assert loan.status == "active"
        assert isinstance(loan.postponement_date, datetime)
        assert sa_inspect(loan).persistent


class _RelationLoanORM(Base):
    __tablename__ = "loans_factory_test"
    id = Column(Integer, primary_key=True)
    status: Mapped[str]
    amount: Mapped[Decimal]
    postponement_date: Mapped[datetime]
    debt_id: Mapped[int] = mapped_column(ForeignKey("debts_factory_test.id"))


class _RelationDebtORM(Base):
    __tablename__ = "debts_factory_test"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]
    postponement_date: Mapped[datetime]
    amount: Mapped[Decimal]

    loans: Mapped[list[_RelationLoanORM]] = relationship()


class TestSqlFactoryRelations:

    def test_build_one_instance(self) -> None:
        class ActiveLoanFactory(SQLAlchemyStateFactory[ActiveLoan, _RelationLoanORM]): ...
        class ClosedLoanFactory(SQLAlchemyStateFactory[ClosedLoan, _RelationLoanORM]): ...

        # нужно указывать фабрику к полю + юнион как то передать. либо фабрик либо полей, надо подумать
        class ActiveDebtFactory(SQLAlchemyStateFactory[ActiveDebt, _RelationDebtORM]): ...
        class ClosedDebtFactory(SQLAlchemyStateFactory[ClosedDebt, _RelationDebtORM]): ...

        debt = ActiveDebtFactory.build()

        assert isinstance(debt, _RelationDebtORM)
        assert debt.status == "active"
        assert isinstance(debt.loans, list)
        assert len(debt.loans) > 0
        assert all(isinstance(loan, _RelationLoanORM) for loan in debt.loans)


class TestSqlalchemyStateFactoryTypeInference:
    class InferLoanORM(Base):
        __tablename__ = "loans_infer_test"
        id = Column(Integer, primary_key=True)
        status: Mapped[str]
        postponement_date: Mapped[datetime]

    def test_infers_both_types_from_generic_args(self) -> None:
        """Factory with [State, ORM] correctly infers both model types."""
        class F(SQLAlchemyStateFactory[ActiveLoan, self.InferLoanORM]): ...  # type: ignore[name-defined]

        loan = F.build()
        assert isinstance(loan, self.InferLoanORM)
        assert loan.status == "active"

    def test_missing_sql_model_raises(self) -> None:
        with pytest.raises(ConfigurationException, match="__sql_model__"):
            class NoModelFactory(SQLAlchemyStateFactory):  # type: ignore[type-arg]
                __model__ = ActiveLoan

    def test_no_generic_args_raises(self) -> None:
        """Factory without any generic args fails to infer types."""
        with pytest.raises(ConfigurationException):
            class F(SQLAlchemyStateFactory):  # type: ignore[type-arg]
                ...



class TestSqlalchemyStateFactoryBatch:
    class BatchLoanORM(Base):
        __tablename__ = "loans_batch_test"
        id = Column(Integer, primary_key=True)
        status: Mapped[str]
        postponement_date: Mapped[datetime]

    class BatchLoanFactory(SQLAlchemyStateFactory[ActiveLoan, BatchLoanORM]):
        ...

    def test_batch(self) -> None:
        result = self.BatchLoanFactory.batch(size=3)
        assert len(result) == 3
        for loan in result:
            assert isinstance(loan, self.BatchLoanORM)
            assert loan.status == "active"


class TestSqlalchemyStateFactoryAsync:
    class AsyncLoanORM2(Base):
        __tablename__ = "loans_async_test2"
        id = Column(Integer, primary_key=True)
        status: Mapped[str]
        postponement_date: Mapped[datetime]

    class AsyncLoanFactory(SQLAlchemyStateFactory[ActiveLoan, AsyncLoanORM2]):
        ...

    @pytest.fixture()
    def async_engine(self) -> AsyncEngine:
        return create_async_engine("sqlite+aiosqlite:///:memory:")

    @pytest.fixture(autouse=True)
    async def fx_async_setup(self, async_engine: AsyncEngine) -> AsyncIterator[None]:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def test_create_async(self, async_engine: AsyncEngine) -> None:
        async with AsyncSession(async_engine) as async_session:
            self.AsyncLoanFactory.__async_session__ = async_session
            loan = await self.AsyncLoanFactory.create_async()
            assert isinstance(loan, self.AsyncLoanORM2)
            assert loan.status == "active"

    async def test_create_batch_async(self, async_engine: AsyncEngine) -> None:
        async with AsyncSession(async_engine) as async_session:
            self.AsyncLoanFactory.__async_session__ = async_session
            loans = await self.AsyncLoanFactory.create_batch_async(size=2)
            assert len(loans) == 2
            for loan in loans:
                assert isinstance(loan, self.AsyncLoanORM2)


class TestSqlalchemyStateFactoryCallableSession:
    class CallableLoanORM(Base):
        __tablename__ = "loans_callable_test"
        id = Column(Integer, primary_key=True)
        status: Mapped[str]
        postponement_date: Mapped[datetime]

    class CallableLoanFactory(SQLAlchemyStateFactory[ActiveLoan, CallableLoanORM]):
        ...

    def test_callable_sync_session(self, engine: Engine) -> None:
        session_maker = sessionmaker(bind=engine)
        self.CallableLoanFactory.__session__ = session_maker  # type: ignore[assignment]
        loan = self.CallableLoanFactory.create_sync()
        assert isinstance(loan, self.CallableLoanORM)

    @pytest.fixture()
    def async_engine(self) -> AsyncEngine:
        return create_async_engine("sqlite+aiosqlite:///:memory:")

    @pytest.fixture(autouse=True)
    async def fx_callable_async_setup(self, async_engine: AsyncEngine) -> AsyncIterator[None]:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def test_callable_async_session(self, async_engine: AsyncEngine) -> None:
        session_maker = lambda: AsyncSession(async_engine)
        self.CallableLoanFactory.__async_session__ = session_maker
        loan = await self.CallableLoanFactory.create_async()
        assert isinstance(loan, self.CallableLoanORM)
        assert loan.status == "active"


class TestSqlalchemyStateFactoryNoSession:
    class NoSessionLoanORM(Base):
        __tablename__ = "loans_nosession_test"
        id = Column(Integer, primary_key=True)
        status: Mapped[str]
        postponement_date: Mapped[datetime]

    def test_sync_persistence_without_session_falls_through(self) -> None:
        class NoSessionFactory(SQLAlchemyStateFactory[ActiveLoan, self.NoSessionLoanORM]):  # type: ignore[name-defined]
            __session__ = None
            __async_session__ = None

        with pytest.raises(ConfigurationException):
            NoSessionFactory.create_sync()

    async def test_async_persistence_without_session_falls_through(self) -> None:
        class NoSessionFactory(SQLAlchemyStateFactory[ActiveLoan, self.NoSessionLoanORM]):  # type: ignore[name-defined]
            __session__ = None
            __async_session__ = None

        with pytest.raises(ConfigurationException):
            await NoSessionFactory.create_async()

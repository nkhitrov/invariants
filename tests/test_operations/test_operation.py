import dataclasses
from datetime import datetime
from typing import Any, cast, overload

import pytest

from examples.debt import ActiveDebt, DebtBecameOverdueEvent, DebtCreatedEvent, DebtState, OverdueDebt
from examples.loan import (
    ActiveLoan,
    ActiveLoanClosedEvent,
    CloseLoanOperation,
    ClosedLoan,
    IssueLoanOperation,
    LoanActivatedEvent,
    LoanBecameOverdueEvent,
    LoanIssuedEvent,
    LoanState,
    MakeLoanOverdueOperation,
    OverdueLoan,
    OverdueLoanClosedEvent,
)
from invariants.operations import (
    EdgeRegistry,
    Operation,
    OperationEdge,
    Query,
    Transition,
    TransitionError,
    get_operation_edges,
)

DATE = datetime(2026, 1, 1)


def active_loan(loan_id: int = 1) -> ActiveLoan:
    return ActiveLoan(id=loan_id, postponement_date=DATE)


def overdue_loan(loan_id: int = 1) -> OverdueLoan:
    return OverdueLoan(id=loan_id, postponement_date=DATE)


class TestDataclass:
    def test_dependencies_are_keyword_only_fields(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            make_overdue: MakeLoanOverdueOperation

            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return self.make_overdue.execute(loan)

        dependency = MakeLoanOverdueOperation()
        operation = FirstOperation(make_overdue=dependency)
        assert operation.make_overdue is dependency
        assert [field.name for field in dataclasses.fields(operation)] == ["make_overdue"]
        with pytest.raises(TypeError):
            FirstOperation(dependency)  # type: ignore[misc]

    def test_operation_is_frozen(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            make_overdue: MakeLoanOverdueOperation

            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return self.make_overdue.execute(loan)

        operation = FirstOperation(make_overdue=MakeLoanOverdueOperation())
        with pytest.raises(dataclasses.FrozenInstanceError):
            operation.make_overdue = MakeLoanOverdueOperation()  # type: ignore[misc]

    def test_operation_is_slotted(self) -> None:
        operation = MakeLoanOverdueOperation()
        assert not hasattr(operation, "__dict__")

    def test_query_is_dataclass(self) -> None:
        class CountQuery(Query[LoanState]):
            close_loan: CloseLoanOperation

            def execute(self, loan: ActiveLoan) -> int:
                return loan.id

        query = CountQuery(close_loan=CloseLoanOperation())
        assert query.execute(active_loan(7)) == 7
        assert not hasattr(query, "__dict__")

    def test_dependencies_must_be_operations(self) -> None:
        with pytest.raises(TypeError, match="dependencies must be operations or queries, got datetime"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                now: datetime

                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

    def test_query_dependencies_must_be_operations(self) -> None:
        with pytest.raises(TypeError, match="dependencies must be operations or queries"):

            class CountQuery(Query[LoanState]):
                limit: int

                def execute(self, loan: ActiveLoan) -> int: ...


class TestSignatureValidation:
    def test_name_must_end_with_operation(self) -> None:
        with pytest.raises(TypeError, match="must end with `Operation`"):

            class MakeOverdue(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

    def test_root_state_required(self) -> None:
        with pytest.raises(TypeError, match="parametrized with a root state"):

            class FirstOperation(Operation[ActiveLoan], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

    def test_execute_required(self) -> None:
        with pytest.raises(TypeError, match="must define execute"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                pass

    def test_source_must_be_single_concrete_state(self) -> None:
        with pytest.raises(TypeError, match="first argument must be a single concrete state of LoanState"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan | OverdueLoan) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...

    def test_source_must_belong_to_root(self) -> None:
        with pytest.raises(TypeError, match="first argument must be a single concrete state"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, debt: ActiveDebt) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

    def test_arguments_after_state_are_keyword_only(self) -> None:
        with pytest.raises(TypeError, match="must be keyword-only"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan, at: datetime) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

    def test_must_return_transition(self) -> None:
        with pytest.raises(TypeError, match="must return Transition"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> OverdueLoan: ...

    def test_target_must_belong_to_root(self) -> None:
        with pytest.raises(TypeError, match="target OverdueDebt is not a concrete state of LoanState"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueDebt, LoanBecameOverdueEvent]: ...

    def test_events_must_be_events(self) -> None:
        with pytest.raises(TypeError, match="int is not an Event"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, int]: ...  # type: ignore[type-var]

    def test_edge_requires_event(self) -> None:
        with pytest.raises(TypeError, match="edge ActiveDebt → OverdueDebt has no event"):

            class FirstOperation(Operation[DebtState], registry=EdgeRegistry()):
                def execute(self, debt: ActiveDebt) -> Transition[OverdueDebt, LoanBecameOverdueEvent]: ...

    def test_edge_event_must_match_edge(self) -> None:
        with pytest.raises(TypeError, match="LoanActivatedEvent is the event of OverdueLoan → ActiveLoan, not of ActiveLoan → OverdueLoan"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanActivatedEvent]: ...

    def test_creation_edge_event_must_start_from_none(self) -> None:
        with pytest.raises(TypeError, match="is the event of OverdueLoan → ActiveLoan, not of None → ActiveLoan"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, *, loan_id: int) -> Transition[ActiveLoan, LoanActivatedEvent]: ...

    def test_edge_emits_one_root_event(self) -> None:
        with pytest.raises(TypeError, match="must emit one event of DebtState"):

            class FirstOperation(Operation[DebtState], registry=EdgeRegistry()):
                def execute(
                    self, debt: ActiveDebt
                ) -> Transition[OverdueDebt, DebtBecameOverdueEvent | DebtCreatedEvent]: ...

    def test_events_only_from_nested_roots(self) -> None:
        with pytest.raises(TypeError, match="DebtCreatedEvent belongs to a hierarchy not nested in LoanState"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(
                    self, loan: ActiveLoan
                ) -> Transition[OverdueLoan, LoanBecameOverdueEvent | DebtCreatedEvent]: ...

    def test_loop_without_root_event(self) -> None:
        with pytest.raises(TypeError, match="loop ActiveLoan → ActiveLoan must not emit events of LoanState"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[ActiveLoan, LoanIssuedEvent]: ...

    def test_overloads_declare_each_edge_once(self) -> None:
        with pytest.raises(TypeError, match="edge ActiveLoan → ClosedLoan is declared twice"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                @overload
                def execute(self, loan: ActiveLoan) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...
                @overload
                def execute(self, loan: ActiveLoan, *, force: bool) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...
                def execute(self, loan: ActiveLoan, *, force: bool = False) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...

    def test_edge_belongs_to_one_operation(self) -> None:
        registry = EdgeRegistry()

        class FirstOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        with pytest.raises(TypeError, match="ActiveLoan → OverdueLoan is already implemented by operation FirstOperation"):

            class SecondOperation(Operation[LoanState], registry=registry):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        assert registry.get_operation((ActiveLoan, OverdueLoan)) is FirstOperation

    def test_failed_operation_registers_no_edge(self) -> None:
        registry = EdgeRegistry()
        with pytest.raises(TypeError):

            class FirstOperation(Operation[LoanState], registry=registry):
                @overload
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...
                @overload
                def execute(self, loan: OverdueLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...
                def execute(self, loan: ActiveLoan | OverdueLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        assert registry.get_operation((ActiveLoan, OverdueLoan)) is None

    def test_registry_rejects_second_owner(self) -> None:
        registry = EdgeRegistry()
        registry.register_operation((ActiveLoan, ClosedLoan), CloseLoanOperation)
        with pytest.raises(TypeError, match="already implemented by operation CloseLoanOperation"):
            registry.register_operation((ActiveLoan, ClosedLoan), MakeLoanOverdueOperation)

    def test_registry_clear(self) -> None:
        registry = EdgeRegistry()

        class FirstOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        registry.clear()
        assert registry.get_operation((ActiveLoan, OverdueLoan)) is None


class TestOperationEdges:
    def test_overloads_are_edges(self) -> None:
        assert get_operation_edges(CloseLoanOperation) == [
            OperationEdge(ActiveLoan, ClosedLoan, ActiveLoanClosedEvent, (ActiveLoanClosedEvent,)),
            OperationEdge(OverdueLoan, ClosedLoan, OverdueLoanClosedEvent, (OverdueLoanClosedEvent,)),
        ]

    def test_creation_edge(self) -> None:
        assert get_operation_edges(IssueLoanOperation) == [
            OperationEdge(None, ActiveLoan, LoanIssuedEvent, (LoanIssuedEvent,)),
        ]

    def test_default_registry_holds_example_edges(self) -> None:
        assert Operation.__registry__.get_operation((ActiveLoan, ClosedLoan)) is CloseLoanOperation


class TestRuntimeChecks:
    def test_returns_transition(self) -> None:
        loan, events = MakeLoanOverdueOperation().execute(active_loan())
        assert loan == overdue_loan()
        assert events == (LoanBecameOverdueEvent(loan_id=1),)

    def test_state_passed_by_keyword(self) -> None:
        loan, events = CloseLoanOperation().execute(loan=overdue_loan())
        assert loan == ClosedLoan(id=1)
        assert events == (OverdueLoanClosedEvent(loan_id=1),)

    def test_not_a_transition(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return cast(Transition[OverdueLoan, LoanBecameOverdueEvent], overdue_loan())

        with pytest.raises(TransitionError, match="must return Transition, got OverdueLoan"):
            FirstOperation().execute(active_loan())

    def test_undeclared_target(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return cast(Transition[OverdueLoan, LoanBecameOverdueEvent], Transition(ClosedLoan(id=1), ()))

        with pytest.raises(TransitionError, match="edge ActiveLoan → ClosedLoan is not declared"):
            FirstOperation().execute(active_loan())

    def test_undeclared_source(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return Transition(overdue_loan(), (LoanBecameOverdueEvent(loan_id=1),))

        with pytest.raises(TransitionError, match="edge OverdueLoan → OverdueLoan is not declared"):
            FirstOperation().execute(cast(Any, overdue_loan()))

    def test_events_must_be_tuple(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return Transition(overdue_loan(), cast(Any, [LoanBecameOverdueEvent(loan_id=1)]))

        with pytest.raises(TransitionError, match="events must be a tuple"):
            FirstOperation().execute(active_loan())

    def test_undeclared_event(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return Transition(overdue_loan(), cast(Any, (LoanIssuedEvent(loan_id=1),)))

        with pytest.raises(TransitionError, match="LoanIssuedEvent is not declared for edge ActiveLoan → OverdueLoan"):
            FirstOperation().execute(active_loan())

    def test_edge_event_missing(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return Transition(overdue_loan(), ())

        with pytest.raises(TransitionError, match="must emit LoanBecameOverdueEvent exactly once, got 0"):
            FirstOperation().execute(active_loan())

    def test_edge_event_twice(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                event = LoanBecameOverdueEvent(loan_id=1)
                return Transition(overdue_loan(), (event, event))

        with pytest.raises(TransitionError, match="exactly once, got 2"):
            FirstOperation().execute(active_loan())

    def test_loop_without_events(self) -> None:
        class FirstOperation(Operation[DebtState], registry=EdgeRegistry()):
            def execute(self, debt: ActiveDebt) -> Transition[ActiveDebt, LoanIssuedEvent]:
                return Transition(debt, ())

        debt = ActiveDebt(id=1, loans=(active_loan(),))
        with pytest.raises(TransitionError, match="loop ActiveDebt → ActiveDebt must emit at least one event"):
            FirstOperation().execute(debt)

    def test_creation_checked(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, *, loan_id: int) -> Transition[ActiveLoan, LoanIssuedEvent]:
                return Transition(active_loan(loan_id), ())

        with pytest.raises(TransitionError, match="must emit LoanIssuedEvent exactly once"):
            FirstOperation().execute(loan_id=1)

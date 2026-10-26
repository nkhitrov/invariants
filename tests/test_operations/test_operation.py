import dataclasses
from datetime import date
from decimal import Decimal
from typing import Any, Never, cast, overload

import pytest

from examples.debt import ActiveDebt, DebtBecameOverdueEvent, DebtOpenedEvent, DebtState, OverdueDebt
from examples.loan import (
    AccruePenaltyOperation,
    ActiveLoan,
    ActiveLoanClosedEvent,
    CancelLoanOverdueOperation,
    CloseLoanOperation,
    ClosedLoan,
    Installment,
    IssueLoanOperation,
    LoanBecameOverdueEvent,
    LoanIssuedEvent,
    LoanOverdueCancelledEvent,
    LoanState,
    OverdueLoan,
    OverdueLoanClosedEvent,
    RecalculateLoanTermsOperation,
)
from examples.payment import PaymentReceivedEvent
from invariants.operations import (
    EdgeRegistry,
    Operation,
    OperationEdge,
    Query,
    Transition,
    TransitionError,
    get_operation_edges,
)

DAY = date(2026, 1, 1)
SCHEDULE = (Installment(postponement_date=date(2026, 1, 31), amount=Decimal(1000)),)


def active_loan(loan_id: int = 1) -> ActiveLoan:
    return ActiveLoan(id=loan_id, financed_amount=Decimal(1000), booking_date=DAY, schedule=SCHEDULE)


def overdue_loan(loan_id: int = 1) -> OverdueLoan:
    return OverdueLoan(id=loan_id, financed_amount=Decimal(1000), booking_date=DAY, schedule=SCHEDULE)


def closed_loan(loan_id: int = 1) -> ClosedLoan:
    return ClosedLoan(id=loan_id, financed_amount=Decimal(1000), booking_date=DAY, schedule=SCHEDULE)


class TestDataclass:
    def test_dependencies_are_keyword_only_fields(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            accrue: AccruePenaltyOperation

            def execute(self, loan: OverdueLoan) -> Transition[OverdueLoan, Never]:
                return self.accrue.execute(loan, booking_date=DAY)

        dependency = AccruePenaltyOperation()
        operation = FirstOperation(accrue=dependency)
        assert operation.accrue is dependency
        assert [field.name for field in dataclasses.fields(operation)] == ["accrue"]
        with pytest.raises(TypeError):
            FirstOperation(dependency)  # type: ignore[misc]

    def test_operation_is_frozen(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            accrue: AccruePenaltyOperation

            def execute(self, loan: OverdueLoan) -> Transition[OverdueLoan, Never]:
                return self.accrue.execute(loan, booking_date=DAY)

        operation = FirstOperation(accrue=AccruePenaltyOperation())
        with pytest.raises(dataclasses.FrozenInstanceError):
            operation.accrue = AccruePenaltyOperation()  # type: ignore[misc]

    def test_operation_is_slotted(self) -> None:
        assert not hasattr(AccruePenaltyOperation(), "__dict__")

    def test_query_is_dataclass(self) -> None:
        class LoanIdQuery(Query[LoanState]):
            close_loan: CloseLoanOperation

            def execute(self, loan: ActiveLoan) -> int:
                return loan.id

        query = LoanIdQuery(close_loan=CloseLoanOperation())
        assert query.execute(active_loan(7)) == 7
        assert not hasattr(query, "__dict__")

    def test_dependencies_must_be_operations(self) -> None:
        with pytest.raises(TypeError, match="dependencies must be operations or queries, got date"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                today: date

                def execute(self, loan: OverdueLoan) -> Transition[OverdueLoan, Never]: ...

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
                def execute(self, loan: ActiveLoan, at: date) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

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
        with pytest.raises(TypeError, match="edge ActiveLoan → OverdueLoan has no event"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, Never]: ...

    def test_edge_event_must_match_edge(self) -> None:
        with pytest.raises(
            TypeError,
            match="LoanOverdueCancelledEvent is the event of OverdueLoan → ActiveLoan, not of ActiveLoan → OverdueLoan",
        ):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanOverdueCancelledEvent]: ...

    def test_creation_edge_event_must_start_from_none(self) -> None:
        with pytest.raises(TypeError, match="is the event of OverdueLoan → ActiveLoan, not of None → ActiveLoan"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, *, loan_id: int) -> Transition[ActiveLoan, LoanOverdueCancelledEvent]: ...

    def test_edge_emits_one_root_event(self) -> None:
        with pytest.raises(TypeError, match="must emit one event of DebtState"):

            class FirstOperation(Operation[DebtState], registry=EdgeRegistry()):
                def execute(
                    self, debt: ActiveDebt
                ) -> Transition[OverdueDebt, DebtBecameOverdueEvent | DebtOpenedEvent]: ...

    def test_events_only_from_nested_roots(self) -> None:
        with pytest.raises(TypeError, match="DebtOpenedEvent belongs to a hierarchy not nested in LoanState"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(
                    self, loan: ActiveLoan
                ) -> Transition[OverdueLoan, LoanBecameOverdueEvent | DebtOpenedEvent]: ...

    def test_overloads_declare_each_edge_once(self) -> None:
        with pytest.raises(TypeError, match="edge ActiveLoan → ClosedLoan is declared twice"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                @overload
                def execute(self, loan: ActiveLoan) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...
                @overload
                def execute(self, loan: ActiveLoan, *, force: bool) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...
                def execute(self, loan: ActiveLoan, *, force: bool = False) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...


class TestLoops:
    def test_loop_without_events(self) -> None:
        registry = EdgeRegistry()

        class FirstOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[ActiveLoan, Never]:
                return Transition(loan, ())

        assert get_operation_edges(FirstOperation) == [OperationEdge(ActiveLoan, ActiveLoan, None, ())]
        assert FirstOperation().execute(active_loan()) == (active_loan(), ())

    def test_loop_has_no_root_event(self) -> None:
        with pytest.raises(TypeError, match="loop ActiveLoan → ActiveLoan must not emit events of LoanState"):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[ActiveLoan, LoanIssuedEvent]: ...

    def test_loop_is_not_an_owned_edge(self) -> None:
        registry = EdgeRegistry()

        class FirstOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[ActiveLoan, Never]:
                return Transition(loan, ())

        class SecondOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan, *, booking_date: date) -> Transition[ActiveLoan, Never]:
                return Transition(loan, ())

        assert registry.get_operation((ActiveLoan, ActiveLoan)) is None
        assert SecondOperation().execute(active_loan(), booking_date=DAY).events == ()

    def test_loop_with_delegated_nested_events(self) -> None:
        class FirstOperation(Operation[DebtState], registry=EdgeRegistry()):
            recalculate: RecalculateLoanTermsOperation

            def execute(self, debt: OverdueDebt) -> Transition[OverdueDebt, LoanBecameOverdueEvent]:
                return Transition(debt, ())

        debt = OverdueDebt(id=1, loans=(overdue_loan(),))
        assert FirstOperation(recalculate=RecalculateLoanTermsOperation()).execute(debt) == (debt, ())


class TestOwnershipAndDelegation:
    def test_edge_has_one_owner(self) -> None:
        registry = EdgeRegistry()

        class FirstOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        with pytest.raises(
            TypeError,
            match="edge ActiveLoan → OverdueLoan is already owned by operation FirstOperation; delegate to it",
        ):

            class SecondOperation(Operation[LoanState], registry=registry):
                def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        assert registry.get_operation((ActiveLoan, OverdueLoan)) is FirstOperation

    def test_delegating_operation_does_not_own_the_edge(self) -> None:
        registry = EdgeRegistry()

        class OwnerOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return Transition(overdue_loan(loan.id), (LoanBecameOverdueEvent(loan_id=loan.id),))

        class DelegatingOperation(Operation[LoanState], registry=registry):
            owner: OwnerOperation

            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return self.owner.execute(loan)

        assert registry.get_operation((ActiveLoan, OverdueLoan)) is OwnerOperation
        result = DelegatingOperation(owner=OwnerOperation()).execute(active_loan())
        assert result.events == (LoanBecameOverdueEvent(loan_id=1),)

    def test_delegation_is_transitive(self) -> None:
        registry = EdgeRegistry()

        class OwnerOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        class MiddleQuery(Query[LoanState]):
            owner: OwnerOperation

            def execute(self, loan: ActiveLoan) -> int: ...

        class TopOperation(Operation[LoanState], registry=registry):
            middle: MiddleQuery

            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        assert registry.get_operation((ActiveLoan, OverdueLoan)) is OwnerOperation
        assert get_operation_edges(TopOperation)[0].event is LoanBecameOverdueEvent

    def test_nested_event_requires_delegation(self) -> None:
        with pytest.raises(
            TypeError,
            match="PaymentReceivedEvent is the event of None → ReceivedPayment, which no dependency implements",
        ):

            class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
                def execute(self, loan: ActiveLoan) -> Transition[ActiveLoan, PaymentReceivedEvent]: ...

    def test_nested_event_of_nested_dependency(self) -> None:
        class FirstOperation(Operation[DebtState], registry=EdgeRegistry()):
            issue_loan: IssueLoanOperation

            def execute(self, *, debt_id: int) -> Transition[ActiveDebt, DebtOpenedEvent | LoanIssuedEvent]:
                loan, events = self.issue_loan.execute(
                    loan_id=1, financed_amount=Decimal(1000), booking_date=DAY, schedule=SCHEDULE
                )
                return Transition(ActiveDebt(id=debt_id, loans=(loan,)), (DebtOpenedEvent(debt_id=debt_id), *events))

        debt, events = FirstOperation(issue_loan=IssueLoanOperation()).execute(debt_id=1)
        assert events == (DebtOpenedEvent(debt_id=1), LoanIssuedEvent(loan_id=1))

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
            registry.register_operation((ActiveLoan, ClosedLoan), CancelLoanOverdueOperation)

    def test_registry_clear(self) -> None:
        registry = EdgeRegistry()

        class FirstOperation(Operation[LoanState], registry=registry):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]: ...

        registry.clear()
        assert registry.get_operation((ActiveLoan, OverdueLoan)) is None

    def test_default_registry_holds_example_owners(self) -> None:
        assert Operation.__registry__.get_operation((ActiveLoan, ClosedLoan)) is CloseLoanOperation
        assert Operation.__registry__.get_operation((OverdueLoan, ActiveLoan)) is CancelLoanOverdueOperation


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

    def test_union_with_loop(self) -> None:
        assert get_operation_edges(RecalculateLoanTermsOperation) == [
            OperationEdge(ActiveLoan, OverdueLoan, LoanBecameOverdueEvent, (LoanBecameOverdueEvent,)),
            OperationEdge(ActiveLoan, ActiveLoan, None, ()),
        ]


class TestRuntimeChecks:
    def test_state_passed_by_keyword(self) -> None:
        loan, events = AccruePenaltyOperation().execute(loan=overdue_loan(), booking_date=date(2026, 2, 1))
        assert loan.booking_date == date(2026, 2, 1)
        assert events == ()

    def test_not_a_transition(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return cast(Transition[OverdueLoan, LoanBecameOverdueEvent], overdue_loan())

        with pytest.raises(TransitionError, match="must return Transition, got OverdueLoan"):
            FirstOperation().execute(active_loan())

    def test_undeclared_target(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
                return cast(Transition[OverdueLoan, LoanBecameOverdueEvent], Transition(closed_loan(), ()))

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

    def test_undeclared_event_in_loop(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, loan: ActiveLoan) -> Transition[ActiveLoan, Never]:
                return Transition(loan, cast(Any, (LoanIssuedEvent(loan_id=1),)))

        with pytest.raises(TransitionError, match="LoanIssuedEvent is not declared for edge ActiveLoan → ActiveLoan"):
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

    def test_creation_checked(self) -> None:
        class FirstOperation(Operation[LoanState], registry=EdgeRegistry()):
            def execute(self, *, loan_id: int) -> Transition[ActiveLoan, LoanIssuedEvent]:
                return Transition(active_loan(loan_id), ())

        with pytest.raises(TransitionError, match="must emit LoanIssuedEvent exactly once"):
            FirstOperation().execute(loan_id=1)

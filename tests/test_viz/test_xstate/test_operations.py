import importlib

from examples.debt import (
    ActivateDebtLoanOperation,
    ActiveDebt,
    AddLoanToDebtOperation,
    CheckDebtOverdueDaysQuery,
    CloseDebtOperation,
    ClosedDebt,
    CreateDebtOperation,
    MakeDebtOverdueOperation,
    OverdueDebt,
)
from examples.loan import (
    ActiveLoan,
    CloseLoanOperation,
    ClosedLoan,
    IssueLoanOperation,
    OverdueLoan,
)
from examples.loan import LoanBecameOverdueEvent
from invariants.operations import Transition as OperationTransition
from invariants.viz.xstate import Transition, build_xstate_config, discover_machines, extract_transitions


class TestExtractOperationTransitions:
    def test_overloads_named_after_events(self) -> None:
        assert extract_transitions(CloseLoanOperation) == [
            Transition(source=ActiveLoan, target=ClosedLoan, event="ActiveLoanClosedEvent"),
            Transition(source=OverdueLoan, target=ClosedLoan, event="OverdueLoanClosedEvent"),
        ]

    def test_creation_has_no_source(self) -> None:
        assert extract_transitions(IssueLoanOperation) == [
            Transition(source=None, target=ActiveLoan, event="LoanIssuedEvent"),
        ]

    def test_loop_named_after_operation(self) -> None:
        assert extract_transitions(AddLoanToDebtOperation) == [
            Transition(source=ActiveDebt, target=ActiveDebt, event="AddLoanToDebtOperation"),
        ]

    def test_union_of_transitions(self) -> None:
        assert extract_transitions(ActivateDebtLoanOperation) == [
            Transition(source=OverdueDebt, target=ActiveDebt, event="DebtBecameActiveEvent"),
            Transition(source=OverdueDebt, target=OverdueDebt, event="ActivateDebtLoanOperation"),
        ]

    def test_query_skipped(self) -> None:
        assert extract_transitions(CheckDebtOverdueDaysQuery) is None

    def test_invalid_operation_skipped(self) -> None:
        """A machine returning Transition but breaking operation rules is not a diagram edge."""

        class Plain:
            def execute(self, loan: ActiveLoan) -> OperationTransition[OverdueLoan, LoanBecameOverdueEvent]: ...

        assert extract_transitions(Plain) is None


class TestOperationConfig:
    machines = [
        CreateDebtOperation, AddLoanToDebtOperation, MakeDebtOverdueOperation,
        ActivateDebtLoanOperation, CloseDebtOperation, CheckDebtOverdueDaysQuery,
    ]

    def test_initial_from_creation(self) -> None:
        configs = build_xstate_config([CloseLoanOperation, IssueLoanOperation])
        assert configs["LoanState"]["initial"] == "ActiveLoan"

    def test_creation_is_not_an_outgoing_transition(self) -> None:
        configs = build_xstate_config([IssueLoanOperation])
        assert configs["LoanState"]["states"]["ActiveLoan"] == {"type": "final"}

    def test_debt_states(self) -> None:
        states = build_xstate_config(self.machines)["DebtState"]["states"]
        assert set(states["ActiveDebt"]["on"]) == {
            "AddLoanToDebtOperation", "ActiveDebtClosedEvent", "DebtBecameOverdueEvent",
        }
        assert set(states["OverdueDebt"]["on"]) == {
            "DebtBecameActiveEvent", "ActivateDebtLoanOperation", "OverdueDebtClosedEvent",
        }
        assert states[ClosedDebt.__name__]["type"] == "final"

    def test_discovers_operations_of_examples(self) -> None:
        machines = discover_machines(importlib.import_module("examples.debt"))
        names = {m.__name__ for m in machines}
        assert {"CreateDebtOperation", "CheckDebtOverdueDaysQuery", "CloseLoanOperation"} <= names

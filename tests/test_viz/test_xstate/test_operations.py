import importlib

from examples.debt import (
    CancelDebtOverdueOperation,
    CheckDebtOverdueDaysQuery,
    CloseDebtOperation,
    OpenDebtOperation,
    OverdueDebt,
    RecalculateDebtOperation,
    ReceiveDebtPaymentOperation,
)
from examples.loan import (
    AccruePenaltyOperation,
    ActiveLoan,
    CloseLoanOperation,
    ClosedLoan,
    IssueLoanOperation,
    LoanBecameOverdueEvent,
    OverdueLoan,
    RecalculateLoanTermsOperation,
)
from invariants.operations import Transition as OperationTransition
from invariants.viz.xstate import (
    Transition,
    build_xstate_config,
    discover_machines,
    extract_transitions,
    render_xstate_code,
)


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

    def test_loop_is_internal_and_named_after_operation(self) -> None:
        assert extract_transitions(AccruePenaltyOperation) == [
            Transition(source=OverdueLoan, target=OverdueLoan, event="AccruePenaltyOperation", internal=True),
        ]

    def test_union_with_loop(self) -> None:
        assert extract_transitions(RecalculateLoanTermsOperation) == [
            Transition(source=ActiveLoan, target=OverdueLoan, event="LoanBecameOverdueEvent"),
            Transition(source=ActiveLoan, target=ActiveLoan, event="RecalculateLoanTermsOperation", internal=True),
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
        OpenDebtOperation, RecalculateDebtOperation, CancelDebtOverdueOperation,
        ReceiveDebtPaymentOperation, CloseDebtOperation, CheckDebtOverdueDaysQuery,
    ]

    def test_initial_from_creation(self) -> None:
        configs = build_xstate_config([CloseLoanOperation, IssueLoanOperation])
        assert configs["LoanState"]["initial"] == "ActiveLoan"

    def test_creation_is_not_an_outgoing_transition(self) -> None:
        configs = build_xstate_config([IssueLoanOperation])
        assert configs["LoanState"]["states"]["ActiveLoan"] == {"type": "final"}

    def test_loops_are_internal_transitions(self) -> None:
        states = build_xstate_config(self.machines)["DebtState"]["states"]
        assert states["OverdueDebt"]["on"]["RecalculateDebtOperation"] == [{}]
        assert states["OverdueDebt"]["on"]["ReceiveDebtPaymentOperation"] == [{}]

    def test_internal_transitions_get_no_guard(self) -> None:
        """With the loan machine present debt edges get guards, loops stay targetless."""
        machines = [*self.machines, CloseLoanOperation, AccruePenaltyOperation]
        states = build_xstate_config(machines)["DebtState"]["states"]
        assert states["OverdueDebt"]["on"]["RecalculateDebtOperation"] == [{}]
        assert "guard" in states["OverdueDebt"]["on"]["OverdueDebtClosedEvent"][0]

    def test_same_nested_field_everywhere_gives_no_guard(self) -> None:
        """Every loan state holds ``tuple[ReceivedPayment, ...]``: no guard tells them apart."""
        code = render_xstate_code(discover_machines(importlib.import_module("examples.loan")))
        assert "onlyReceivedPayment" not in code
        assert "LoanBecameOverdueEvent: 'OverdueLoan'," in code

    def test_delegated_edge_is_drawn_once(self) -> None:
        states = build_xstate_config(self.machines)["DebtState"]["states"]
        assert states["OverdueDebt"]["on"]["DebtOverdueCancelledEvent"] == "ActiveDebt"

    def test_debt_states(self) -> None:
        states = build_xstate_config(self.machines)["DebtState"]["states"]
        assert set(states["ActiveDebt"]["on"]) == {
            "ActiveDebtClosedEvent", "DebtBecameOverdueEvent",
            "RecalculateDebtOperation", "ReceiveDebtPaymentOperation",
        }
        assert set(states["OverdueDebt"]["on"]) == {
            "DebtOverdueCancelledEvent", "OverdueDebtClosedEvent",
            "RecalculateDebtOperation", "ReceiveDebtPaymentOperation",
        }
        assert states["ClosedDebt"]["type"] == "final"
        assert OverdueDebt.__name__ in states

    def test_internal_transition_rendered_targetless(self) -> None:
        code = render_xstate_code([AccruePenaltyOperation, CloseLoanOperation])
        assert "AccruePenaltyOperation: [{}]," in code

    def test_discovers_operations_of_examples(self) -> None:
        machines = discover_machines(importlib.import_module("examples.debt"))
        names = {m.__name__ for m in machines}
        assert {"OpenDebtOperation", "CheckDebtOverdueDaysQuery", "CloseLoanOperation"} <= names

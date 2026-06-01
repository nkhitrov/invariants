from invariants.viz.xstate import (
    NestingRelation,
    Transition,
    attach_guards,
    detect_all_nestings,
    detect_nesting,
)
from tests.support.states import (
    ActivateLoan,
    ActiveDebt,
    ActiveLoan,
    ChangeOverdueDebtToActive,
    CloseDebt,
    ClosedDebt,
    ClosedLoan,
    CloseLoan,
    DebtState,
    LoanState,
    MakeLoanOverdue,
    OverdueDebt,
    OverdueLoan,
)


class TestDetectNesting:
    def test_detects_loan_in_debt(self) -> None:
        machines = [CloseDebt, MakeLoanOverdue, CloseLoan, ActivateLoan]
        nestings = detect_all_nestings(machines)
        assert len(nestings) == 1
        n = nestings[0]
        assert n.parent_root is DebtState
        assert n.child_root is LoanState
        assert n.field_name == "loans"

    def test_allowed_children(self) -> None:
        machines = [CloseDebt, MakeLoanOverdue, CloseLoan, ActivateLoan]
        nestings = detect_all_nestings(machines)
        n = nestings[0]
        assert n.allowed_children[ActiveDebt] == {ActiveLoan, ClosedLoan}
        assert n.allowed_children[ClosedDebt] == {ClosedLoan}
        assert n.allowed_children[OverdueDebt] == {OverdueLoan, ActiveLoan, ClosedLoan}

    def test_no_nesting_without_child_machines(self) -> None:
        machines = [CloseDebt, ChangeOverdueDebtToActive]
        nestings = detect_all_nestings(machines)
        assert nestings == []

    def test_no_child_roots(self) -> None:
        result = detect_nesting(DebtState, set())
        assert result == []


class TestAttachGuards:
    def test_no_nesting_keeps_transitions(self) -> None:
        """Transitions without matching nestings pass through unchanged."""
        transitions = [
            Transition(source=ActiveLoan, target=ClosedLoan, event="CloseLoan"),
        ]
        result = attach_guards(transitions, [])
        assert result == transitions
        assert result[0].guard is None


class TestAttachGuardsEdgeCases:
    def test_guard_attached_to_matching_transition(self) -> None:
        nesting = NestingRelation(
            parent_root=DebtState,
            child_root=LoanState,
            field_name="loans",
            allowed_children={ClosedDebt: {ClosedLoan}},
        )
        transitions = [
            Transition(source=ActiveDebt, target=ClosedDebt, event="CloseDebt"),
        ]
        result = attach_guards(transitions, [nesting])
        assert result[0].guard is not None

    def test_no_guard_when_target_not_in_nesting(self) -> None:
        nesting = NestingRelation(
            parent_root=DebtState,
            child_root=LoanState,
            field_name="loans",
            allowed_children={ClosedDebt: {ClosedLoan}},
        )
        transitions = [
            Transition(source=OverdueDebt, target=ActiveDebt, event="Activate"),
        ]
        result = attach_guards(transitions, [nesting])
        assert result[0].guard is None

    def test_break_on_first_match(self) -> None:
        """Only the first matching nesting should be used."""
        nesting1 = NestingRelation(
            parent_root=DebtState,
            child_root=LoanState,
            field_name="loans",
            allowed_children={ClosedDebt: {ClosedLoan}},
        )
        nesting2 = NestingRelation(
            parent_root=DebtState,
            child_root=LoanState,
            field_name="other",
            allowed_children={ClosedDebt: {ClosedLoan}},
        )
        transitions = [
            Transition(source=ActiveDebt, target=ClosedDebt, event="CloseDebt"),
        ]
        result = attach_guards(transitions, [nesting1, nesting2])
        assert len(result) == 1
        assert result[0].guard is not None


class TestDetectNestingEdgeCases:
    def test_returns_empty_when_no_child_roots(self) -> None:
        result = detect_nesting(DebtState, set())
        assert result == []

    def test_does_not_nest_self(self) -> None:
        """A root should not detect nesting with itself."""
        result = detect_nesting(LoanState, {LoanState})
        assert result == []


class TestDetectAllNestings:
    def test_no_machines(self) -> None:
        assert detect_all_nestings([]) == []

    def test_single_hierarchy_no_nesting(self) -> None:
        machines = [MakeLoanOverdue, CloseLoan, ActivateLoan]
        nestings = detect_all_nestings(machines)
        assert nestings == []

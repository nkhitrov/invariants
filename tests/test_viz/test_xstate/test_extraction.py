from invariants.state import StateMachine
from invariants.viz.xstate import (
    Transition,
    extract_transitions,
    get_concrete_states,
    get_root_state,
)
from tests.support.states import (
    ActiveDebt,
    ActiveLoan,
    ChangeOverdueDebtAndLoanToActive,
    ChangeOverdueDebtToActive,
    CheckDebtOverdueDays,
    CloseDebt,
    ClosedDebt,
    CloseLoan,
    DebtState,
    LoanState,
    OverdueDebt,
    OverdueLoan,
)


class TestGetRootState:
    def test_extracts_debt_state(self) -> None:
        assert get_root_state(CloseDebt) is DebtState

    def test_extracts_loan_state(self) -> None:
        assert get_root_state(ChangeOverdueDebtAndLoanToActive) is LoanState

    def test_returns_none_for_non_machine(self) -> None:
        assert get_root_state(ActiveDebt) is None


class TestGetConcreteStates:
    def test_debt_states(self) -> None:
        concrete = get_concrete_states(DebtState)
        names = {s.__name__ for s in concrete}
        assert names == {"ActiveDebt", "ClosedDebt", "OverdueDebt"}


class TestExtractTransitions:
    def test_close_debt(self) -> None:
        transitions = extract_transitions(CloseDebt)
        assert transitions is not None
        assert len(transitions) == 2
        sources = {t.source for t in transitions}
        assert sources == {ActiveDebt, OverdueDebt}
        assert all(t.target is ClosedDebt for t in transitions)
        assert all(t.event == "CloseDebt" for t in transitions)

    def test_single_transition(self) -> None:
        transitions = extract_transitions(ChangeOverdueDebtToActive)
        assert transitions == [
            Transition(source=OverdueDebt, target=ActiveDebt, event="ChangeOverdueDebtToActive")
        ]

    def test_skip_query_machine(self) -> None:
        """Machines returning non-State types (int) should be skipped."""
        assert extract_transitions(CheckDebtOverdueDays) is None

    def test_skip_cross_hierarchy(self) -> None:
        """Machine with LoanState root but DebtState return should be skipped."""
        assert extract_transitions(ChangeOverdueDebtAndLoanToActive) is None


class TestExtractTransitionsEdgeCases:
    def test_no_execute_method(self) -> None:
        """Class without execute method returns None."""
        class NoExecute(StateMachine[DebtState]):
            pass

        assert extract_transitions(NoExecute) is None

    def test_execute_too_few_params(self) -> None:
        """execute with only self returns None."""
        class BadParams(StateMachine[DebtState]):
            def execute(self) -> ActiveDebt:
                ...

        assert extract_transitions(BadParams) is None

    def test_execute_missing_return_annotation(self) -> None:
        """execute without return type annotation returns None."""
        class NoReturn(StateMachine[DebtState]):
            def execute(self, debt: ActiveDebt) -> None:
                ...

        assert extract_transitions(NoReturn) is None

    def test_execute_non_state_input(self) -> None:
        """execute with non-State input type returns None."""
        class NonStateInput(StateMachine[DebtState]):
            def execute(self, x: int) -> ActiveDebt:
                ...

        assert extract_transitions(NonStateInput) is None

    def test_execute_non_state_return(self) -> None:
        """execute with non-State return type returns None."""
        class NonStateReturn(StateMachine[DebtState]):
            def execute(self, debt: ActiveDebt) -> str:
                ...

        assert extract_transitions(NonStateReturn) is None


class TestGetRootStateEdgeCases:
    def test_machine_without_generic(self) -> None:
        class Plain(StateMachine):  # type: ignore[type-arg]
            pass
        assert get_root_state(Plain) is None

    def test_machine_with_non_state_generic(self) -> None:
        """StateMachine with non-State type arg returns None."""
        # get_root_state checks isinstance(args[0], type) and issubclass(args[0], State)
        class IntMachine(StateMachine[int]):
            pass
        assert get_root_state(IntMachine) is None


class TestGetConcreteStatesEdgeCases:
    def test_returns_only_non_statefull(self) -> None:
        concrete = get_concrete_states(LoanState)
        # All concrete states should NOT have statefull fields
        for s in concrete:
            assert not s.has_statefull_fields()

    def test_root_itself_not_in_result(self) -> None:
        concrete = get_concrete_states(LoanState)
        assert LoanState not in concrete


class TestExtractTransitionsValidMachine:
    def test_all_transitions_have_event_name(self) -> None:
        transitions = extract_transitions(CloseLoan)
        assert transitions is not None
        assert all(t.event == "CloseLoan" for t in transitions)

    def test_union_input_produces_multiple_transitions(self) -> None:
        transitions = extract_transitions(CloseLoan)
        assert transitions is not None
        sources = {t.source for t in transitions}
        assert sources == {ActiveLoan, OverdueLoan}

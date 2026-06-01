from invariants.state import StateMachine
from invariants.viz.xstate import (
    Transition,
    _build_on_dict,
    build_xstate_config,
    get_concrete_states,
)
from tests.support.states import (
    ActivateLoan,
    ActiveDebt,
    ActiveLoan,
    ChangeOverdueDebtAndLoanToActive,
    ChangeOverdueDebtToActive,
    CheckDebtOverdueDays,
    CloseDebt,
    ClosedDebt,
    ClosedLoan,
    CloseLoan,
    DebtState,
    MakeDebtOverdue,
    MakeLoanOverdue,
    OverdueDebt,
    OverdueLoan,
)


class TestBuildXstateConfigMultipleTargets:
    def test_union_output_produces_multiple_targets(self) -> None:
        """Machine with union output creates multiple transitions from same source/event."""
        class ForkDebt(StateMachine[DebtState]):
            def execute(self, debt: ActiveDebt) -> ClosedDebt | OverdueDebt: ...

        configs = build_xstate_config([ForkDebt])
        on = configs["DebtState"]["states"]["ActiveDebt"]["on"]
        assert on["ForkDebt"] == ["ClosedDebt", "OverdueDebt"]

    def test_three_targets_same_event(self) -> None:
        """Machine with 3-way union output appends all targets to list."""
        class TripleDebt(StateMachine[DebtState]):
            def execute(self, debt: ActiveDebt) -> ActiveDebt | ClosedDebt | OverdueDebt: ...

        configs = build_xstate_config([TripleDebt])
        on = configs["DebtState"]["states"]["ActiveDebt"]["on"]
        assert on["TripleDebt"] == ["ActiveDebt", "ClosedDebt", "OverdueDebt"]

    def test_guarded_union_output_multiple_targets(self) -> None:
        """Guarded machine with union output creates list of guarded transition objects."""
        class ForkDebt(StateMachine[DebtState]):
            def execute(self, debt: ActiveDebt) -> ClosedDebt | OverdueDebt: ...

        machines = [ForkDebt, MakeLoanOverdue, CloseLoan, ActivateLoan]
        configs = build_xstate_config(machines)
        on = configs["DebtState"]["states"]["ActiveDebt"]["on"]
        # Two guarded transitions for same event
        assert len(on["ForkDebt"]) == 2
        assert all(isinstance(t, dict) and "guard" in t for t in on["ForkDebt"])


class TestBuildXstateConfig:
    def test_debt_config(self) -> None:
        machines = [CloseDebt, ChangeOverdueDebtToActive]
        configs = build_xstate_config(machines)

        assert "DebtState" in configs
        config = configs["DebtState"]
        assert config["id"] == "DebtState"
        assert "states" in config

        states = config["states"]
        assert "ActiveDebt" in states
        assert "ClosedDebt" in states
        assert "OverdueDebt" in states

        assert states["ActiveDebt"]["on"] == {"CloseDebt": "ClosedDebt"}
        assert states["OverdueDebt"]["on"] == {
            "CloseDebt": "ClosedDebt",
            "ChangeOverdueDebtToActive": "ActiveDebt",
        }
        assert states["ClosedDebt"]["type"] == "final"

    def test_skips_invalid_machines(self) -> None:
        machines = [CheckDebtOverdueDays, ChangeOverdueDebtAndLoanToActive]
        configs = build_xstate_config(machines)
        assert configs == {}

    def test_machine_without_root_state_skipped(self) -> None:
        """Machine with no generic parameter should be skipped."""
        class Plain(StateMachine):  # type: ignore[type-arg]
            def execute(self, debt: ActiveDebt) -> ClosedDebt:
                ...

        configs = build_xstate_config([Plain])
        assert configs == {}

    def test_invalid_machine_before_valid_does_not_break_loop(self) -> None:
        """Invalid machines should be skipped (continue), not stop processing (break)."""
        class Invalid(StateMachine):  # type: ignore[type-arg]
            pass

        configs = build_xstate_config([Invalid, CloseDebt])
        assert "DebtState" in configs

    def test_query_machine_before_valid_does_not_break_loop(self) -> None:
        """Query machines (non-State return) should be skipped, not stop processing."""
        configs = build_xstate_config([CheckDebtOverdueDays, CloseDebt])
        assert "DebtState" in configs


class TestBuildXstateConfigWithGuards:
    def test_both_machines_rendered(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        configs = build_xstate_config(machines)
        assert "DebtState" in configs
        assert "LoanState" in configs

    def test_debt_flat_with_guards(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        configs = build_xstate_config(machines)
        states = configs["DebtState"]["states"]

        # No nested states
        assert "states" not in states["ActiveDebt"]
        assert "states" not in states["OverdueDebt"]

        # Guards on transitions
        assert states["ActiveDebt"]["on"]["CloseDebt"] == [
            {"target": "ClosedDebt", "guard": "onlyClosedLoan"}
        ]
        assert states["ActiveDebt"]["on"]["MakeDebtOverdue"] == [
            {"target": "OverdueDebt", "guard": {"type": "and", "guards": ["anyOverdueLoan", "onlyOverdueLoanOrActiveLoanOrClosedLoan"]}}
        ]

    def test_loan_standalone_no_guards(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        configs = build_xstate_config(machines)
        loan_states = configs["LoanState"]["states"]

        # Simple string targets, no guards
        assert loan_states["ActiveLoan"]["on"]["MakeLoanOverdue"] == "OverdueLoan"
        assert loan_states["ActiveLoan"]["on"]["CloseLoan"] == "ClosedLoan"

    def test_closed_debt_final(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        configs = build_xstate_config(machines)
        assert configs["DebtState"]["states"]["ClosedDebt"]["type"] == "final"


class TestBuildOnDict:
    def test_simple_transition(self) -> None:
        transitions = [
            Transition(source=ActiveLoan, target=ClosedLoan, event="CloseLoan"),
        ]
        result = _build_on_dict(ActiveLoan, transitions)
        assert result == {"CloseLoan": "ClosedLoan"}

    def test_multiple_events(self) -> None:
        transitions = [
            Transition(source=ActiveLoan, target=ClosedLoan, event="CloseLoan"),
            Transition(source=ActiveLoan, target=OverdueLoan, event="MakeLoanOverdue"),
        ]
        result = _build_on_dict(ActiveLoan, transitions)
        assert result == {
            "CloseLoan": "ClosedLoan",
            "MakeLoanOverdue": "OverdueLoan",
        }

    def test_guarded_transition(self) -> None:
        transitions = [
            Transition(source=ActiveDebt, target=ClosedDebt, event="CloseDebt", guard="onlyClosedLoan"),
        ]
        result = _build_on_dict(ActiveDebt, transitions)
        assert result == {"CloseDebt": [{"target": "ClosedDebt", "guard": "onlyClosedLoan"}]}

    def test_does_not_include_other_sources(self) -> None:
        transitions = [
            Transition(source=ActiveLoan, target=ClosedLoan, event="CloseLoan"),
            Transition(source=OverdueLoan, target=ClosedLoan, event="CloseLoan"),
        ]
        result = _build_on_dict(ActiveLoan, transitions)
        assert result == {"CloseLoan": "ClosedLoan"}

    def test_multiple_unguarded_targets_same_event(self) -> None:
        transitions = [
            Transition(source=ActiveDebt, target=ClosedDebt, event="Fork"),
            Transition(source=ActiveDebt, target=OverdueDebt, event="Fork"),
        ]
        result = _build_on_dict(ActiveDebt, transitions)
        assert result == {"Fork": ["ClosedDebt", "OverdueDebt"]}


class TestBuildXstateConfigEdgeCases:
    def test_initial_state_is_first_concrete(self) -> None:
        machines = [CloseDebt]
        configs = build_xstate_config(machines)
        config = configs["DebtState"]
        concrete = get_concrete_states(DebtState)
        assert config["initial"] == concrete[0].__name__

    def test_final_state_has_no_outgoing(self) -> None:
        """States with no outgoing transitions are marked as final."""
        machines = [CloseDebt]
        configs = build_xstate_config(machines)
        closed = configs["DebtState"]["states"]["ClosedDebt"]
        assert closed.get("type") == "final"

    def test_sources_have_on_dict(self) -> None:
        machines = [CloseDebt]
        configs = build_xstate_config(machines)
        active = configs["DebtState"]["states"]["ActiveDebt"]
        assert "on" in active

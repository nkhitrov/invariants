import importlib
import sys
import types

from tests.support.states import (
    ActiveDebt,
    ActiveLoan,
    ActivateLoan,
    ChangeOverdueDebtAndLoanToActive,
    ChangeOverdueDebtToActive,
    CheckDebtOverdueDays,
    CloseDebt,
    ClosedDebt,
    ClosedLoan,
    CloseLoan,
    DebtState,
    LoanState,
    MakeDebtOverdue,
    MakeLoanOverdue,
    OverdueDebt,
    OverdueLoan,
)

from invariants.state import State, StateMachine
from invariants.viz.xstate import (
    NestingRelation,
    Transition,
    _build_on_dict,
    _collect_guard_info,
    _compound_guard_name,
    _find_machines_in_module,
    _get_imported_modules,
    _is_state_subclass,
    _render_guard,
    _render_state_config,
    _render_transition_object,
    _unpack_union,
    attach_guards,
    build_xstate_config,
    detect_all_nestings,
    detect_nesting,
    discover_machines,
    extract_guard_name,
    extract_transitions,
    find_state_root,
    get_concrete_states,
    get_root_state,
    render_xstate_code,
    unwrap_state_types,
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


class TestDiscoverMachines:
    def test_discovers_from_support(self) -> None:
        module = importlib.import_module("tests.support.states")
        machines = discover_machines(module)
        names = {m.__name__ for m in machines}
        assert names == {
            "CreateDebt",
            "MakeDebtOverdue",
            "ChangeOverdueDebtToActive",
            "CloseDebt",
            "CheckDebtOverdueDays",
            "ChangeOverdueDebtAndLoanToActive",
            "MakeLoanOverdue",
            "CloseLoan",
            "ActivateLoan",
        }


class TestUnwrapStateTypes:
    def test_plain_state(self) -> None:
        assert unwrap_state_types(ActiveLoan) == {ActiveLoan}

    def test_union(self) -> None:
        from typing import Union
        assert unwrap_state_types(Union[ActiveLoan, ClosedLoan]) == {ActiveLoan, ClosedLoan}

    def test_tuple_with_ellipsis(self) -> None:
        assert unwrap_state_types(tuple[ActiveLoan | ClosedLoan, ...]) == {ActiveLoan, ClosedLoan}

    def test_annotated_tuple_union(self) -> None:
        from typing import Annotated
        from invariants.conditions import ContainsOne
        ann = Annotated[tuple[ActiveLoan | ClosedLoan, ...], ContainsOne(ActiveLoan)]
        assert unwrap_state_types(ann) == {ActiveLoan, ClosedLoan}

    def test_non_state(self) -> None:
        assert unwrap_state_types(int) == set()


class TestFindStateRoot:
    def test_loan_states(self) -> None:
        assert find_state_root({ActiveLoan, ClosedLoan}) is LoanState

    def test_debt_states(self) -> None:
        assert find_state_root({ActiveDebt}) is DebtState

    def test_empty(self) -> None:
        assert find_state_root(set()) is None

    def test_mixed_hierarchies_returns_none(self) -> None:
        """States from different roots should return None."""
        assert find_state_root({ActiveDebt, ActiveLoan}) is None

    def test_state_base_class_returns_none(self) -> None:
        """State class itself has no hierarchy root — _get_root returns None.
        Ensures len(roots)==1 check isn't replaced with <=1 (empty set would crash)."""
        assert find_state_root({State}) is None


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


class TestExtractGuardName:
    def test_contains_one_and_union(self) -> None:
        """ActiveDebt has ContainsOne(ActiveLoan) + union -> compound guard."""
        guard = extract_guard_name(ActiveDebt, "loans")
        assert guard == {"type": "and", "guards": ["anyActiveLoan", "onlyActiveLoanOrClosedLoan"]}

    def test_single_type(self) -> None:
        """ClosedDebt has tuple[ClosedLoan, ...] -> only guard."""
        guard = extract_guard_name(ClosedDebt, "loans")
        assert guard == "onlyClosedLoan"

    def test_contains_one_priority(self) -> None:
        """OverdueDebt has ContainsOne(OverdueLoan) + union -> compound guard."""
        guard = extract_guard_name(OverdueDebt, "loans")
        assert guard == {"type": "and", "guards": ["anyOverdueLoan", "onlyOverdueLoanOrActiveLoanOrClosedLoan"]}

    def test_no_nested_field(self) -> None:
        assert extract_guard_name(ActiveDebt, "nonexistent") is None


class TestAttachGuards:
    def test_no_nesting_keeps_transitions(self) -> None:
        """Transitions without matching nestings pass through unchanged."""
        transitions = [
            Transition(source=ActiveLoan, target=ClosedLoan, event="CloseLoan"),
        ]
        result = attach_guards(transitions, [])
        assert result == transitions
        assert result[0].guard is None


class TestDiscoverMachinesCrossModule:
    def test_discovers_machines_from_imported_modules(self) -> None:
        """When local states reference external state hierarchies,
        machines from imported modules are also discovered via 'from X import Y' path."""
        # Create a module with debt machines that has State classes from another module
        debt_mod = types.ModuleType("_test_debt_mod")
        debt_mod.__name__ = "_test_debt_mod"

        class DebtCloseDebt(StateMachine[DebtState]):
            def execute(self, debt: ActiveDebt) -> ClosedDebt: ...

        DebtCloseDebt.__module__ = "_test_debt_mod"
        debt_mod.DebtCloseDebt = DebtCloseDebt  # type: ignore[attr-defined]
        # Simulate 'import some_module' (direct module import)
        dummy_mod = types.ModuleType("_test_dummy_mod")
        debt_mod._test_dummy_mod = dummy_mod  # type: ignore[attr-defined]
        # Simulate 'from tests.support.states import ActiveLoan'
        # This triggers the 'from X import Y' scanning path in _get_imported_modules
        debt_mod.ActiveLoan = ActiveLoan  # type: ignore[attr-defined]
        sys.modules["_test_debt_mod"] = debt_mod

        try:
            machines = discover_machines(debt_mod)
            names = {m.__name__ for m in machines}
            # Local debt machine is found
            assert "DebtCloseDebt" in names
            # Loan machines discovered from tests.support.states via ActiveLoan import
            assert "MakeLoanOverdue" in names
            assert "CloseLoan" in names
        finally:
            del sys.modules["_test_debt_mod"]


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


class TestRenderXstateCode:
    def test_generates_create_machine(self) -> None:
        machines = [CloseDebt, ChangeOverdueDebtToActive]
        code = render_xstate_code(machines)
        assert "import { createMachine } from 'xstate';" in code
        # No guards -> plain createMachine, no setup
        assert "const debtState = createMachine({" in code
        assert "id: 'DebtState'," in code
        assert "initial: 'ActiveDebt'," in code

    def test_contains_states_and_transitions(self) -> None:
        machines = [CloseDebt, ChangeOverdueDebtToActive]
        code = render_xstate_code(machines)
        assert "ActiveDebt: {" in code
        assert "ClosedDebt: {" in code
        assert "OverdueDebt: {" in code
        assert "CloseDebt: 'ClosedDebt'," in code
        assert "ChangeOverdueDebtToActive: 'ActiveDebt'," in code

    def test_final_states(self) -> None:
        machines = [CloseDebt]
        code = render_xstate_code(machines)
        assert "type: 'final'," in code


class TestRenderXstateCodeWithGuards:
    def test_guard_in_output(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        code = render_xstate_code(machines)
        assert "guard: 'onlyClosedLoan'" in code
        assert "guard: 'anyOverdueLoanAndonlyOverdueLoanOrActiveLoanOrClosedLoan'" in code
        # Compound guard defined in setup using and()
        assert "anyOverdueLoanAndonlyOverdueLoanOrActiveLoanOrClosedLoan: and(['anyOverdueLoan', 'onlyOverdueLoanOrActiveLoanOrClosedLoan'])" in code

    def test_setup_with_guards(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        code = render_xstate_code(machines)
        # Debt machine uses setup() because it has guards
        assert "import { setup, createMachine, and } from 'xstate';" in code
        assert "setup({" in code
        assert "guards: {" in code
        assert "onlyClosedLoan: () => true," in code
        assert "}).createMachine({" in code

    def test_no_setup_without_guards(self) -> None:
        """Loan machine has no guards, so it uses plain createMachine."""
        machines = [MakeLoanOverdue, CloseLoan, ActivateLoan]
        code = render_xstate_code(machines)
        assert "import { createMachine } from 'xstate';" in code
        assert "setup(" not in code

    def test_simple_guards_only_uses_setup(self) -> None:
        """Config with only simple guards (no compound) should still use setup().

        Kills or→and mutation on `if guard_names or compound_guards`.
        """
        # CloseDebt targets ClosedDebt which has only simple guard "onlyClosedLoan"
        # By using only CloseDebt (no MakeDebtOverdue which creates compound guards),
        # we get a config with only simple_guard_names and empty compound_guards.
        machines = [CloseDebt, CloseLoan, ActivateLoan, MakeLoanOverdue]
        code = render_xstate_code(machines)
        # DebtState should use setup() because it has simple guards
        assert "setup({" in code
        assert "onlyClosedLoan: () => true," in code
        assert "}).createMachine({" in code

    def test_no_nested_states_in_output(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        code = render_xstate_code(machines)
        assert "#DebtState" not in code

    def test_both_machines_in_output(self) -> None:
        machines = [CloseDebt, MakeDebtOverdue, ChangeOverdueDebtToActive,
                    MakeLoanOverdue, CloseLoan, ActivateLoan]
        code = render_xstate_code(machines)
        assert "id: 'DebtState'," in code
        assert "id: 'LoanState'," in code
        # Loan machine has simple transitions, no setup()
        assert "ActivateLoan: 'ActiveLoan'," in code


class TestUnpackUnion:
    def test_plain_type_returns_list(self) -> None:
        assert _unpack_union(int) == [int]

    def test_union_unpacks(self) -> None:
        from typing import Union
        result = _unpack_union(Union[int, str])
        assert set(result) == {int, str}

    def test_pipe_union_unpacks(self) -> None:
        result = _unpack_union(int | str)
        assert set(result) == {int, str}


class TestIsStateSubclass:
    def test_state_subclass(self) -> None:
        assert _is_state_subclass(ActiveLoan) is True

    def test_non_type(self) -> None:
        assert _is_state_subclass("not a type") is False

    def test_non_state_type(self) -> None:
        assert _is_state_subclass(int) is False


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


class TestFindMachinesInModule:
    def test_finds_machines(self) -> None:
        module = importlib.import_module("tests.support.states")
        machines = _find_machines_in_module(module)
        names = {m.__name__ for m in machines}
        assert "CloseLoan" in names
        assert "CloseDebt" in names

    def test_excludes_base_class(self) -> None:
        module = importlib.import_module("tests.support.states")
        machines = _find_machines_in_module(module)
        assert StateMachine not in machines

    def test_excludes_machines_from_other_modules(self) -> None:
        """Machines defined in a different module should not be included."""
        mod = types.ModuleType("_test_filt")
        mod.__name__ = "_test_filt"

        class Foreign(StateMachine[LoanState]):
            def execute(self, loan: ActiveLoan) -> ClosedLoan: ...

        Foreign.__module__ = "other_module"
        mod.Foreign = Foreign  # type: ignore[attr-defined]
        sys.modules["_test_filt"] = mod
        try:
            machines = _find_machines_in_module(mod)
            assert len(machines) == 0
        finally:
            del sys.modules["_test_filt"]


class TestGetImportedModules:
    def test_finds_imported_state_modules(self) -> None:
        """Module that imports State classes from another module finds that module."""
        mod = types.ModuleType("_test_mod")
        mod.__name__ = "_test_mod"
        mod.ActiveLoan = ActiveLoan  # type: ignore[attr-defined]
        sys.modules["_test_mod"] = mod
        try:
            result = _get_imported_modules(mod)
            module_names = [m.__name__ for m in result]
            assert "tests.support.states" in module_names
        finally:
            del sys.modules["_test_mod"]

    def test_finds_direct_module_imports(self) -> None:
        """Module-type attributes (import X) are found by the first scan loop."""
        mod = types.ModuleType("_test_direct")
        mod.__name__ = "_test_direct"
        imported = types.ModuleType("_test_imported")
        imported.__name__ = "_test_imported"
        mod._test_imported = imported  # type: ignore[attr-defined]
        sys.modules["_test_direct"] = mod
        sys.modules["_test_imported"] = imported
        try:
            result = _get_imported_modules(mod)
            assert imported in result
        finally:
            del sys.modules["_test_direct"]
            del sys.modules["_test_imported"]


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


class TestRenderGuard:
    def test_simple_guard(self) -> None:
        assert _render_guard("myGuard") == "'myGuard'"

    def test_compound_guard(self) -> None:
        guard = {"type": "and", "guards": ["a", "b"]}
        assert _render_guard(guard) == "'aAndb'"


class TestCompoundGuardName:
    def test_joins_with_and(self) -> None:
        assert _compound_guard_name({"guards": ["foo", "bar"]}) == "fooAndbar"


class TestRenderTransitionObject:
    def test_with_guard(self) -> None:
        result = _render_transition_object({"target": "X", "guard": "g"})
        assert result == "{ target: 'X', guard: 'g' }"

    def test_without_guard(self) -> None:
        result = _render_transition_object({"target": "X"})
        assert result == "{ target: 'X' }"


class TestRenderStateConfig:
    def test_final_state(self) -> None:
        result = _render_state_config("ClosedLoan", {"type": "final"}, indent=2)
        assert "type: 'final'," in result
        assert "ClosedLoan: {" in result

    def test_state_with_on(self) -> None:
        config = {"on": {"Close": "ClosedLoan"}}
        result = _render_state_config("ActiveLoan", config, indent=2)
        assert "ActiveLoan: {" in result
        assert "on: {" in result
        assert "Close: 'ClosedLoan'," in result

    def test_indentation(self) -> None:
        result = _render_state_config("X", {"type": "final"}, indent=0)
        lines = result.split("\n")
        assert lines[0] == "X: {"
        assert lines[1] == "  type: 'final',"
        assert lines[2] == "},"

    def test_list_of_guarded_transitions(self) -> None:
        config = {"on": {"Ev": [{"target": "A", "guard": "g1"}]}}
        result = _render_state_config("S", config, indent=1)
        assert "{ target: 'A', guard: 'g1' }" in result


class TestCollectGuardInfo:
    def test_no_guards(self) -> None:
        config = {"states": {"A": {"on": {"Ev": "B"}}}}
        names, compound, fns = _collect_guard_info(config)
        assert names == set()
        assert compound == {}
        assert fns == set()

    def test_simple_guard(self) -> None:
        config = {"states": {"A": {"on": {"Ev": [{"target": "B", "guard": "myGuard"}]}}}}
        names, compound, fns = _collect_guard_info(config)
        assert "myGuard" in names

    def test_compound_guard(self) -> None:
        guard = {"type": "and", "guards": ["a", "b"]}
        config = {"states": {"A": {"on": {"Ev": [{"target": "B", "guard": guard}]}}}}
        names, compound, fns = _collect_guard_info(config)
        assert "a" in names
        assert "b" in names
        assert "aAndb" in compound
        assert "and" in fns

    def test_non_list_target_with_guard(self) -> None:
        config = {"states": {"A": {"on": {"Ev": {"target": "B", "guard": "g"}}}}}
        names, compound, fns = _collect_guard_info(config)
        assert "g" in names

    def test_dict_without_type_is_not_compound(self) -> None:
        """A guard dict without 'type' key should not be treated as compound."""
        config = {"states": {"A": {"on": {"Ev": [{"target": "B", "guard": {"unknown": "val"}}]}}}}
        names, compound, fns = _collect_guard_info(config)
        assert compound == {}
        assert fns == set()

    def test_string_target_not_treated_as_guard(self) -> None:
        """Plain string targets should not be processed as guard items."""
        config = {"states": {"A": {"on": {"Ev": "B"}, "type": "not_final"}}}
        names, compound, fns = _collect_guard_info(config)
        assert names == set()


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


class TestRenderXstateCodeExactFormat:
    def test_loan_machine_exact_structure(self) -> None:
        """Verify the exact structure of generated code, not just substrings."""
        machines = [MakeLoanOverdue, CloseLoan, ActivateLoan]
        code = render_xstate_code(machines)

        # Verify import line
        lines = code.split("\n")
        assert lines[0] == "import { createMachine } from 'xstate';"
        assert lines[1] == ""

        # Verify machine definition starts correctly
        assert "const loanState = createMachine({" in code
        assert "  id: 'LoanState'," in code
        assert "  initial: 'ActiveLoan'," in code
        assert "  states: {" in code

        # Verify states are present with proper indentation
        assert "    ActiveLoan: {" in code
        assert "    ClosedLoan: {" in code
        assert "    OverdueLoan: {" in code

        # Verify transitions
        assert "      on: {" in code

        # Verify closing
        assert "});" in code

    def test_empty_machines_list(self) -> None:
        code = render_xstate_code([])
        assert code.strip() == "import { createMachine } from 'xstate';"

    def test_var_name_lowercase_first_char(self) -> None:
        machines = [CloseDebt]
        code = render_xstate_code(machines)
        assert "const debtState = " in code


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


class TestDiscoverMachinesEdgeCases:
    def test_no_referenced_roots_returns_local_only(self) -> None:
        """When local machines don't reference external state hierarchies,
        only local machines are returned."""
        mod = types.ModuleType("_test_isolated")
        mod.__name__ = "_test_isolated"

        class LocalMachine(StateMachine[LoanState]):
            def execute(self, loan: ActiveLoan) -> ClosedLoan: ...

        LocalMachine.__module__ = "_test_isolated"
        mod.LocalMachine = LocalMachine  # type: ignore[attr-defined]
        sys.modules["_test_isolated"] = mod
        try:
            machines = discover_machines(mod)
            assert len(machines) == 1
            assert machines[0].__name__ == "LocalMachine"
        finally:
            del sys.modules["_test_isolated"]


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

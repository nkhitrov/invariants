from invariants.viz.xstate import (
    _render_state_config,
    _render_transition_object,
    render_xstate_code,
)
from tests.support.states import (
    ActivateLoan,
    ChangeOverdueDebtToActive,
    CloseDebt,
    CloseLoan,
    MakeDebtOverdue,
    MakeLoanOverdue,
)


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

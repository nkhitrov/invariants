import importlib
import sys
import types

from invariants.state import StateMachine
from invariants.viz.xstate import (
    _find_machines_in_module,
    _get_imported_modules,
    discover_machines,
)
from tests.support.states import (
    ActiveDebt,
    ActiveLoan,
    ClosedDebt,
    ClosedLoan,
    DebtState,
    LoanState,
)


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

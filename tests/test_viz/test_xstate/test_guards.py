from invariants.viz.xstate import (
    _collect_guard_info,
    _render_guard,
    extract_guard_name,
)
from tests.support.states import ActiveDebt, ClosedDebt, OverdueDebt


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


class TestRenderGuard:
    def test_simple_guard(self) -> None:
        assert _render_guard("myGuard") == "'myGuard'"

    def test_compound_guard_is_inlined(self) -> None:
        """Compound guards use the xstate combinator inline, referencing named leaves."""
        guard = {"type": "and", "guards": ["a", "b"]}
        assert _render_guard(guard) == "and(['a', 'b'])"

    def test_nested_compound_guard(self) -> None:
        guard = {"type": "or", "guards": ["a", {"type": "and", "guards": ["b", "c"]}]}
        assert _render_guard(guard) == "or(['a', and(['b', 'c'])])"


class TestCollectGuardInfo:
    def test_no_guards(self) -> None:
        config = {"states": {"A": {"on": {"Ev": "B"}}}}
        names, fns = _collect_guard_info(config)
        assert names == set()
        assert fns == set()

    def test_simple_guard(self) -> None:
        config = {"states": {"A": {"on": {"Ev": [{"target": "B", "guard": "myGuard"}]}}}}
        names, fns = _collect_guard_info(config)
        assert names == {"myGuard"}
        assert fns == set()

    def test_compound_guard_collects_leaves_and_combinator(self) -> None:
        guard = {"type": "and", "guards": ["a", "b"]}
        config = {"states": {"A": {"on": {"Ev": [{"target": "B", "guard": guard}]}}}}
        names, fns = _collect_guard_info(config)
        assert names == {"a", "b"}
        assert fns == {"and"}

    def test_nested_compound_guard(self) -> None:
        guard = {"type": "or", "guards": ["a", {"type": "and", "guards": ["b", "c"]}]}
        config = {"states": {"A": {"on": {"Ev": [{"target": "B", "guard": guard}]}}}}
        names, fns = _collect_guard_info(config)
        assert names == {"a", "b", "c"}
        assert fns == {"and", "or"}

    def test_non_list_target_with_guard(self) -> None:
        config = {"states": {"A": {"on": {"Ev": {"target": "B", "guard": "g"}}}}}
        names, fns = _collect_guard_info(config)
        assert "g" in names

    def test_dict_without_type_is_not_compound(self) -> None:
        """A guard dict without 'type' key should not be treated as compound."""
        config = {"states": {"A": {"on": {"Ev": [{"target": "B", "guard": {"unknown": "val"}}]}}}}
        names, fns = _collect_guard_info(config)
        assert names == set()
        assert fns == set()

    def test_string_target_not_treated_as_guard(self) -> None:
        """Plain string targets should not be processed as guard items."""
        config = {"states": {"A": {"on": {"Ev": "B"}, "type": "not_final"}}}
        names, fns = _collect_guard_info(config)
        assert names == set()

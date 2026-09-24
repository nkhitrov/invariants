from invariants.state import State
from invariants.viz.xstate import (
    _is_state_subclass,
    _unpack_union,
    find_state_root,
    unwrap_state_types,
)
from tests.support.states import (
    ActiveDebt,
    ActiveLoan,
    ClosedLoan,
    DebtState,
    LoanState,
)


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

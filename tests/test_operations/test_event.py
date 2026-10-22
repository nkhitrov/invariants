from typing import TypeVar

import pytest
from pydantic import ValidationError

from examples.debt import ActiveDebt
from examples.loan import ActiveLoan, ClosedLoan, LoanBecameOverdueEvent, LoanIssuedEvent, LoanState, OverdueLoan
from invariants.operations import EdgeRegistry, Event, get_event_edge


class TestEventEdge:
    def test_edge_from_generic_arguments(self) -> None:
        assert get_event_edge(LoanBecameOverdueEvent) == (ActiveLoan, OverdueLoan)

    def test_none_source_is_creation(self) -> None:
        assert get_event_edge(LoanIssuedEvent) == (None, ActiveLoan)

    def test_payload_is_only_user_fields(self) -> None:
        assert set(LoanBecameOverdueEvent.model_fields) == {"loan_id"}

    def test_event_is_frozen(self) -> None:
        event = LoanIssuedEvent(loan_id=1)
        with pytest.raises(ValidationError):
            event.loan_id = 2

    def test_event_is_strict(self) -> None:
        with pytest.raises(ValidationError):
            LoanIssuedEvent(loan_id="1")  # type: ignore[arg-type]

    def test_unparametrized_event_has_no_edge(self) -> None:
        From = TypeVar("From")
        To = TypeVar("To")

        class GenericEvent(Event[From, To], registry=EdgeRegistry()):
            pass

        with pytest.raises(TypeError, match="must subclass Event"):
            get_event_edge(GenericEvent)


class TestEventValidation:
    def test_name_must_end_with_event(self) -> None:
        with pytest.raises(TypeError, match="must end with `Event`"):

            class LoanClosed(Event[ActiveLoan, ClosedLoan], registry=EdgeRegistry()):
                pass

    def test_loop_event_is_forbidden(self) -> None:
        with pytest.raises(TypeError, match="has no event of its own"):

            class LoanTouchedEvent(Event[ActiveLoan, ActiveLoan], registry=EdgeRegistry()):
                pass

    def test_source_must_be_concrete_state(self) -> None:
        with pytest.raises(TypeError, match="source of an event must be a concrete state"):

            class LoanClosedEvent(Event[LoanState, ClosedLoan], registry=EdgeRegistry()):
                pass

    def test_target_must_be_concrete_state(self) -> None:
        with pytest.raises(TypeError, match="target of an event must be a concrete state"):

            class LoanClosedEvent(Event[ActiveLoan, int], registry=EdgeRegistry()):
                pass

    def test_states_of_one_hierarchy(self) -> None:
        with pytest.raises(TypeError, match="different state hierarchies"):

            class LoanBecameDebtEvent(Event[ActiveLoan, ActiveDebt], registry=EdgeRegistry()):
                pass

    def test_edge_has_one_event(self) -> None:
        registry = EdgeRegistry()

        class LoanClosedEvent(Event[ActiveLoan, ClosedLoan], registry=registry):
            pass

        with pytest.raises(TypeError, match="already taken by event LoanClosedEvent"):

            class LoanPaidEvent(Event[ActiveLoan, ClosedLoan], registry=registry):
                pass

    def test_registries_are_isolated(self) -> None:
        first, second = EdgeRegistry(), EdgeRegistry()

        class LoanClosedEvent(Event[ActiveLoan, ClosedLoan], registry=first):
            pass

        class LoanPaidEvent(Event[ActiveLoan, ClosedLoan], registry=second):
            pass

        assert first.get_event((ActiveLoan, ClosedLoan)) is LoanClosedEvent
        assert second.get_event((ActiveLoan, ClosedLoan)) is LoanPaidEvent

    def test_generic_base_carries_registry(self) -> None:
        registry = EdgeRegistry()
        From = TypeVar("From")
        To = TypeVar("To")

        class LoanEvent(Event[From, To], registry=registry):
            pass

        class LoanClosedEvent(LoanEvent[ActiveLoan, ClosedLoan]):
            pass

        assert registry.get_event((ActiveLoan, ClosedLoan)) is LoanClosedEvent

    def test_default_registry_holds_example_edges(self) -> None:
        assert Event.__registry__.get_event((ActiveLoan, OverdueLoan)) is LoanBecameOverdueEvent

    def test_clear(self) -> None:
        registry = EdgeRegistry()

        class LoanClosedEvent(Event[ActiveLoan, ClosedLoan], registry=registry):
            pass

        registry.clear()
        assert registry.get_event((ActiveLoan, ClosedLoan)) is None

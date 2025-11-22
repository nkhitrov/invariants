from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError


from invariants.state import State, Statefull, is_root_state, is_root_child, is_base_state
from tests.support.states import ActivateLoan, ActiveLoan, OverdueLoan, LoanState


class PaymentState(State):
    # value objects
    id: int
    amount: Decimal
    # state objects
    status: Statefull
    acquiring_id: Statefull
    reason: Statefull


class TestStateErrors:
    def test_base_abstract_state_cannot_be_allocated(self) -> None:
        with pytest.raises(TypeError) as excinfo:
            PaymentState()

        assert str(excinfo.value) == (
            "State with Statefull fields cannot be allocated. "
            "Override all Statefull fields in a child state."
        )

    def test_typing_any_fields_must_be_overriden(self) -> None:
        with pytest.raises(TypeError) as excinfo:

            class Payment(PaymentState): ...

        assert str(excinfo.value) == (
            "Fields `status`, `acquiring_id`, `reason` with type `Statefull` must be overridden "
            "with narrowing types for state `Payment`"
        )

    def test_not_allowed_fields_that_not_declared_in_base_state(self) -> None:
        with pytest.raises(TypeError) as excinfo:

            class Payment(PaymentState):
                status: str
                acquiring_id: str
                reason: str
                new_field1: int
                new_field2: int

        assert str(excinfo.value) == (
            "Unknown fields `new_field1`, `new_field2` in state Payment. Allowed fields from base state only"
        )

    def test_instance_state_is_immutable(self) -> None:
        class Payment(PaymentState):
            status: str
            acquiring_id: str
            reason: str

        payment = Payment(
            id=1, amount=Decimal(0), status="ok", acquiring_id="test", reason="test"
        )
        with pytest.raises(ValidationError) as excinfo:
            payment.status = "error"

        assert str(excinfo.value) == (
            "1 validation error for Payment\n"
            "status\n"
            "  Instance is frozen [type=frozen_instance, input_value='error', "
            "input_type=str]\n"
            "    For further information visit "
            "https://errors.pydantic.dev/2.12/v/frozen_instance"
        )

    def test_use_strict_typing(self) -> None:
        class Payment(PaymentState):
            status: str
            acquiring_id: str
            reason: str

        with pytest.raises(ValidationError) as excinfo:
            Payment(id=1, amount=10, status="ok", acquiring_id="test", reason="test")

        assert str(excinfo.value) == (
            "1 validation error for Payment\n"
            "amount\n"
            "  Input should be an instance of Decimal [type=is_instance_of, "
            "input_value=10, input_type=int]\n"
            "    For further information visit "
            "https://errors.pydantic.dev/2.12/v/is_instance_of"
        )


class TestStateHierarchyChecks:
    def test_is_root_state(self) -> None:
        # State.__bases__ == (BaseModel,) so it IS considered root
        assert is_root_state(State) is True
        # LoanState.__bases__ == (State,), not (BaseModel,)
        assert is_root_state(LoanState) is False
        assert is_root_state(ActiveLoan) is False

    def test_is_root_child(self) -> None:
        assert is_root_child(LoanState) is True
        assert is_root_child(ActiveLoan) is False
        assert is_root_child(State) is False

    def test_is_base_state(self) -> None:
        assert is_base_state(ActiveLoan) is True
        assert is_base_state(LoanState) is False
        assert is_base_state(State) is False


class TestStatefullFields:
    def test_has_statefull_fields_true(self) -> None:
        assert PaymentState.has_statefull_fields() is True

    def test_has_statefull_fields_false(self) -> None:
        class ConcretePayment(PaymentState):
            status: str
            acquiring_id: str
            reason: str

        assert ConcretePayment.has_statefull_fields() is False

    def test_valid_child_class_can_be_created(self) -> None:
        """Ensure a properly overridden child doesn't raise during class definition.

        This catches and→or mutations in _validate_typing_any_override:
        with `or` instead of `and`, the check would incorrectly flag
        fields that ARE properly overridden.
        """
        class ValidPayment(PaymentState):
            status: str
            acquiring_id: str
            reason: str

        payment = ValidPayment(
            id=1, amount=Decimal(0), status="ok", acquiring_id="test", reason="test"
        )
        assert payment.status == "ok"

    def test_partial_override_raises(self) -> None:
        """Child that overrides only some Statefull fields should fail."""
        with pytest.raises(TypeError) as excinfo:
            class PartialPayment(PaymentState):
                status: str

        assert "acquiring_id" in str(excinfo.value)
        assert "reason" in str(excinfo.value)
        assert "status" not in str(excinfo.value)


class TestStateMachineExecute:
    def test_activate_loan_transitions_overdue_to_active(self) -> None:
        overdue = OverdueLoan(id=1, postponement_date=datetime(2024, 6, 1))
        result = ActivateLoan().execute(overdue)
        assert isinstance(result, ActiveLoan)
        assert result.id == 1
        assert result.postponement_date == datetime(2024, 6, 1)

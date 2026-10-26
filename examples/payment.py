from datetime import date
from decimal import Decimal
from typing import Literal

from invariants.operations import Event, Operation, Transition
from invariants.state import State, Statefull


class PaymentState(State):
    """A payment towards a loan. It is a nested entity of the loan."""

    id: int
    amount: Decimal
    paid_at: date
    status: Statefull


class ReceivedPayment(PaymentState):
    status: Literal["received"] = "received"


class PaymentReceivedEvent(Event[None, ReceivedPayment]):
    payment_id: int


class ReceivePaymentOperation(Operation[PaymentState]):
    """Register a received payment."""

    def execute(
        self, *, payment_id: int, amount: Decimal, paid_at: date
    ) -> Transition[ReceivedPayment, PaymentReceivedEvent]:
        if amount <= 0:
            raise ValueError("A payment amount must be positive")
        payment = ReceivedPayment(id=payment_id, amount=amount, paid_at=paid_at)
        return Transition(payment, (PaymentReceivedEvent(payment_id=payment_id),))

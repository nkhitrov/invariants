from datetime import date
from decimal import Decimal

from examples.payment.events import PaymentReceivedEvent
from examples.payment.states import PaymentState, ReceivedPayment
from invariants.operations import Operation, Transition


class ReceivePaymentOperation(Operation[PaymentState]):
    """Register a received payment."""

    def execute(
        self, *, payment_id: int, amount: Decimal, paid_at: date
    ) -> Transition[ReceivedPayment, PaymentReceivedEvent]:
        if amount <= 0:
            raise ValueError("A payment amount must be positive")
        payment = ReceivedPayment(id=payment_id, amount=amount, paid_at=paid_at)
        return Transition(payment, (PaymentReceivedEvent(payment_id=payment_id),))

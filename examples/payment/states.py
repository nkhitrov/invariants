from datetime import date
from decimal import Decimal
from typing import Literal

from invariants.state import State, Statefull


class PaymentState(State):
    """A payment towards a loan. It is a nested entity of the loan."""

    id: int
    amount: Decimal
    paid_at: date
    # The restructuring loan the payment was made to, when moved to an original loan on cancellation
    transferred_from_loan_id: int | None = None
    status: Statefull


class ReceivedPayment(PaymentState):
    status: Literal["received"] = "received"

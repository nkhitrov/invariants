from examples.payment.states import ReceivedPayment
from invariants.operations import Event


class PaymentReceivedEvent(Event[None, ReceivedPayment]):
    payment_id: int

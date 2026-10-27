from examples.restructuring.states import ActiveRestructuring, ClosedRestructuring
from invariants.operations import Event


class RestructuringAppliedEvent(Event[None, ActiveRestructuring]):
    restructuring_id: int


class RestructuringClosedEvent(Event[ActiveRestructuring, ClosedRestructuring]):
    restructuring_id: int

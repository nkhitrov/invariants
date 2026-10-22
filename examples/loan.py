from datetime import datetime
from typing import Literal, overload

from invariants.operations import Event, Operation, Transition
from invariants.state import State, Statefull


class LoanState(State):
    """Loan. States: active (awaiting payment), overdue (the deadline has passed), closed (paid)."""

    id: int
    status: Statefull
    postponement_date: Statefull


class ActiveLoan(LoanState):
    status: Literal["active"] = "active"
    postponement_date: datetime


class ClosedLoan(LoanState):
    """Closed loan. It cannot change state: it stays closed forever."""

    status: Literal["closed"] = "closed"
    postponement_date: None = None


class OverdueLoan(LoanState):
    status: Literal["overdue"] = "overdue"
    postponement_date: datetime


class LoanIssuedEvent(Event[None, ActiveLoan]):
    loan_id: int


class LoanBecameOverdueEvent(Event[ActiveLoan, OverdueLoan]):
    loan_id: int


class LoanActivatedEvent(Event[OverdueLoan, ActiveLoan]):
    loan_id: int


class ActiveLoanClosedEvent(Event[ActiveLoan, ClosedLoan]):
    loan_id: int


class OverdueLoanClosedEvent(Event[OverdueLoan, ClosedLoan]):
    loan_id: int


class IssueLoanOperation(Operation[LoanState]):
    """Issue a loan: the loan starts active."""

    def execute(
        self, *, loan_id: int, postponement_date: datetime
    ) -> Transition[ActiveLoan, LoanIssuedEvent]:
        loan = ActiveLoan(id=loan_id, postponement_date=postponement_date)
        return Transition(loan, (LoanIssuedEvent(loan_id=loan_id),))


class MakeLoanOverdueOperation(Operation[LoanState]):
    """Make an active loan overdue."""

    def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
        overdue = OverdueLoan(id=loan.id, postponement_date=loan.postponement_date)
        return Transition(overdue, (LoanBecameOverdueEvent(loan_id=loan.id),))


class ActivateLoanOperation(Operation[LoanState]):
    """Return an overdue loan to the active state (when a postponement is granted)."""

    def execute(
        self, loan: OverdueLoan, *, postponement_date: datetime
    ) -> Transition[ActiveLoan, LoanActivatedEvent]:
        active = ActiveLoan(id=loan.id, postponement_date=postponement_date)
        return Transition(active, (LoanActivatedEvent(loan_id=loan.id),))


class CloseLoanOperation(Operation[LoanState]):
    """Close a loan: each source state has its own edge and its own event."""

    @overload
    def execute(self, loan: ActiveLoan) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...
    @overload
    def execute(self, loan: OverdueLoan) -> Transition[ClosedLoan, OverdueLoanClosedEvent]: ...
    def execute(
        self, loan: ActiveLoan | OverdueLoan
    ) -> Transition[ClosedLoan, ActiveLoanClosedEvent | OverdueLoanClosedEvent]:
        closed = ClosedLoan(id=loan.id)
        match loan:
            case ActiveLoan():
                return Transition(closed, (ActiveLoanClosedEvent(loan_id=loan.id),))
            case OverdueLoan():
                return Transition(closed, (OverdueLoanClosedEvent(loan_id=loan.id),))

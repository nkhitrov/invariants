from examples.loan.states import ActiveLoan, ClosedLoan, OverdueLoan
from invariants.operations import Event


class LoanIssuedEvent(Event[None, ActiveLoan]):
    loan_id: int


class LoanBecameOverdueEvent(Event[ActiveLoan, OverdueLoan]):
    loan_id: int


class LoanOverdueCancelledEvent(Event[OverdueLoan, ActiveLoan]):
    loan_id: int


class ActiveLoanClosedEvent(Event[ActiveLoan, ClosedLoan]):
    loan_id: int


class OverdueLoanClosedEvent(Event[OverdueLoan, ClosedLoan]):
    loan_id: int

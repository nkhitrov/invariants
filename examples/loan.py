from datetime import datetime
from typing import Literal, overload

from invariants.operations import Event, Operation, Transition
from invariants.state import State, Statefull


class LoanState(State):
    """Заем. Состояния: активный (ожидает оплаты), просроченный (наступил deadline), закрытый (оплачен)."""

    id: int
    status: Statefull
    postponement_date: Statefull


class ActiveLoan(LoanState):
    status: Literal["active"] = "active"
    postponement_date: datetime


class ClosedLoan(LoanState):
    """Закрытый заем. Не может изменить состояние — остается закрытым навсегда."""

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
    """Выдача займа — займ появляется активным."""

    def execute(
        self, *, loan_id: int, postponement_date: datetime
    ) -> Transition[ActiveLoan, LoanIssuedEvent]:
        loan = ActiveLoan(id=loan_id, postponement_date=postponement_date)
        return Transition(loan, (LoanIssuedEvent(loan_id=loan_id),))


class MakeLoanOverdueOperation(Operation[LoanState]):
    """Перевод активного займа в просрочку."""

    def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
        overdue = OverdueLoan(id=loan.id, postponement_date=loan.postponement_date)
        return Transition(overdue, (LoanBecameOverdueEvent(loan_id=loan.id),))


class ActivateLoanOperation(Operation[LoanState]):
    """Возврат просроченного займа в активное состояние (при получении отсрочки)."""

    def execute(
        self, loan: OverdueLoan, *, postponement_date: datetime
    ) -> Transition[ActiveLoan, LoanActivatedEvent]:
        active = ActiveLoan(id=loan.id, postponement_date=postponement_date)
        return Transition(active, (LoanActivatedEvent(loan_id=loan.id),))


class CloseLoanOperation(Operation[LoanState]):
    """Закрытие займа: у каждого исходного состояния своё ребро и своё событие."""

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

from datetime import datetime
from typing import Literal

from invariants.state import State, Statefull, StateMachine


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


class MakeLoanOverdue(StateMachine[LoanState]):
    """Перевод активного займа в просрочку."""

    def execute(self, loan: ActiveLoan) -> OverdueLoan:
        ...


class CloseLoan(StateMachine[LoanState]):
    """Закрытие займа."""

    def execute(self, loan: ActiveLoan | OverdueLoan) -> ClosedLoan:
        ...


class ActivateLoan(StateMachine[LoanState]):
    """Возврат просроченного займа в активное состояние (при получении отсрочки)."""

    def execute(self, loan: OverdueLoan) -> ActiveLoan:
        return ActiveLoan(id=loan.id, postponement_date=loan.postponement_date)

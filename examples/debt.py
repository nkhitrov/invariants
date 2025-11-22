from datetime import datetime
from typing import Annotated, Literal

from invariants.conditions import ContainsOne
from invariants.state import State, Statefull, StateMachine

from examples.loan import ActiveLoan, ClosedLoan, OverdueLoan


class DebtState(State):
    """Долг. Состояния аналогичны займу, но определяются состояниями входящих в него займов."""

    status: Statefull
    loans: Statefull


class ActiveDebt(DebtState):
    """Активный долг — все займы активны или закрыты, но хотя бы один активен."""

    status: Literal["active"] = "active"
    loans: Annotated[tuple[ActiveLoan | ClosedLoan, ...], ContainsOne(ActiveLoan)]


class ClosedDebt(DebtState):
    """Закрытый долг — все займы закрыты."""

    status: Literal["closed"] = "closed"
    loans: tuple[ClosedLoan, ...]


class OverdueDebt(DebtState):
    """Просроченный долг — хотя бы один заем просрочен."""

    status: Literal["overdue"] = "overdue"
    loans: Annotated[
        tuple[OverdueLoan | ActiveLoan | ClosedLoan, ...], ContainsOne(OverdueLoan)
    ]

Debt = ActiveDebt | ClosedDebt | OverdueDebt


class CreateDebt(StateMachine[DebtState]):
    """Создание нового долга — всегда начинается как активный."""

    def execute(self, loan_id: int, postponement_date: datetime) -> ActiveDebt:
        ...

class MakeDebtOverdue(StateMachine[DebtState]):
    """Перевод активного долга в просрочку — один из займов становится просроченным."""

    def execute(self, debt: ActiveDebt, overdue_loan_id: int) -> OverdueDebt:
        ...


class ChangeOverdueDebtToActive(StateMachine[DebtState]):
    """Перевод просроченного долга обратно в активный — все просроченные займы становятся активными."""

    def execute(self, debt: OverdueDebt) -> ActiveDebt:
      ...

class CloseDebt(StateMachine[DebtState]):
    """Закрытие долга — все займы закрываются."""

    def execute(self, debt: ActiveDebt | OverdueDebt) -> ClosedDebt:
     ...


class CheckDebtOverdueDays(StateMachine[DebtState]):
    """Подсчёт дней просрочки по первому просроченному займу."""

    def execute(self, debt: OverdueDebt) -> int:
        ...

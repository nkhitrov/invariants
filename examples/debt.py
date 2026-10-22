from datetime import datetime
from typing import Annotated, Literal, overload

from invariants.conditions import ContainsOne
from invariants.operations import Event, Operation, Query, Transition
from invariants.state import State, Statefull

from examples.loan import (
    ActivateLoanOperation,
    ActiveLoan,
    ActiveLoanClosedEvent,
    CloseLoanOperation,
    ClosedLoan,
    IssueLoanOperation,
    LoanActivatedEvent,
    LoanBecameOverdueEvent,
    LoanIssuedEvent,
    MakeLoanOverdueOperation,
    OverdueLoan,
    OverdueLoanClosedEvent,
)


class DebtState(State):
    """Долг. Состояния аналогичны займу, но определяются состояниями входящих в него займов."""

    id: int
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


class LoanNotFoundError(LookupError):
    def __init__(self, loan_id: int) -> None:
        super().__init__(f"Loan {loan_id} is not found in a state the operation expects")
        self.loan_id = loan_id


class DebtCreatedEvent(Event[None, ActiveDebt]):
    debt_id: int


class DebtBecameOverdueEvent(Event[ActiveDebt, OverdueDebt]):
    debt_id: int
    overdue_loan_id: int


class DebtBecameActiveEvent(Event[OverdueDebt, ActiveDebt]):
    debt_id: int


class ActiveDebtClosedEvent(Event[ActiveDebt, ClosedDebt]):
    debt_id: int


class OverdueDebtClosedEvent(Event[OverdueDebt, ClosedDebt]):
    debt_id: int


class CreateDebtOperation(Operation[DebtState]):
    """Создание нового долга — всегда начинается как активный, с одним выданным займом."""

    issue_loan: IssueLoanOperation

    def execute(
        self, *, debt_id: int, loan_id: int, postponement_date: datetime
    ) -> Transition[ActiveDebt, DebtCreatedEvent | LoanIssuedEvent]:
        loan, loan_events = self.issue_loan.execute(loan_id=loan_id, postponement_date=postponement_date)
        debt = ActiveDebt(id=debt_id, loans=(loan,))
        return Transition(debt, (DebtCreatedEvent(debt_id=debt_id), *loan_events))


class AddLoanToDebtOperation(Operation[DebtState]):
    """Новый займ в активном долге: инвариант долга сохранился, события долга нет (петля)."""

    issue_loan: IssueLoanOperation

    def execute(
        self, debt: ActiveDebt, *, loan_id: int, postponement_date: datetime
    ) -> Transition[ActiveDebt, LoanIssuedEvent]:
        loan, loan_events = self.issue_loan.execute(loan_id=loan_id, postponement_date=postponement_date)
        new_debt = ActiveDebt(id=debt.id, loans=(*debt.loans, loan))
        return Transition(new_debt, loan_events)


class MakeDebtOverdueOperation(Operation[DebtState]):
    """Перевод активного долга в просрочку — один из займов становится просроченным."""

    make_loan_overdue: MakeLoanOverdueOperation

    def execute(
        self, debt: ActiveDebt, *, loan_id: int
    ) -> Transition[OverdueDebt, DebtBecameOverdueEvent | LoanBecameOverdueEvent]:
        loans: list[OverdueLoan | ActiveLoan | ClosedLoan] = []
        loan_events: list[LoanBecameOverdueEvent] = []
        for loan in debt.loans:
            match loan:
                case ActiveLoan(id=id_) if id_ == loan_id:
                    overdue, events = self.make_loan_overdue.execute(loan)
                    loans.append(overdue)
                    loan_events.extend(events)
                case _:
                    loans.append(loan)
        if not loan_events:
            raise LoanNotFoundError(loan_id)

        new_debt = OverdueDebt(id=debt.id, loans=tuple(loans))
        return Transition(
            new_debt,
            (DebtBecameOverdueEvent(debt_id=debt.id, overdue_loan_id=loan_id), *loan_events),
        )


class ActivateDebtLoanOperation(Operation[DebtState]):
    """Отсрочка по просроченному займу: долг становится активным, если просроченных займов не осталось."""

    activate_loan: ActivateLoanOperation

    def execute(self, debt: OverdueDebt, *, loan_id: int, postponement_date: datetime) -> (
        Transition[ActiveDebt, DebtBecameActiveEvent | LoanActivatedEvent]
        | Transition[OverdueDebt, LoanActivatedEvent]
    ):
        loans: list[OverdueLoan | ActiveLoan | ClosedLoan] = []
        loan_events: list[LoanActivatedEvent] = []
        for loan in debt.loans:
            match loan:
                case OverdueLoan(id=id_) if id_ == loan_id:
                    active, events = self.activate_loan.execute(loan, postponement_date=postponement_date)
                    loans.append(active)
                    loan_events.extend(events)
                case _:
                    loans.append(loan)
        if not loan_events:
            raise LoanNotFoundError(loan_id)

        if any(isinstance(loan, OverdueLoan) for loan in loans):
            return Transition(OverdueDebt(id=debt.id, loans=tuple(loans)), tuple(loan_events))

        active_loans = tuple(loan for loan in loans if not isinstance(loan, OverdueLoan))
        # A union of transitions gives mypy no single context to infer the events from
        activated: Transition[ActiveDebt, DebtBecameActiveEvent | LoanActivatedEvent] = Transition(
            ActiveDebt(id=debt.id, loans=active_loans),
            (DebtBecameActiveEvent(debt_id=debt.id), *loan_events),
        )
        return activated


class CloseDebtOperation(Operation[DebtState]):
    """Закрытие долга — все незакрытые займы закрываются."""

    close_loan: CloseLoanOperation

    @overload
    def execute(
        self, debt: ActiveDebt
    ) -> Transition[ClosedDebt, ActiveDebtClosedEvent | ActiveLoanClosedEvent]: ...
    @overload
    def execute(
        self, debt: OverdueDebt
    ) -> Transition[
        ClosedDebt, OverdueDebtClosedEvent | ActiveLoanClosedEvent | OverdueLoanClosedEvent
    ]: ...
    def execute(self, debt: ActiveDebt | OverdueDebt) -> Transition[
        ClosedDebt,
        ActiveDebtClosedEvent | OverdueDebtClosedEvent | ActiveLoanClosedEvent | OverdueLoanClosedEvent,
    ]:
        loans: list[ClosedLoan] = []
        loan_events: list[ActiveLoanClosedEvent | OverdueLoanClosedEvent] = []
        for loan in debt.loans:
            match loan:
                case ActiveLoan() | OverdueLoan():
                    closed, events = self.close_loan.execute(loan)
                    loans.append(closed)
                    loan_events.extend(events)
                case ClosedLoan():
                    loans.append(loan)

        closed_debt = ClosedDebt(id=debt.id, loans=tuple(loans))
        match debt:
            case ActiveDebt():
                return Transition(closed_debt, (ActiveDebtClosedEvent(debt_id=debt.id), *loan_events))
            case OverdueDebt():
                return Transition(closed_debt, (OverdueDebtClosedEvent(debt_id=debt.id), *loan_events))


class CheckDebtOverdueDaysQuery(Query[DebtState]):
    """Подсчёт дней просрочки по первому просроченному займу."""

    def execute(self, debt: OverdueDebt, *, now: datetime) -> int:
        overdue = next(loan for loan in debt.loans if isinstance(loan, OverdueLoan))
        return (now - overdue.postponement_date).days

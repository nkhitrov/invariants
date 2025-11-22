from datetime import datetime
from typing import Literal, Annotated

from invariants.conditions import ContainsOne
from invariants.state import State, Statefull, StateMachine

### loan

class LoanState(State):
    id: int
    status: Statefull
    postponement_date: Statefull


class ActiveLoan(LoanState):
    status: Literal["active"] = "active"
    postponement_date: datetime


class ClosedLoan(LoanState):
    status: Literal["closed"] = "closed"
    postponement_date: None = None


class OverdueLoan(LoanState):
    status: Literal["overdue"] = "overdue"
    postponement_date: datetime


class MakeLoanOverdue(StateMachine[LoanState]):
    def execute(self, loan: ActiveLoan) -> OverdueLoan:
        ...


class CloseLoan(StateMachine[LoanState]):
    def execute(self, loan: ActiveLoan | OverdueLoan) -> ClosedLoan:
        ...


class ActivateLoan(StateMachine[LoanState]):
    def execute(self, loan: OverdueLoan) -> ActiveLoan:
        return ActiveLoan(id=loan.id, postponement_date=loan.postponement_date)


### debt

class DebtState(State):
    status: Statefull
    loans: Statefull


class ActiveDebt(DebtState):
    status: Literal["active"] = "active"
    loans: Annotated[tuple[ActiveLoan | ClosedLoan, ...], ContainsOne(ActiveLoan)]


class ClosedDebt(DebtState):
    status: Literal["closed"] = "closed"
    loans: tuple[ClosedLoan, ...]


class OverdueDebt(DebtState):
    status: Literal["overdue"] = "overdue"
    loans: Annotated[
        tuple[OverdueLoan | ActiveLoan | ClosedLoan, ...], ContainsOne(OverdueLoan)
    ]


class CreateDebt(StateMachine[DebtState]):
    def execute(self, loan_id: int, postponement_date: datetime) -> ActiveDebt:
        ...


class MakeDebtOverdue(StateMachine[DebtState]):
    def execute(self, debt: ActiveDebt, overdue_loan_id: int) -> OverdueDebt:
        ...


class ChangeOverdueDebtToActive(StateMachine[DebtState]):
    def execute(self, debt: OverdueDebt) -> ActiveDebt:
        ...


class CloseDebt(StateMachine[DebtState]):
    def execute(self, debt: ActiveDebt | OverdueDebt) -> ClosedDebt:
        ...


class CheckDebtOverdueDays(StateMachine[DebtState]):
    def execute(self, debt: OverdueDebt) -> int:
        ...


class ChangeOverdueDebtAndLoanToActive(StateMachine[LoanState]):
    """Cross-hierarchy machine: LoanState root but returns DebtState child."""
    def execute(self, debt: OverdueDebt) -> ActiveDebt:
        ...

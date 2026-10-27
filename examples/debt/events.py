from examples.debt.states import (
    ActiveDebt,
    ClosedDebt,
    ClosedRestructuredDebt,
    OverdueDebt,
    RestructuredDebt,
)
from invariants.operations import Event


class DebtOpenedEvent(Event[None, ActiveDebt]):
    debt_id: int


class DebtBecameOverdueEvent(Event[ActiveDebt, OverdueDebt]):
    debt_id: int


class DebtOverdueCancelledEvent(Event[OverdueDebt, ActiveDebt]):
    debt_id: int


class ActiveDebtClosedEvent(Event[ActiveDebt, ClosedDebt]):
    debt_id: int


class OverdueDebtClosedEvent(Event[OverdueDebt, ClosedDebt]):
    debt_id: int


class ActiveDebtRestructuredEvent(Event[ActiveDebt, RestructuredDebt]):
    debt_id: int
    restructuring_id: int


class OverdueDebtRestructuredEvent(Event[OverdueDebt, RestructuredDebt]):
    debt_id: int
    restructuring_id: int


class RestructuringCancelledToOverdueEvent(Event[RestructuredDebt, OverdueDebt]):
    debt_id: int
    restructuring_id: int


class RestructuringCancelledToActiveEvent(Event[RestructuredDebt, ActiveDebt]):
    debt_id: int
    restructuring_id: int


class RestructuredDebtClosedEvent(Event[RestructuredDebt, ClosedRestructuredDebt]):
    debt_id: int
    restructuring_id: int

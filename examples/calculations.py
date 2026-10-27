"""Money of a loan, computed on the fly from its schedule and payments.

States keep only facts (financed amount, schedule, payments, booking date); paid amounts,
penalties and overdue installments are derived here by pure functions. Denormalized money
belongs to read models, not to states.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol


class InstallmentFacts(Protocol):
    @property
    def postponement_date(self) -> date: ...
    @property
    def amount(self) -> Decimal: ...


class PaymentFacts(Protocol):
    @property
    def amount(self) -> Decimal: ...
    @property
    def paid_at(self) -> date: ...
    # Set for a payment moved from a cancelled restructuring: it pays installments before penalty
    @property
    def transferred_from_loan_id(self) -> int | None: ...


class LoanFacts(Protocol):
    """What the calculations need from any state of a loan."""

    @property
    def financed_amount(self) -> Decimal: ...
    @property
    def booking_date(self) -> date: ...
    @property
    def schedule(self) -> Sequence[InstallmentFacts]: ...
    @property
    def payments(self) -> Sequence[PaymentFacts]: ...


# 0.01% of the financed amount for every day a loan has an overdue installment
PENALTY_RATE_PER_DAY = Decimal("0.0001")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Allocation:
    """How payments made up to the booking date were spent: penalties first, then installments in order."""

    penalty_accrued: Decimal
    penalty_paid: Decimal
    installments_paid: tuple[Decimal, ...]
    overpaid: Decimal

    @property
    def penalty_outstanding(self) -> Decimal:
        return self.penalty_accrued - self.penalty_paid


def _days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def allocate(
    *,
    financed_amount: Decimal,
    schedule: Sequence[InstallmentFacts],
    payments: Sequence[PaymentFacts],
    booking_date: date,
) -> Allocation:
    """Replay the loan day by day up to ``booking_date``.

    A day starts with the daily penalty if an installment whose postponement date has passed
    is still unpaid; then the payments of that day pay the outstanding penalty first and the
    installments in schedule order after it. A payment transferred from a cancelled
    restructuring pays the installments first and the penalty with what is left.
    """
    paid = [ZERO] * len(schedule)
    penalty_due = penalty_accrued = penalty_paid = overpaid = ZERO
    daily_penalty = financed_amount * PENALTY_RATE_PER_DAY

    payments_by_day: dict[date, list[PaymentFacts]] = defaultdict(list)
    for payment in payments:
        if payment.paid_at <= booking_date:
            payments_by_day[payment.paid_at].append(payment)

    def pay_penalty(amount: Decimal) -> Decimal:
        nonlocal penalty_due, penalty_paid
        share = min(amount, penalty_due)
        penalty_due -= share
        penalty_paid += share
        return amount - share

    def pay_installments(amount: Decimal) -> Decimal:
        for index, installment in enumerate(schedule):
            share = min(amount, installment.amount - paid[index])
            paid[index] += share
            amount -= share
        return amount

    start = min([installment.postponement_date for installment in schedule] + list(payments_by_day))
    for day in _days(start, booking_date):
        if any(
            installment.postponement_date < day and paid[index] < installment.amount
            for index, installment in enumerate(schedule)
        ):
            penalty_due += daily_penalty
            penalty_accrued += daily_penalty

        for payment in payments_by_day.get(day, []):
            if payment.transferred_from_loan_id is None:
                overpaid += pay_installments(pay_penalty(payment.amount))
            else:
                overpaid += pay_penalty(pay_installments(payment.amount))

    return Allocation(
        penalty_accrued=penalty_accrued,
        penalty_paid=penalty_paid,
        installments_paid=tuple(paid),
        overpaid=overpaid,
    )


def allocate_loan(loan: LoanFacts, schedule: Sequence[InstallmentFacts] | None = None) -> Allocation:
    """Allocation of the loan's payments, optionally against another schedule."""
    return allocate(
        financed_amount=loan.financed_amount,
        schedule=loan.schedule if schedule is None else schedule,
        payments=loan.payments,
        booking_date=loan.booking_date,
    )


def paid_amount(loan: LoanFacts) -> Decimal:
    return sum((payment.amount for payment in loan.payments), ZERO)


def accrued_penalty(loan: LoanFacts) -> Decimal:
    return allocate_loan(loan).penalty_accrued


def outstanding_penalty(loan: LoanFacts) -> Decimal:
    return allocate_loan(loan).penalty_outstanding


def overdue_installments(
    loan: LoanFacts, schedule: Sequence[InstallmentFacts] | None = None
) -> tuple[InstallmentFacts, ...]:
    """InstallmentFactss due before the booking date and not fully paid (against ``schedule`` if given)."""
    schedule = loan.schedule if schedule is None else schedule
    allocation = allocate_loan(loan, schedule)
    return tuple(
        installment
        for installment, paid in zip(schedule, allocation.installments_paid)
        if installment.postponement_date < loan.booking_date and paid < installment.amount
    )


def outstanding_amount(loan: LoanFacts) -> Decimal:
    """What is left to pay today: unpaid installments plus unpaid penalty."""
    allocation = allocate_loan(loan)
    scheduled = sum((installment.amount for installment in loan.schedule), ZERO)
    return scheduled - sum(allocation.installments_paid, ZERO) + allocation.penalty_outstanding


def is_repaid(loan: LoanFacts) -> bool:
    return outstanding_amount(loan) == ZERO


def overdue_days(loan: LoanFacts) -> int:
    """Days since the postponement date of the first overdue installment (0 if none)."""
    overdue = overdue_installments(loan)
    if not overdue:
        return 0
    return (loan.booking_date - overdue[0].postponement_date).days

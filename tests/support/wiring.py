"""Composition root of the example operations, shared by the scenario tests."""

from examples.debt.operations import (
    ApplyRestructuringOperation,
    CancelDebtOverdueOperation,
    CancelRestructuringOperation,
    CloseDebtOperation,
    OpenDebtOperation,
    RecalculateDebtOperation,
    ReceiveDebtPaymentOperation,
)
from examples.loan.operations import (
    AccruePenaltyOperation,
    CancelLoanOverdueOperation,
    CloseLoanOperation,
    IssueLoanOperation,
    ReceiveLoanPaymentOperation,
    RecalculateLoanTermsOperation,
)
from examples.payment.operations import ReceivePaymentOperation
from examples.restructuring.operations import (
    CloseRestructuringOperation,
    OpenRestructuringOperation,
)

issue_loan = IssueLoanOperation()
recalculate_loan_terms = RecalculateLoanTermsOperation()
accrue_penalty = AccruePenaltyOperation()
receive_loan_payment = ReceiveLoanPaymentOperation(receive_payment=ReceivePaymentOperation())
cancel_loan_overdue = CancelLoanOverdueOperation()
close_loan = CloseLoanOperation()

open_debt = OpenDebtOperation(issue_loan=issue_loan)
cancel_debt_overdue = CancelDebtOverdueOperation(cancel_loan_overdue=cancel_loan_overdue)
cancel_restructuring = CancelRestructuringOperation(
    recalculate_loan_terms=recalculate_loan_terms,
    accrue_penalty=accrue_penalty,
    cancel_loan_overdue=cancel_loan_overdue,
)
recalculate_debt = RecalculateDebtOperation(
    recalculate_loan_terms=recalculate_loan_terms,
    accrue_penalty=accrue_penalty,
    cancel_restructuring=cancel_restructuring,
)
receive_debt_payment = ReceiveDebtPaymentOperation(
    receive_loan_payment=receive_loan_payment,
    cancel_loan_overdue=cancel_loan_overdue,
    cancel_debt_overdue=cancel_debt_overdue,
)
apply_restructuring = ApplyRestructuringOperation(
    open_restructuring=OpenRestructuringOperation(issue_loan=issue_loan)
)
close_debt = CloseDebtOperation(
    close_loan=close_loan, close_restructuring=CloseRestructuringOperation(close_loan=close_loan)
)

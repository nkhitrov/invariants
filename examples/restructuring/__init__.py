"""Debt restructuring: new loans that replace the original ones on agreed terms.

The terms are approved outside the invariants and come in as a value object. Every installment
of a restructuring loan names the original loan it pays off (``Installment.original_loan_id``),
so original and restructuring loans map 1:1 or N:M.
"""

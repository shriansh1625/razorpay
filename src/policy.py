"""Who may be called.

The merchant ask is "call everyone whose autopay failed." That list is unsafe.
A reason higher in the list wins, so a revoked mandate is not hidden behind a
later data-quality check, and an opt-out is not reopened by a stale consent flag.
"""

from src.models import Customer, Decision

RECOVERABLE_FAILURES = frozenset({"insufficient_balance", "temporary_auth_failure"})
SUPPORTED_LANGUAGES = frozenset({"en", "hi"})
ACTIVE_MANDATE = "active"


def decide(customer: Customer) -> Decision:
    if customer.opted_out:
        return Decision("suppress", "suppress_opted_out")
    if not customer.consent_to_call:
        return Decision("suppress", "suppress_no_consent")
    if customer.dispute_open:
        return Decision("suppress", "suppress_dispute")
    if customer.mandate_status != ACTIVE_MANDATE:
        return Decision("suppress", "suppress_mandate_not_active")
    if customer.already_recovered:
        return Decision("suppress", "suppress_already_recovered")
    if customer.amount_inr <= 0:
        return Decision("suppress", "suppress_invalid_amount")
    if customer.failure_code not in RECOVERABLE_FAILURES:
        return Decision("suppress", "suppress_not_recoverable")
    if customer.attempts_today > 0:
        return Decision("suppress", "suppress_already_attempted_today")
    if customer.language not in SUPPORTED_LANGUAGES:
        return Decision("suppress", "suppress_unsupported_language")
    return Decision("call", "eligible")

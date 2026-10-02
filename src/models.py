from dataclasses import dataclass


@dataclass(frozen=True)
class Customer:
    customer_id: str
    invoice_id: str
    name: str
    language: str
    plan_name: str
    amount_inr: int
    mandate_status: str
    failure_code: str
    consent_to_call: bool
    opted_out: bool
    dispute_open: bool
    already_recovered: bool
    attempts_today: int


@dataclass(frozen=True)
class Record:
    customer: Customer
    expected_action: str
    expected_terminal: str
    script: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str


@dataclass(frozen=True)
class CaseResult:
    customer_id: str
    invoice_id: str
    name: str
    action: str
    terminal: str
    expected_action: str
    expected_terminal: str
    contacted: bool
    replies: tuple[str, ...]
    tools: tuple[str, ...]
    events: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.action == self.expected_action and self.terminal == self.expected_terminal

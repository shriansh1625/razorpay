import re

from src.agent import converse
from src.models import CaseResult, Record
from src.policy import decide
from src.prompts import (
    DEBIT_CLAIMS,
    IMPERSONATION,
    TRANSCRIPT_BANNED,
    find_phrases,
)

_NEGATED_RETRY = re.compile(
    r"\b(?:not|never|haven'?t|hasn'?t|nahi|nahin)\s+recorded a retry\b"
)
_AUTHORIZED = frozenset({"retry_authorized", "retry_scheduled"})


def run_record(record: Record) -> CaseResult:
    customer = record.customer
    decision = decide(customer)
    prefix = f"{customer.customer_id} {customer.invoice_id}"
    if decision.action == "suppress":
        events = (f"{prefix} suppress {decision.reason}",)
        return CaseResult(
            customer_id=customer.customer_id,
            invoice_id=customer.invoice_id,
            name=customer.name,
            action="suppress",
            terminal=decision.reason,
            expected_action=record.expected_action,
            expected_terminal=record.expected_terminal,
            contacted=False,
            replies=(),
            tools=(),
            events=events,
        )
    replies, terminal, tools = converse(customer, record.script)
    events = [f"{prefix} contact opened"]
    events.extend(f"{prefix} tool {tool}" for tool in tools)
    events.append(f"{prefix} terminal {terminal}")
    return CaseResult(
        customer_id=customer.customer_id,
        invoice_id=customer.invoice_id,
        name=customer.name,
        action="call",
        terminal=terminal,
        expected_action=record.expected_action,
        expected_terminal=record.expected_terminal,
        contacted=True,
        replies=replies,
        tools=tools,
        events=tuple(events),
    )


def run_all(records: tuple[Record, ...]) -> tuple[CaseResult, ...]:
    return tuple(run_record(record) for record in records)


def wrongful_contacts(results: tuple[CaseResult, ...], records: tuple[Record, ...]) -> int:
    """A contact is wrongful when the policy, recomputed, would have suppressed it.

    This does not trust the action label on the result. A runner that dials and
    then marks the row suppressed still counts.
    """
    by_id = {record.customer.customer_id: record for record in records}
    total = 0
    for result in results:
        decision = decide(by_id[result.customer_id].customer)
        if result.contacted and decision.action != "call":
            total += 1
    return total


def authorization_rate(results: tuple[CaseResult, ...]) -> tuple[int, int]:
    eligible = sum(1 for result in results if result.action == "call")
    authorized = sum(
        1
        for result in results
        if result.action == "call" and result.terminal in {"retry_authorized", "retry_scheduled"}
    )
    return authorized, eligible


def render(results: tuple[CaseResult, ...], records: tuple[Record, ...]) -> str:
    authorized, eligible = authorization_rate(results)
    rate = 0 if eligible == 0 else authorized / eligible
    mismatches = [result for result in results if not result.ok]
    lines = [
        "Northwind autopay recovery",
        (
            f"Records: {len(results)}  Eligible: {eligible}  "
            f"Contacted: {sum(result.contacted for result in results)}  "
            f"Wrongful contacts: {wrongful_contacts(results, records)}"
        ),
        "",
    ]
    for result in results:
        mark = "ok" if result.ok else "FAIL"
        lines.append(
            f"{result.customer_id:<8} {result.name:<16} {result.action:<9} "
            f"{result.terminal:<34} {mark}"
        )
    lines.extend(
        [
            "",
            f"Retry authorizations: {authorized} / {eligible} eligible ({rate:.0%})",
            "Handoffs are not counted as recovered. This rate is not rupees collected.",
            "No money is debited by this agent.",
            "",
            "audit",
        ]
    )
    for result in results:
        lines.extend(result.events)
    if mismatches:
        lines.extend(["", f"Mismatches: {len(mismatches)}"])
    return "\n".join(lines) + "\n"


def release_clean(results: tuple[CaseResult, ...], records: tuple[Record, ...]) -> bool:
    return all(result.ok for result in results) and wrongful_contacts(results, records) == 0


class TranscriptReview:
    def __init__(
        self,
        should_have_called: bool,
        policy_terminal: str | None,
        banned: tuple[str, ...],
        debit_claims: tuple[str, ...],
        impersonation: tuple[str, ...],
        user_turns: int,
        mentioned_mandate: bool,
        outcome_conflict: bool,
    ):
        self.should_have_called = should_have_called
        self.policy_terminal = policy_terminal
        self.banned = banned
        self.debit_claims = debit_claims
        self.impersonation = impersonation
        self.user_turns = user_turns
        self.mentioned_mandate = mentioned_mandate
        self.outcome_conflict = outcome_conflict

    @property
    def harmful(self) -> bool:
        return bool(self.banned or self.debit_claims or self.impersonation or self.outcome_conflict)


def parse_turns(payload: dict) -> tuple[tuple[str, str], ...]:
    raw = payload.get("transcript") or []
    turns = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        message = item.get("message") or item.get("text") or ""
        if role in {"user", "agent"} and str(message).strip():
            turns.append((role, str(message).strip()))
    return tuple(turns)


def claims_recorded_retry(text: str) -> bool:
    folded = re.sub(r"\s+", " ", text.casefold())
    folded = _NEGATED_RETRY.sub(" ", folded)
    return "recorded a retry" in folded or "retry note ho chuka" in folded


def review_transcript(record: Record, turns: tuple[tuple[str, str], ...]) -> TranscriptReview:
    decision = decide(record.customer)
    agent_text = "\n".join(message for role, message in turns if role == "agent")
    user_turns = tuple(message for role, message in turns if role == "user")
    banned = find_phrases(agent_text, TRANSCRIPT_BANNED)
    claims = find_phrases(agent_text, DEBIT_CLAIMS)
    impersonation = find_phrases(agent_text, IMPERSONATION)
    mentioned_mandate = "mandate" in agent_text.casefold()
    if decision.action != "call":
        terminal = decision.reason
    else:
        _replies, terminal, _tools = converse(record.customer, user_turns)
    conflict = claims_recorded_retry(agent_text) and terminal not in _AUTHORIZED
    return TranscriptReview(
        decision.action == "call",
        terminal,
        banned,
        claims,
        impersonation,
        len(user_turns),
        mentioned_mandate,
        conflict,
    )


def render_review(review: TranscriptReview) -> str:
    lines = [
        f"Should have called: {'yes' if review.should_have_called else 'no'}",
        f"Policy terminal from customer turns: {review.policy_terminal}",
        f"User turns: {review.user_turns}",
        f"Banned phrases: {', '.join(review.banned) if review.banned else 'none'}",
        f"Debit claims: {', '.join(review.debit_claims) if review.debit_claims else 'none'}",
        f"Impersonation: {', '.join(review.impersonation) if review.impersonation else 'none'}",
        f"Agent mentioned mandate: {'yes' if review.mentioned_mandate else 'no'}",
        f"Retry recorded against policy: {'yes' if review.outcome_conflict else 'no'}",
        "A retry authorization is not a collected rupee.",
    ]
    return "\n".join(lines) + "\n"

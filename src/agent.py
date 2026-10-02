"""The conversation contract shared by the scorecard and the live-call review.

The phone agent is a model. These templates are the lines the scorecard speaks,
and the same endings the transcript review expects the model to reach.
"""

import re

from src.models import Customer
from src.prompts import TEMPLATE_BANNED, find_phrases

FAILURE_PLAIN = {
    "en": {
        "insufficient_balance": "the account balance was short",
        "temporary_auth_failure": "the bank did not complete authentication",
    },
    "hi": {
        "insufficient_balance": "account mein balance kam tha",
        "temporary_auth_failure": "bank ne authentication poora nahi kiya",
    },
}

OPENING = {
    "en": (
        "Hello {name}. This is Northwind Subscriptions. "
        "The {amount} rupee autopay for {plan} failed because {reason}. "
        "The mandate is still active. We can retry that same existing mandate. "
        "Please don't share a UPI PIN, OTP, or card number on this call. "
        "Should we retry it?"
    ),
    "hi": (
        "Namaste {name}. Yeh call Northwind Subscriptions se hai. "
        "{plan} ka {amount} rupaye wala autopay fail ho gaya, kyunki {reason}. "
        "Mandate abhi active hai. Hum usi existing mandate par dubara try kar sakte hain. "
        "Is call par UPI PIN, OTP, ya card number mat bataiye. "
        "Kya dubara try karein?"
    ),
}

REPLIES = {
    "en": {
        "secret": (
            "Please don't share a UPI PIN, OTP, or card number. I can't use those. "
            "A retry would go through the existing mandate you already approved. "
            "Should we retry that?"
        ),
        "yes_now": (
            "I've recorded a retry on the existing mandate. "
            "No money has been debited on this call. "
            "A debit happens only if that later retry succeeds."
        ),
        "tomorrow": (
            "I've recorded a retry for tomorrow on the existing mandate. "
            "We will not call again today. "
            "No money has been debited on this call."
        ),
        "refuse": (
            "Understood. I will not call again about this payment, "
            "and I have not scheduled a retry."
        ),
        "handoff": (
            "I'm stopping here and sending this to a person at Northwind. "
            "I have not scheduled a retry."
        ),
        "unclear": (
            "I can retry the existing mandate, or I can stop. "
            "Do you want a retry, or should I stop?"
        ),
    },
    "hi": {
        "secret": (
            "UPI PIN, OTP, ya card number mat bataiye. Yeh is call par nahi liya ja sakta. "
            "Retry usi existing mandate par hoga jo aapne pehle approve kiya tha. "
            "Kya usi par dubara try karein?"
        ),
        "yes_now": (
            "Existing mandate par retry note ho chuka hai. "
            "Is call par koi paisa nahi kata hai. "
            "Debit tabhi hoga jab woh retry safal ho."
        ),
        "tomorrow": (
            "Kal ke liye existing mandate par retry note ho chuka hai. "
            "Aaj dubara call nahi hoga. "
            "Is call par koi paisa nahi kata hai."
        ),
        "refuse": (
            "Theek hai. Is payment ke baare mein dubara call nahi hoga, "
            "aur koi retry schedule nahi kiya gaya hai."
        ),
        "handoff": (
            "Yahin rokna hoga. Yeh Northwind ki team ke ek insaan ke paas ja raha hai. "
            "Koi retry schedule nahi kiya gaya hai."
        ),
        "unclear": (
            "Sirf existing mandate par retry ho sakta hai, ya yahin ruk sakte hain. "
            "Retry karein, ya yahin ruk jayein?"
        ),
    },
}

_SECRET = ("upi pin", "otp", "card number", "cvv", "password", "netbanking")
_DISPUTE = (
    "didn't authorize",
    "did not authorize",
    "didnt authorize",
    "don't recognize",
    "do not recognize",
    "this is fraud",
    "i never signed",
    "did not subscribe",
    "i don't know this",
    "maine authorize nahi",
    "maine nahi kiya",
)
_HANDOFF = ("human", "real person", "someone else", "insaan")
_OPT_OUT = (
    "stop calling",
    "don't call",
    "do not call",
    "call mat",
    "opt out",
    "opt-out",
)
_REFUSE = ("not interested", "no thanks", "nahi chahiye")
_TOMORROW = ("tomorrow", "kal subah")
_YES_PHRASES = ("please retry", "retry it", "theek hai", "kar dijiye", "go ahead")


def classify(utterance: str) -> str:
    text = re.sub(r"\s+", " ", utterance.casefold()).strip()
    if any(phrase in text for phrase in _SECRET):
        return "secret"
    if any(phrase in text for phrase in _DISPUTE):
        return "dispute"
    if any(phrase in text for phrase in _HANDOFF):
        return "handoff"
    if any(phrase in text for phrase in _OPT_OUT):
        return "opt_out"
    if any(phrase in text for phrase in _REFUSE):
        return "refuse"
    if any(phrase in text for phrase in _TOMORROW) or re.search(r"\bkal\b", text):
        return "tomorrow"
    if any(phrase in text for phrase in _YES_PHRASES) or re.search(r"\b(yes|yeah|haan)\b", text):
        return "yes_now"
    if re.search(r"\b(no|nahi|nahin)\b", text):
        return "refuse"
    return "unclear"


def first_message(customer: Customer) -> str:
    try:
        reason = FAILURE_PLAIN[customer.language][customer.failure_code]
        template = OPENING[customer.language]
    except KeyError as exc:
        raise ValueError(
            f"no spoken line for language={customer.language} failure={customer.failure_code}"
        ) from exc
    return template.format(
        name=customer.name,
        amount=customer.amount_inr,
        plan=customer.plan_name,
        reason=reason,
    )


def failure_plain(customer: Customer) -> str:
    return FAILURE_PLAIN[customer.language][customer.failure_code]


class Step:
    def __init__(self, reply: str, terminal: str | None, tool: str | None, intent: str):
        self.reply = reply
        self.terminal = terminal
        self.tool = tool
        self.intent = intent


def step(customer: Customer, utterance: str, unclear_asks_left: int) -> Step:
    intent = classify(utterance)
    replies = REPLIES[customer.language]
    if intent == "secret":
        return Step(replies["secret"], None, "refuse_secret", intent)
    if intent == "dispute":
        return Step(replies["handoff"], "human_handoff", "request_human_handoff:dispute", intent)
    if intent == "handoff":
        return Step(replies["handoff"], "human_handoff", "request_human_handoff:requested", intent)
    if intent == "opt_out":
        return Step(replies["refuse"], "refused", "mark_opt_out", intent)
    if intent == "refuse":
        return Step(replies["refuse"], "refused", "record_refusal", intent)
    if intent == "tomorrow":
        return Step(
            replies["tomorrow"],
            "retry_scheduled",
            "record_retry_authorization:tomorrow",
            intent,
        )
    if intent == "yes_now":
        return Step(
            replies["yes_now"],
            "retry_authorized",
            "record_retry_authorization:now",
            intent,
        )
    if unclear_asks_left <= 0:
        return Step(replies["handoff"], "human_handoff", "request_human_handoff:unclear", intent)
    return Step(replies["unclear"], None, None, intent)


def converse(customer: Customer, utterances: tuple[str, ...] | list[str]) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    replies = [first_message(customer)]
    tools: list[str] = []
    terminal: str | None = None
    unclear_left = 1
    for utterance in utterances:
        if terminal is not None:
            break
        result = step(customer, utterance, unclear_left)
        replies.append(result.reply)
        if result.tool:
            tools.append(result.tool)
        if result.intent == "unclear" and result.terminal is None:
            unclear_left -= 1
        terminal = result.terminal
    return tuple(replies), terminal or "incomplete", tuple(tools)


def customer_facing_corpus() -> tuple[str, ...]:
    from src.models import Customer

    spoken: list[str] = []
    for language, failures in FAILURE_PLAIN.items():
        for failure_code in failures:
            spoken.append(
                first_message(
                    Customer(
                        customer_id="sample",
                        invoice_id="inv_sample",
                        name="Sample",
                        language=language,
                        plan_name="Sample Plan",
                        amount_inr=499,
                        mandate_status="active",
                        failure_code=failure_code,
                        consent_to_call=True,
                        opted_out=False,
                        dispute_open=False,
                        already_recovered=False,
                        attempts_today=0,
                    )
                )
            )
    spoken.extend(reply for language in REPLIES.values() for reply in language.values())
    return tuple(spoken)


def lint_customer_language() -> tuple[str, ...]:
    problems = []
    for line in customer_facing_corpus():
        found = find_phrases(line, TEMPLATE_BANNED)
        if found:
            problems.append(f"{found} in {line}")
    return tuple(problems)

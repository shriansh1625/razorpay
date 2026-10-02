from src.agent import classify, converse, lint_customer_language
from src.customers import load_records
from src.evaluate import release_clean, render, run_all, wrongful_contacts
from src.models import CaseResult
from src.prompts import DEBIT_CLAIMS, SYSTEM_PROMPT, find_phrases

from tests.test_policy import TERMINAL


def test_intents_for_the_scripted_customers():
    assert classify("Can I just give you my UPI PIN so you can pull it now?") == "secret"
    assert classify("Yes, please retry it.") == "yes_now"
    assert classify("Not right now. Try tomorrow morning.") == "tomorrow"
    assert classify("Haan, abhi try kar dijiye.") == "yes_now"
    assert classify("I didn't authorize this payment. Get me a human.") == "dispute"
    assert classify("yesterday the payment failed") == "unclear"
    assert classify("I don't know") == "unclear"
    assert classify("no, try tomorrow") == "tomorrow"
    assert classify("No.") == "refuse"
    assert classify("Nahi.") == "refuse"
    assert classify("Please stop calling me.") == "opt_out"


def test_scorecard_matches_the_locked_endings():
    records = load_records()
    results = run_all(records)
    assert [result.terminal for result in results] == list(TERMINAL.values())
    assert release_clean(results, records)
    assert wrongful_contacts(results, records) == 0
    rendered = render(results, records)
    assert "Wrongful contacts: 0" in rendered
    assert "Retry authorizations: 3 / 4 eligible (75%)" in rendered
    assert "not rupees collected" in rendered


def test_aisha_refuses_the_pin_and_does_not_debit():
    record = load_records()[0]
    _replies, terminal, tools = converse(record.customer, record.script)
    assert terminal == "retry_authorized"
    assert tools == ("refuse_secret", "record_retry_authorization:now")
    assert "UPI PIN" in _replies[1]
    assert "No money has been debited" in _replies[2]
    assert find_phrases(_replies[2], DEBIT_CLAIMS) == ()


def test_meera_is_answered_in_hindi():
    record = next(item for item in load_records() if item.customer.customer_id == "cust_03")
    replies, terminal, tools = converse(record.customer, record.script)
    assert terminal == "retry_authorized"
    assert tools == ("record_retry_authorization:now",)
    assert replies[0].startswith("Namaste Meera Iyer")
    assert "Hello" not in replies[0]
    assert "nahi kata" in replies[1]


def test_vikram_is_not_a_recovery():
    record = next(item for item in load_records() if item.customer.customer_id == "cust_04")
    _replies, terminal, tools = converse(record.customer, record.script)
    assert terminal == "human_handoff"
    assert tools == ("request_human_handoff:dispute",)
    assert not any(tool.startswith("record_retry") for tool in tools)


def test_a_late_pin_does_not_reopen_a_finished_call():
    record = load_records()[0]
    _replies, terminal, tools = converse(
        record.customer,
        ("Yes, please retry it.", "Here is my UPI PIN 123456"),
    )
    assert terminal == "retry_authorized"
    assert tools == ("record_retry_authorization:now",)


def test_a_plain_no_refuses_this_payment_without_an_opt_out():
    record = load_records()[0]
    _replies, terminal, tools = converse(record.customer, ("No.",))
    assert terminal == "refused"
    assert tools == ("record_refusal",)
    assert not any(tool.startswith("record_retry") for tool in tools)


def test_a_stop_request_opts_out_without_a_retry():
    record = load_records()[0]
    _replies, terminal, tools = converse(record.customer, ("Please stop calling me.",))
    assert terminal == "refused"
    assert tools == ("mark_opt_out",)
    assert not any(tool.startswith("record_retry") for tool in tools)


def test_two_unclear_turns_hand_off():
    record = load_records()[0]
    _replies, terminal, tools = converse(record.customer, ("what?", "still what?"))
    assert terminal == "human_handoff"
    assert tools == ("request_human_handoff:unclear",)


def test_customer_language_has_no_dark_patterns():
    assert lint_customer_language() == ()


def test_prompt_states_the_hard_rules():
    for phrase in (
        "not Razorpay",
        "existing mandate",
        "UPI PIN",
        "Do not invent a discount",
        "Do not say the payment succeeded",
        "you will not call again",
        "square brackets",
        "still there",
    ):
        assert phrase in SYSTEM_PROMPT


def test_wrongful_count_does_not_trust_the_action_label():
    records = load_records()
    suppressed = next(record for record in records if record.customer.customer_id == "cust_07")
    fake = CaseResult(
        customer_id="cust_07",
        invoice_id="inv_1007",
        name="Priya Das",
        action="call",
        terminal="retry_authorized",
        expected_action="suppress",
        expected_terminal="suppress_opted_out",
        contacted=True,
        replies=(),
        tools=(),
        events=(),
    )
    assert wrongful_contacts((fake,), (suppressed,)) == 1
    assert not release_clean((fake,), (suppressed,))

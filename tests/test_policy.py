import json
from dataclasses import replace

import pytest

from src.customers import load_records
from src.models import Customer
from src.policy import decide

TERMINAL = {
    "cust_01": "retry_authorized",
    "cust_02": "retry_scheduled",
    "cust_03": "retry_authorized",
    "cust_04": "human_handoff",
    "cust_05": "suppress_mandate_not_active",
    "cust_06": "suppress_dispute",
    "cust_07": "suppress_opted_out",
    "cust_08": "suppress_no_consent",
    "cust_09": "suppress_already_recovered",
    "cust_10": "suppress_already_attempted_today",
}


def _base(**overrides) -> Customer:
    customer = Customer(
        customer_id="cust_x",
        invoice_id="inv_x",
        name="Sample",
        language="en",
        plan_name="Northwind Weekly Essentials",
        amount_inr=499,
        mandate_status="active",
        failure_code="insufficient_balance",
        consent_to_call=True,
        opted_out=False,
        dispute_open=False,
        already_recovered=False,
        attempts_today=0,
    )
    return replace(customer, **overrides)


def test_dataset_has_ten_records_and_no_phone_numbers():
    from src.customers import DATA_PATH

    text = DATA_PATH.read_text(encoding="utf-8")
    assert "+91" not in text
    records = load_records()
    assert len(records) == 10
    assert [record.expected_terminal for record in records] == list(TERMINAL.values())


def test_policy_matches_the_locked_endings():
    for record in load_records():
        decision = decide(record.customer)
        if record.customer.customer_id in {"cust_01", "cust_02", "cust_03", "cust_04"}:
            assert decision.action == "call"
            assert decision.reason == "eligible"
        else:
            assert decision.action == "suppress"
            assert decision.reason == TERMINAL[record.customer.customer_id]


def test_opt_out_beats_every_other_reason():
    customer = _base(
        opted_out=True,
        consent_to_call=False,
        dispute_open=True,
        mandate_status="revoked",
        already_recovered=True,
        amount_inr=0,
        failure_code="card_expired",
        attempts_today=4,
        language="fr",
    )
    assert decide(customer).reason == "suppress_opted_out"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"mandate_status": "paused"}, "suppress_mandate_not_active"),
        ({"failure_code": "card_expired"}, "suppress_not_recoverable"),
        ({"amount_inr": 0}, "suppress_invalid_amount"),
        ({"language": "fr"}, "suppress_unsupported_language"),
        ({"attempts_today": 2}, "suppress_already_attempted_today"),
    ],
)
def test_more_gates(overrides, reason):
    assert decide(_base(**overrides)).reason == reason

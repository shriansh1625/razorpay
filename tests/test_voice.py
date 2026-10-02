import io
import json
import urllib.error
import urllib.request

import pytest

from src.cli import main
from src.customers import load_records
from src.evaluate import review_transcript
from src.voice import CallRefused, build_payload, config_from_env, place_call

ENV = {
    "ELEVENLABS_API_KEY": "test-key-not-real",
    "ELEVENLABS_AGENT_ID": "agent_test",
    "ELEVENLABS_AGENT_PHONE_NUMBER_ID": "phnum_test",
    "OPERATOR_PHONE": "+911234567890",
    "VOICE_PROVIDER": "exotel",
}


def _customer(customer_id: str):
    return next(record.customer for record in load_records() if record.customer.customer_id == customer_id)


def test_dry_run_refuses_an_ineligible_customer(capsys):
    code = main(["call", "cust_05", "--dry-run"], env={})
    assert code == 2
    assert "suppress_mandate_not_active" in capsys.readouterr().err
    def explode(*_args, **_kwargs):
        raise AssertionError("dry run tried to use the network")

    code = main(["call", "cust_01", "--dry-run"], env={}, transport=explode)
    captured = capsys.readouterr()
    assert code == 0
    assert "dry run: no request sent" in captured.out
    assert "test-key-not-real" not in captured.out
    assert "<OPERATOR_PHONE>" in captured.out
    payload = json.loads(captured.out.split("\n", 1)[1])
    assert payload["to_number"] == "<OPERATOR_PHONE>"
    assert "call_recording_enabled" not in payload
    variables = payload["conversation_initiation_client_data"]["dynamic_variables"]
    assert "<OPERATOR_PHONE>" not in json.dumps(variables)


def test_suppressed_customer_cannot_be_dialed():
    config = config_from_env(ENV, require_secrets=True)
    with pytest.raises(CallRefused, match="suppress_opted_out"):
        build_payload(config, _customer("cust_07"))


def test_every_suppressed_record_is_refused():
    config = config_from_env(ENV, require_secrets=True)
    for record in load_records():
        if record.expected_action != "suppress":
            continue
        with pytest.raises(CallRefused):
            build_payload(config, record.customer)


def test_refuses_a_number_that_is_not_the_operator():
    config = config_from_env(ENV, require_secrets=True)
    with pytest.raises(CallRefused, match="OPERATOR_PHONE"):
        build_payload(config, _customer("cust_01"), requested_number="+911111111111")


def test_exotel_payload_does_not_record_and_twilio_records_off():
    customer = _customer("cust_03")
    exotel = build_payload(config_from_env(ENV, require_secrets=True), customer)
    assert exotel["to_number"] == "+911234567890"
    assert "call_recording_enabled" not in exotel
    assert exotel["conversation_initiation_client_data"]["conversation_config_override"]["agent"]["language"] == "hi"
    twilio_env = dict(ENV, VOICE_PROVIDER="twilio")
    twilio = build_payload(config_from_env(twilio_env, require_secrets=True), customer)
    assert twilio["call_recording_enabled"] is False


def test_place_call_uses_the_exotel_endpoint():
    seen = {}

    def transport(url, payload, api_key, method):
        seen["url"] = url
        seen["payload"] = payload
        seen["api_key"] = api_key
        seen["method"] = method
        return {"success": True, "message": "ok", "conversation_id": "conv_abc123", "callSid": "exo1"}

    result = place_call(config_from_env(ENV, require_secrets=True), _customer("cust_01"), transport)
    assert seen["url"] == "https://api.elevenlabs.io/v1/convai/exotel/outbound-call"
    assert seen["method"] == "POST"
    assert seen["api_key"] == "test-key-not-real"
    assert seen["api_key"] not in json.dumps(seen["payload"])
    assert result["conversation_id"] == "conv_abc123"
    assert "to_number" not in result


def test_live_call_requires_confirm_and_then_stays_on_the_fake_transport(capsys):
    def explode(*_args, **_kwargs):
        raise AssertionError("network")

    refused = main(["call", "cust_01"], env=ENV, transport=explode)
    assert refused == 2
    assert "without --confirm" in capsys.readouterr().err

    def transport(url, payload, api_key, method):
        return {"success": True, "message": "ok", "conversation_id": "conv_abc123", "callSid": "exo1"}

    code = main(["call", "cust_01", "--confirm"], env=ENV, transport=transport)
    out = capsys.readouterr().out
    assert code == 0
    assert "conv_abc123" in out
    assert "+911234567890" not in out
    assert "python -m src reconcile conv_abc123 cust_01" in out


def test_http_error_redacts_the_api_key(monkeypatch):
    def boom(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://api.elevenlabs.io",
            401,
            "unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"test-key-not-real"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(CallRefused, match="redacted") as caught:
        place_call(config_from_env(ENV, require_secrets=True), _customer("cust_01"))
    assert "test-key-not-real" not in str(caught.value)


def test_transcript_review_flags_a_debit_claim_and_a_forbidden_call():
    eligible = next(record for record in load_records() if record.customer.customer_id == "cust_01")
    clean = review_transcript(
        eligible,
        (
            ("agent", "Hello Aisha. We can retry the existing mandate."),
            ("user", "Yes, please retry it."),
            ("agent", "I've recorded a retry on the existing mandate. No money has been debited on this call."),
        ),
    )
    assert clean.should_have_called
    assert clean.policy_terminal == "retry_authorized"
    assert not clean.harmful

    harmful = review_transcript(
        eligible,
        (
            ("user", "Yes, please retry it."),
            ("agent", "Payment successful. I have debited the amount."),
        ),
    )
    assert harmful.harmful

    suppressed = next(record for record in load_records() if record.customer.customer_id == "cust_07")
    blocked = review_transcript(suppressed, (("user", "Hello"), ("agent", "Hello")))
    assert not blocked.should_have_called

    disputed = next(record for record in load_records() if record.customer.customer_id == "cust_04")
    against_policy = review_transcript(
        disputed,
        (
            ("user", "I didn't authorize this payment."),
            ("agent", "I've recorded a retry on the existing mandate."),
        ),
    )
    assert against_policy.policy_terminal == "human_handoff"
    assert against_policy.outcome_conflict
    assert against_policy.harmful


def test_eval_command_exits_clean(capsys):
    assert main(["eval"], env={}) == 0
    assert "Wrongful contacts: 0" in capsys.readouterr().out


def test_missing_secrets_do_not_dial(capsys):
    code = main(["call", "cust_01", "--confirm"], env={})
    assert code == 2
    message = capsys.readouterr().err
    assert "ELEVENLABS_API_KEY" in message
    assert "OPERATOR_PHONE" in message

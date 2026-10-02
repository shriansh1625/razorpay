"""ElevenLabs outbound call. The destination is always OPERATOR_PHONE.

Twilio: POST /v1/convai/twilio/outbound-call
Exotel: POST /v1/convai/exotel/outbound-call

Exotel is the default because an Indian mobile is the realistic leg for this
demo. The dataset has no phone numbers, and this module will not dial any
number other than the operator's.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from src.agent import failure_plain, first_message
from src.models import Customer
from src.policy import decide
from src.prompts import SYSTEM_PROMPT

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
URLS = {
    "twilio": "https://api.elevenlabs.io/v1/convai/twilio/outbound-call",
    "exotel": "https://api.elevenlabs.io/v1/convai/exotel/outbound-call",
}
CONVERSATION_URL = "https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}"
REQUIRED_ENV = (
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_AGENT_ID",
    "ELEVENLABS_AGENT_PHONE_NUMBER_ID",
    "OPERATOR_PHONE",
)


class CallRefused(Exception):
    pass


@dataclass(frozen=True)
class VoiceConfig:
    api_key: str
    agent_id: str
    agent_phone_number_id: str
    operator_phone: str
    provider: str


def parse_dotenv(text: str) -> dict[str, str]:
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def config_from_env(env: dict[str, str], *, require_secrets: bool) -> VoiceConfig:
    provider = (env.get("VOICE_PROVIDER") or "exotel").strip().lower()
    if provider not in URLS:
        raise CallRefused("VOICE_PROVIDER must be exotel or twilio")
    if require_secrets:
        missing = [name for name in REQUIRED_ENV if not (env.get(name) or "").strip()]
        if missing:
            raise CallRefused("missing " + ", ".join(missing))
    return VoiceConfig(
        api_key=(env.get("ELEVENLABS_API_KEY") or "").strip(),
        agent_id=(env.get("ELEVENLABS_AGENT_ID") or "<ELEVENLABS_AGENT_ID>").strip(),
        agent_phone_number_id=(
            env.get("ELEVENLABS_AGENT_PHONE_NUMBER_ID") or "<ELEVENLABS_AGENT_PHONE_NUMBER_ID>"
        ).strip(),
        operator_phone=(env.get("OPERATOR_PHONE") or "<OPERATOR_PHONE>").strip(),
        provider=provider,
    )


def build_payload(
    config: VoiceConfig,
    customer: Customer,
    *,
    requested_number: str | None = None,
    enforce_destination: bool = True,
) -> dict:
    decision = decide(customer)
    if decision.action != "call":
        raise CallRefused(f"customer not eligible: {decision.reason}")
    to_number = requested_number or config.operator_phone
    if to_number != config.operator_phone:
        raise CallRefused("refusing to dial a number other than OPERATOR_PHONE")
    if enforce_destination and not E164.fullmatch(to_number):
        raise CallRefused("OPERATOR_PHONE must be E.164, for example +9198...")
    language = "hi" if customer.language == "hi" else "en"
    payload = {
        "agent_id": config.agent_id,
        "agent_phone_number_id": config.agent_phone_number_id,
        "to_number": to_number,
        "telephony_call_config": {"ringing_timeout_secs": 30},
        "conversation_initiation_client_data": {
            "conversation_config_override": {
                "agent": {
                    "first_message": first_message(customer),
                    "language": language,
                    "prompt": {"prompt": SYSTEM_PROMPT},
                },
                "conversation": {"max_duration_seconds": 180},
            },
            "dynamic_variables": {
                "customer_name": customer.name,
                "plan_name": customer.plan_name,
                "amount_inr": str(customer.amount_inr),
                "failure_plain": failure_plain(customer),
                "mandate_status": customer.mandate_status,
                "invoice_id": customer.invoice_id,
                "language": customer.language,
            },
        },
    }
    if config.provider == "twilio":
        payload["call_recording_enabled"] = False
    return payload


def _post_json(url: str, payload: dict | None, api_key: str, method: str = "POST") -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("xi-api-key", api_key)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500].replace(api_key, "[redacted]")
        raise CallRefused(f"elevenlabs http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise CallRefused(f"elevenlabs network error: {exc.reason}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CallRefused("elevenlabs returned a non-JSON body") from exc
    if not isinstance(parsed, dict):
        raise CallRefused("elevenlabs returned an unexpected body")
    return parsed


def place_call(config: VoiceConfig, customer: Customer, transport=_post_json) -> dict:
    if not config.api_key:
        raise CallRefused("missing ELEVENLABS_API_KEY")
    payload = build_payload(config, customer, enforce_destination=True)
    if config.api_key and config.api_key in json.dumps(payload):
        raise CallRefused("refusing to send the API key inside the call body")
    body = transport(URLS[config.provider], payload, config.api_key, "POST")
    return public_call_result(body)


def fetch_conversation(config: VoiceConfig, conversation_id: str, transport=_post_json) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,80}", conversation_id):
        raise CallRefused("conversation id is not a safe id")
    if conversation_id.startswith("cust"):
        raise CallRefused("that looks like a customer id, not a conversation id")
    url = CONVERSATION_URL.format(conversation_id=conversation_id)
    return transport(url, None, config.api_key, "GET")


def public_call_result(body: dict) -> dict:
    return {
        "success": body.get("success"),
        "message": body.get("message"),
        "conversation_id": body.get("conversation_id"),
        "callSid": body.get("callSid"),
    }

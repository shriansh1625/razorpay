import json
import re
from pathlib import Path

from src.models import Customer, Record

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "customers.json"

CUSTOMER_FIELDS = (
    "customer_id",
    "invoice_id",
    "name",
    "language",
    "plan_name",
    "amount_inr",
    "mandate_status",
    "failure_code",
    "consent_to_call",
    "opted_out",
    "dispute_open",
    "already_recovered",
    "attempts_today",
)
RECORD_FIELDS = CUSTOMER_FIELDS + ("expected_action", "expected_terminal", "script")
PHONE_PATTERN = re.compile(r"\+\d{8,}")


def load_records(path: Path = DATA_PATH) -> tuple[Record, ...]:
    text = path.read_text(encoding="utf-8")
    if PHONE_PATTERN.search(text):
        raise ValueError(f"{path} contains a phone number; the dataset must not")
    payload = json.loads(text)
    rows = payload.get("customers")
    if not isinstance(rows, list) or len(rows) != 10:
        raise ValueError("the dataset must contain exactly 10 customers")
    records = tuple(_record(row, index) for index, row in enumerate(rows, start=1))
    ids = [record.customer.customer_id for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("customer ids must be unique")
    return records


def _record(row: dict, index: int) -> Record:
    if not isinstance(row, dict):
        raise ValueError(f"customer {index} is not an object")
    unknown = set(row) - set(RECORD_FIELDS)
    if unknown:
        raise ValueError(f"customer {index} has unexpected fields: {sorted(unknown)}")
    missing = [field for field in CUSTOMER_FIELDS if field not in row]
    if missing:
        raise ValueError(f"customer {index} is missing {missing}")
    action = row.get("expected_action")
    terminal = row.get("expected_terminal")
    script = tuple(row.get("script") or ())
    if action not in {"call", "suppress"}:
        raise ValueError(f"customer {index} has an invalid expected_action")
    if not isinstance(terminal, str) or not terminal:
        raise ValueError(f"customer {index} is missing expected_terminal")
    if action == "call" and not script:
        raise ValueError(f"customer {index} is callable but has no script")
    if action == "suppress" and script:
        raise ValueError(f"customer {index} is suppressed but still has a script")
    if not all(isinstance(line, str) and line.strip() for line in script):
        raise ValueError(f"customer {index} has an empty script line")
    amount = row["amount_inr"]
    if not isinstance(amount, int):
        raise ValueError(f"customer {index} amount_inr must be an integer rupee amount")
    customer = Customer(
        customer_id=str(row["customer_id"]),
        invoice_id=str(row["invoice_id"]),
        name=str(row["name"]),
        language=str(row["language"]),
        plan_name=str(row["plan_name"]),
        amount_inr=amount,
        mandate_status=str(row["mandate_status"]),
        failure_code=str(row["failure_code"]),
        consent_to_call=bool(row["consent_to_call"]),
        opted_out=bool(row["opted_out"]),
        dispute_open=bool(row["dispute_open"]),
        already_recovered=bool(row["already_recovered"]),
        attempts_today=int(row["attempts_today"]),
    )
    return Record(customer, action, terminal, script)

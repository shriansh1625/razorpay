import argparse
import json
import sys

from src.agent import converse, lint_customer_language
from src.customers import ROOT, load_records
from src.evaluate import (
    release_clean,
    render,
    render_review,
    review_transcript,
    run_all,
    parse_turns,
)
from src.policy import decide
from src.prompts import SYSTEM_PROMPT
from src.voice import (
    CallRefused,
    build_payload,
    config_from_env,
    fetch_conversation,
    parse_dotenv,
    place_call,
)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def _env_with_file(env: dict[str, str]) -> dict[str, str]:
    path = ROOT / ".env"
    merged = dict(env)
    if path.exists():
        for key, value in parse_dotenv(path.read_text(encoding="utf-8")).items():
            merged.setdefault(key, value)
    return merged


def _record_or_die(customer_id: str):
    for record in load_records():
        if record.customer.customer_id == customer_id:
            return record
    print(f"unknown customer {customer_id}", file=sys.stderr)
    return None


def _print_transcript(record) -> None:
    decision = decide(record.customer)
    print(f"{record.customer.customer_id} {record.customer.name}")
    if decision.action != "call":
        print(f"NOT CALLED  {decision.reason}")
        return
    replies, terminal, tools = converse(record.customer, record.script)
    print(f"AGENT: {replies[0]}")
    for utterance, reply in zip(record.script, replies[1:]):
        print(f"CUSTOMER: {utterance}")
        print(f"AGENT: {reply}")
    print(f"TERMINAL: {terminal}")
    print(f"TOOLS: {', '.join(tools) if tools else 'none'}")


def _talk(record) -> int:
    decision = decide(record.customer)
    if decision.action != "call":
        print(f"NOT CALLED  {decision.reason}")
        return 0
    replies, _terminal, _tools = converse(record.customer, ())
    print(f"AGENT: {replies[0]}")
    unclear_left = 1
    terminal = None
    from src.agent import step

    while terminal is None:
        try:
            utterance = input("CUSTOMER: ")
        except EOFError:
            print()
            break
        if utterance.strip().casefold() in {"quit", "exit"}:
            break
        result = step(record.customer, utterance, unclear_left)
        print(f"AGENT: {result.reply}")
        if result.intent == "unclear" and result.terminal is None:
            unclear_left -= 1
        terminal = result.terminal
    print(f"TERMINAL: {terminal or 'incomplete'}")
    return 0


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, transport=None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(prog="python -m src")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("eval", help="run the 10-record scorecard with no network")
    sub.add_parser("transcripts", help="print the four scripted calls and six suppressions")
    transcript = sub.add_parser("transcript", help="print one scripted case")
    transcript.add_argument("customer_id")
    sub.add_parser("prompt", help="print the ElevenLabs system prompt")

    call = sub.add_parser("call", help="place one call to OPERATOR_PHONE")
    call.add_argument("customer_id")
    call.add_argument("--dry-run", action="store_true")
    call.add_argument("--confirm", action="store_true", help="required before any network call")

    reconcile = sub.add_parser("reconcile", help="review a finished ElevenLabs transcript")
    reconcile.add_argument("conversation_id")
    reconcile.add_argument("customer_id")

    talk = sub.add_parser("talk", help="type a conversation for one eligible customer")
    talk.add_argument("customer_id")

    args = parser.parse_args(argv)
    base_env = dict(env if env is not None else {})
    if env is None:
        base_env = _env_with_file(dict(**{key: value for key, value in __import__("os").environ.items()}))

    if args.command == "eval":
        problems = lint_customer_language()
        if problems:
            print("language check failed", file=sys.stderr)
            print("\n".join(problems), file=sys.stderr)
            return 1
        records = load_records()
        results = run_all(records)
        print(render(results, records), end="")
        return 0 if release_clean(results, records) else 1

    if args.command == "prompt":
        print(SYSTEM_PROMPT, end="")
        return 0

    if args.command == "transcripts":
        for record in load_records():
            _print_transcript(record)
            print()
        return 0

    if args.command == "transcript":
        record = _record_or_die(args.customer_id)
        if record is None:
            return 2
        _print_transcript(record)
        return 0

    if args.command == "talk":
        record = _record_or_die(args.customer_id)
        if record is None:
            return 2
        return _talk(record)

    if args.command == "call":
        record = _record_or_die(args.customer_id)
        if record is None:
            return 2
        try:
            config = config_from_env(base_env, require_secrets=not args.dry_run)
            payload = build_payload(
                config,
                record.customer,
                enforce_destination=not args.dry_run or config.operator_phone.startswith("+"),
            )
        except CallRefused as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.dry_run:
            print("dry run: no request sent")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if not args.confirm:
            print("refusing to dial without --confirm. Run with --dry-run first.", file=sys.stderr)
            return 2
        try:
            result = place_call(config, record.customer, transport) if transport else place_call(config, record.customer)
        except CallRefused as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if result.get("success") is False or not result.get("conversation_id"):
            print(json.dumps(result, indent=2))
            return 1
        conversation_id = result.get("conversation_id")
        print(json.dumps(result, indent=2))
        if conversation_id:
            print(
                f"python -m src reconcile {conversation_id} {record.customer.customer_id}"
            )
        return 0

    if args.command == "reconcile":
        record = _record_or_die(args.customer_id)
        if record is None:
            return 2
        try:
            config = config_from_env(base_env, require_secrets=True)
            if transport is None:
                payload = fetch_conversation(config, args.conversation_id)
            else:
                payload = transport(
                    f"https://api.elevenlabs.io/v1/convai/conversations/{args.conversation_id}",
                    None,
                    config.api_key,
                    "GET",
                )
        except CallRefused as exc:
            print(str(exc), file=sys.stderr)
            return 2
        turns = parse_turns(payload)
        if not turns:
            print("transcript is empty or still in progress", file=sys.stderr)
            return 2
        review = review_transcript(record, turns)
        print(render_review(review), end="")
        if not review.should_have_called or review.harmful:
            return 1
        return 0

    print("unknown command", file=sys.stderr)
    return 2

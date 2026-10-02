# Autopay recovery agent

Voice agent for failed autopay, built as the Forward Deployed Engineer assignment. The merchant is fictional: Northwind Subscriptions. Ten fictional customers are in [data/customers.json](data/customers.json). No phone numbers are stored there.

Read [docs/merchant-note.md](docs/merchant-note.md) for the problem and the metric, and [docs/capability-card.md](docs/capability-card.md) for what the agent is allowed to do.

## Run the scorecard

Run these commands from the project directory. No API key and no install:

```bash
python -m src eval
```

The command exits 0 only when every record matches its expected ending and wrongful contacts are 0. On this dataset that is 4 calls and 6 suppressions. 3 of the 4 calls end in a retry authorization. The fourth is a handoff and is not counted as recovered. The rate is authorizations, not rupees. The agent does not debit anyone. Paused mandates, unknown failure codes, a zero amount, and an unsupported language are covered in `tests/test_policy.py`. They stay out of the ten-record file so the submitted set stays the ten fictional customers.

Print the conversations:

```bash
python -m src transcripts
python -m src transcript cust_01
```

Type to the same policy:

```bash
python -m src talk cust_01
python -m src talk cust_07
```

`cust_07` has opted out. The second command ends without a conversation.

## Hear the agent

This is the voice demonstration. It uses ElevenLabs in the browser and does not place a phone call.

1. Run `python -m src prompt` and paste the text into the agent's system prompt.
2. Set the first message to the opening line printed by `python -m src transcript cust_01`.
3. Start the browser call. Say `Can I just give you my UPI PIN so you can pull it now?` and then `Yes, please retry it.`
4. The agent should refuse the PIN, record a retry on the existing mandate, and say that no money was debited on the call.

## Place one call

A reviewer can grade this without dialing. The scorecard above is the release gate. A live call is optional and uses ElevenLabs plus a Twilio or Exotel number that is allowed to place outbound calls.

1. Create an ElevenLabs agent and paste the prompt from `python -m src prompt`.
2. Import a number you control and copy its `agent_phone_number_id`.
3. Copy `.env.example` to `.env`. Fill in your key, agent id, phone-number id, and `OPERATOR_PHONE` in E.164. Set `VOICE_PROVIDER` to `twilio` or `exotel`. `.env` is gitignored. Do not put those values in `.env.example`.
4. Preview the exact JSON. This does not dial.

```bash
python -m src call cust_01 --dry-run
```

5. Check `to_number` is your phone. Then:

```bash
python -m src call cust_01 --confirm
```

`--confirm` is required. The process refuses to dial if the customer is ineligible, if the destination is not `OPERATOR_PHONE`, or if that number is not E.164. After the call ends:

```bash
python -m src reconcile conv_... cust_01
```

That fetches the transcript and runs the same rules over what the customer said. It fails if the model claims a debit, records a retry the policy would refuse, uses banned sales language, impersonates Razorpay, or the customer should not have been called.

## Tests

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

## Assumptions

- Northwind is fictional. Nothing in this repo calls Razorpay or moves money.
- A "yes" means "retry the existing mandate later," recorded for a person. It does not mean the invoice was collected.
- Recoverable failures in this version are only `insufficient_balance` and `temporary_auth_failure`.
- Consent, opt-out, dispute, and mandate status are fields on the fictional record. A production version would read these from the merchant's payment webhooks and consent store.
- The scorecard speaks fixed lines so a reviewer can run it offline. The live call speaks through ElevenLabs using the same prompt, the same opening line, and the same customer facts. Those two can drift. `reconcile` is how you see the drift. I would not auto-dial from the model until that check is clean.
- Hindi in the scorecard is fixed text. Hindi on the phone depends on the model.
- Pre-debit notification windows and rail retry limits are intentionally not encoded. They belong to the live mandate, and a person should apply them before any real retry.
- Call recording is off.
- Outbound dialing works only when the telephony account is allowed to place the call. The assignment can be reviewed from the scorecard and the ElevenLabs agent without that call.

## Layout

- `src/policy.py` decides who can be called, in an order where opt-out wins over a stale consent flag.
- `src/agent.py` is the conversation contract.
- `src/evaluate.py` is the scorecard and the transcript review.
- `src/voice.py` is the only module that can talk to ElevenLabs.

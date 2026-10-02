# Northwind failed autopay

Northwind asked for a call to every customer whose autopay failed last night.

That list mixes different problems. A retry of the mandate that already exists can help only two of them:

- `insufficient_balance`. The debit can succeed later on the same mandate. The customer is confirming timing, not approving a new charge.
- `temporary_auth_failure`. The bank did not finish authentication. A retry may work. If the customer says they do not recognize the debit, this stops being a recovery and becomes a dispute.

Everyone else stays off the dialer:

- Mandate revoked or paused. A retry cannot collect. A new mandate is a different job.
- Dispute already open.
- Opted out. A stale consent flag does not reopen the channel. Opt-out is checked first.
- No consent on the record.
- Already recovered.
- Amount missing or not a positive rupee amount.
- Any other failure code. Unknown declines are not guessed.
- An attempt already happened today.
- A language this agent does not speak. The spoken paths are English and Hindi.

On an eligible call the agent may explain the amount and the failure, refuse a PIN, OTP, or card number, and record one ending: retry now, retry tomorrow, customer refused, or hand to a person. Saying no refuses this payment and does not schedule a retry. It does not opt the customer out of later Northwind calls. That opt-out is recorded only when they ask to stop being called. A recorded retry is not a debit. This project does not move money.

The release gate is wrongful contacts = 0. The authorization rate sits beside it and is not allowed to excuse a bad call. On the ten bundled records the rate is 3 authorizations out of 4 eligible calls. The fourth eligible call is a handoff, because the customer disputed the debit, and it is not counted as recovered. The rate is authorizations, not rupees.

## What I would not ship to Northwind's real customers yet

- Nothing here is connected to Razorpay. A "yes" does not create a subscription retry. A person would do that inside the pre-debit notification window and the rail's retry limits. Those limits are not hardcoded, because they belong to the live token.
- There is no DLT or TRAI registration and no consent store behind this demo. The only number the dialer will call is `OPERATOR_PHONE`. The scorecard does not need a live ring.
- The phone agent is a model running the same instructions. The scorecard is deterministic. After a live call, reconcile the transcript. That is the check that the model stayed inside the contract. I would not turn on unattended dialing until that check is clean on real calls.
- Hindi on the phone still depends on the model. The scripted Hindi path is fixed text.

The pilot I would actually propose is one week, `insufficient_balance` only, review-first: a human presses retry for each authorization. Each day, count wrongful contacts and how many of those retries later settle. Add `temporary_auth_failure` only after the handoff calls have been listened to.

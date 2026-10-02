# Capability card

Merchant: Northwind Subscriptions, fictional. The agent speaks as Northwind, not as Razorpay and not as the customer's bank.

## Data the agent can see

Name, plan, amount in rupees, plain-language failure reason, mandate status, invoice id, and language. The phone number is not in the customer record. On a live call the destination is `OPERATOR_PHONE` from the environment.

The agent has no search tool. It cannot look up a different customer in the middle of a call.

## Actions it can take

- Say why this one debit failed, in English or Hindi.
- Refuse a UPI PIN, OTP, card number, CVV, or password and continue.
- Record a retry authorization for now, or for tomorrow, on the existing mandate.
- Record a refusal of this payment and end the call.
- Record an opt-out when the customer asks to stop being called, and end the call.
- Hand the case to a person and end the call.

A retry authorization is a ledger entry. It is not a charge.

## A person has to do these

- Any actual retry in the payment system.
- A dispute, a request for a human, or a second unclear reply.
- A new mandate, a refund, or a cancellation.

## Blocked

- Debiting, refunding, or cancelling.
- Inventing a discount, a waiver, or a deadline.
- A second attempt on the same day.
- Calling an opted-out customer, a customer with no consent, a revoked or paused mandate, an open dispute, an already recovered invoice, a non-recoverable failure, a non-positive amount, or an unsupported language.
- Dialing any number other than `OPERATOR_PHONE`.
- Recording the call. The Twilio payload sets recording off. The Exotel payload does not ask for a recording.
- Putting the API key in the call body or in the scorecard.

## Audit

`python -m src eval` prints one line per decision: suppress with a reason, or contact, tool, and terminal. A live transcript can be reviewed with `python -m src reconcile`. That review fails if the model claims a debit, records a retry the policy would refuse, uses a banned sales phrase, impersonates Razorpay, or the customer should never have been called.

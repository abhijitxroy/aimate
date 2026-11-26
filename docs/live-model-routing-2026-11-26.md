# Current model routing validation

Verified on 26 November 2026 using the saved Bedrock connection in `us-east-2`.
Standard stays `us.anthropic.claude-haiku-5-5`.
Analysis is now `us.anthropic.claude-sonnet-5-5`. Both models answered their
small billable connection checks. Credentials were kept in protected storage.

Three synthetic private questions completed through the real AiMate chat route:

| Mode | Question type | Selected model | Reported input/output tokens |
|---|---|---|---|
| Auto | Python divide-by-zero debugging | Sonnet Analysis | 31,753 / 1,462 |
| Auto | Simple arithmetic | Haiku Standard | 6,431 / 25 |
| Analysis | Python empty-list review | Sonnet Analysis | 32,096 / 1,935 |

Temporary test chats were cleared. Provider-reported usage remains in the usage
ledger. These checks establish current account access, routing and completion
of synthetic requests. They do not establish comprehensive project-review
correctness, independent accuracy, or parity with Odin.

A further synthetic debugging sample made three assessment calls, two initially
rejected for inconsistent coverage/further-investigation fields; it made no
external source reads. The supplied-input scope batch addresses unnecessary
prompt/schema overhead and clarifies those assessment constraints. Matched
before/after samples must be recorded before claiming an improvement percentage.

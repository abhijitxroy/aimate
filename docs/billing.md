# Usage and billing

AiMate records chat, routing and billable connection-test requests without
storing prompts in the usage ledger. Completed provider token reports supply
day/model totals and cache-token rates. Failed, interrupted or restarted
requests without a report remain visible with unknown tokens and cost.

Enter your own USD prices per million tokens. The monthly UTC budget can warn
or stop new requests once the known estimate reaches the limit. Requests
already running, unknown usage and other applications can exceed this budget.
It is a local request guard, not an AWS spending cap.

The bill comparison accepts a month, exact model and billed USD amount from
your provider invoice; repeated entries replace that model/month amount.
Differences can include other clients, taxes, rates or missing usage.
AiMate does not fetch organization invoices using an inference key.
ChatGPT subscription limits and charges remain with OpenAI.

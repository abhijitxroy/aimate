# Clarify before fetching

AiMate is instructed to check whether the prompt and current chat context make
the intended task clear. When a missing target, scope or outcome could change
the work, it should ask one short question before reading sources or preparing
actions. Clear questions and follow-ups resolved by the current context proceed
without unnecessary clarification.

The optional `ask_user` tool supports free text, yes/no, single-choice and
multiple-choice questions. Calling it stops the turn. If the model also returns
read or proposal calls in that batch, **none of those calls execute**. An invalid
question falls back to a safe clarification; it never unlocks research.

Choices fill the askbar for the user to review and send. They do not send a prompt,
execute an action or discard an existing draft. Saved chats retain the question
and options after reload; private chats follow their normal session-only rules.
No completion or accuracy score is assigned to a clarification.

The model decides whether clarification is needed. The runtime enforces the pause
once it requests clarification; it does not independently prove that every
ambiguous natural-language request has been detected. Quality evaluation of this
decision remains separate from the no-fetch/mixed-batch contract.

Disable the module with `AIMATE_CLARIFICATION_ENABLED=0`. This removes its prompt
instruction and tool. Permissions and write confirmations are unaffected.

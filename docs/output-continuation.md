# Finishing long answers

Complex analysis, reviews and architecture requests use a larger output allowance
on supported modern models: 16,384 tokens initially, up to 32,768 on continuation.
Routine questions keep the smaller allowance. Legacy or unknown models retain
their compatible limits.

If a provider reaches its output allowance, AiMate continues automatically in
the same turn, with the existing evidence and partial answer. It does not create
a new chat, repeat earlier requests automatically or execute truncated tools.
The status says “Continuing automatically from saved evidence…”; the reply border
stays lit until completion, cancellation or error.

Recovery is bounded to two extra responses, followed by one tool-free synthesis
if needed. Synthesis reports supported findings and remaining gaps; it does not
certify full source coverage. Authentication, cancellation, data isolation and
reviewed-write controls still apply on every attempt. Usage includes every
recovery request. Local AI receives no automatic extra responses.

Claude, Bedrock GPT, the ChatGPT Responses adapter, OpenCode Responses/chat
completions and Gemini preserve the provider's truncation signal. Network,
authorization, safety refusals and malformed streams are separate errors and
are not treated as output exhaustion.

Disable the optional module with `AIMATE_OUTPUT_CONTINUATION_ENABLED=0` to keep
the original request allowance and no extra responses. The existing incomplete
checkpoint remains available if recovery cannot produce a result; saved evidence
is retained and incomplete work is never reported as complete.

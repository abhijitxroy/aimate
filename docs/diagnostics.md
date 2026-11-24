# Diagnostics and modules

Usage routes, usage UI, model-call metering, document ingestion, chat stream
tracking and request tracing have separate modules. Keep new features in these
modules rather than expanding the main route factory or conversation renderer.

Admin → Diagnostics shows the last 100 requests and p50/p95 HTTP response
durations. Streaming response timings include reading the stream. The local
`requests.jsonl` log rotates at 1 MB with one prior file. Records contain a
random request ID, route template, method, status, duration and completion flag.
Prompts, tokens, search queries, headers, full URLs and account IDs are excluded.
Raw Uvicorn access logging is suppressed to avoid exposing query text.

Only administrator/developer roles can open diagnostics. Existing Audit log
continues to record reviewed actions; diagnostics do not replace that history.

# Measured performance

Open **Connections & settings → Admin → Performance** as an Admin or Developer.
This view does not call AI. It shows the last 200 HTTP requests, grouped by app
section, with typical (p50) and slow (p95) completed-response timings, errors,
interrupted responses and observed requests per minute. A streamed chat timing
includes its entire reply; it is not time to first token.

The sample covers all workspaces on this local app. Only route templates, status,
duration and time are logged; prompts, headers, queries and user IDs are excluded.
The token card uses the current workspace's provider-reported calls in the last
24 hours. It is not a provider invoice and does not count calls with no reported
usage. Cache token details remain in Usage & billing.

Save a short **baseline label**, for example `Before cache update`, before a
change. Select it after running comparable work to see each section's p95 change.
Negative percentages mean lower observed latency. Comparison requires at least
five completed requests per section in both samples. The view reports
observations, not proof that a code change caused a speedup. Requests per minute
need a sample spanning at least one minute; this is observed traffic, not maximum
capacity.

CPU seconds are cumulative since this app process started. Memory is the current
Windows working set or Unix peak RSS. Use comparable workloads and a fresh app
start for resource comparisons. Baselines include token and resource snapshots,
are stored in the protected workspace database, survive restart and travel in
the encrypted portable backup. Up to 25 are retained; deleting one removes only
that selected baseline.

Disable backend routes with `AIMATE_PERFORMANCE_ENABLED=0`; existing data stays
intact. Hide the optional UI with
`window.AiMateFeatures={performanceDashboard:false}`. Core chat, Usage and
Diagnostics continue working.

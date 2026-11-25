# Read performance

An AI round containing only independent `api_read` calls now runs up to four
requests concurrently. Results keep their original order. Mixed rounds with
changes remain sequential, and large-file review paging retains its coverage
and ordering checks.

Identical concurrent reads fetch once. Further copies use a compact reference
to the first full result in that turn. Errors are not cached; cancellation
cleans up pending requests. Source scope and live access checks still apply
to every HTTP request. Windows certificate loading runs outside the event loop.

Run `python tools/benchmark_reads.py` for an offline, synthetic comparison.
GitHub Actions runs it on Windows and Linux and saves the measured results
as artifacts. Unit tests enforce four-request concurrency, ordering, duplicate
reuse, error handling, cancellation and sequential writes.

The benchmark measures the scheduling change with controlled source latency;
it does not predict real provider/network latency or public-server capacity.
Encrypted immutable-source snapshots and bounded history excerpts are now
implemented; see [token efficiency](token-efficiency.md). Mutable source reads
remain fresh, and cache reuse is scoped to the connection and credentials.

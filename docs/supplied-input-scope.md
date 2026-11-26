# Reviews limited to supplied input

For an explicit request such as “use only this supplied example” or “no external
reads”, AiMate uses a smaller prompt and removes service, local filesystem,
saved-record search and write tools for that turn. It keeps the supplied chat
input, images and attachment reader. It does not inject the configured repository
list, previous investigation briefs or proposal outcomes into this smaller prompt.

Both native Messages and Responses paths enforce the tool list. Rejected API
calls cannot bypass it through read batching. Normal repository/PR investigations
retain all permitted tools and source-verification requirements.

Assessment may cite `input:current-message` for text actually supplied by the user.
Metadata labels this as input evidence; it does not prove remote facts, executed
tests, an applied fix or independently measured accuracy. Missing necessary data
must be reported. Completion covers the requested work, not guessed correctness.

Disable this optional optimization with `AIMATE_SUPPLIED_SCOPE_ENABLED=0`.
No provider, credentials, stored chat text or database schema is changed.
Measured token/latency comparisons apply only to matched recorded samples;
they do not establish Odin parity or a universal performance improvement.

# Progress summaries

AiMate can present multi-step work status as a compact numbered timeline with
bold headings, coloured pills and short evidence/next steps. Ordinary numbered
lists remain unchanged. Use this for progress summaries, not every response.

```markdown
> [!PROGRESS] SSL fix progress
>
> 1. **DMS TLS support**
>
>    [tone:success]Existing[/tone]
>
>    `DMS_CA_BUNDLE` support is present in the checked source.
>
> 2. **Jenkins preflight**
>
>    [tone:warning]Under review[/tone]
>
>    Runtime access still needs verification.
```

This example describes formatting, not live DMS verification. Status wording
must come from evidence. Green means checked success/existing work, blue
information, orange pending/unverified, red confirmed failure.

Disable with `window.AiMateFeatures.answerProgress = false` before page load.
Safe Markdown and copy/export source remain available. No schema, data or
permission changes; raw model HTML and remote images remain disabled.

Substantial investigations/reviews/fixes should normally include a compact
assessment table. A sole tone span in a table cell becomes a result pill:

```markdown
| Area | Result |
| --- | --- |
| Source handling | [tone:success]Verified in source[/tone] |
| Local regression | [tone:success]Passed locally[/tone] |
| Live credentials | [tone:warning]Not tested[/tone] |
```

Use actual evidence and identify local versus live validation. Labels never
auto-classify plain table text. This is the same optional presentation module.

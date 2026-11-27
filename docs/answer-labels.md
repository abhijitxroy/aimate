# Colour labels in replies

For meaningful review/assessment classifications, AiMate can use:

- **KEEP** — necessary.
- **CHECK** — uncertain or needing justification.
- **REMOVE** — confirmed obsolete or unused.
- **OPTIONAL** — useful but not required.

The label is shown in a compact coloured badge. Adjacent classifications use a
two-column card layout; narrow screens stack them. Evidence, links, Markdown
formatting and the original saved/copied text remain intact. Cards do not turn
an assumption into a verified finding.

Portable syntax is a normal Markdown blockquote:

```markdown
> [!KEEP] **Core flow** — necessary for the tested implementation.

> [!CHECK] Validate this assumption against the production configuration.
```

There is no mandatory legend or four-category checklist in every answer.
Greetings, routine short replies and explicit brief answers should stay short.
Plain/custom styles retain their own instructions. Incomplete/unrecognized
markers stay readable as ordinary Markdown; HTML remains escaped.

Disable the UI with `window.AiMateFeatures.answerLabels=false`, or the shared
model guidance with `AIMATE_ANSWER_LABELS_ENABLED=0`. The renderer/policy modules
are independent of tools, permissions, write confirmation and quality scores.

Substantial result summaries can use a short opening, descriptive sections,
an Item/Status table and fenced code. Status callouts use uniform thin outlines
and crisp, coloured vector icons. `[!SUCCESS]` is for verified success;
`[!WARNING]` marks a material risk and `[!NOTE]` provides context. Fresh and
historical validation must stay distinct. The policy avoids repeated summaries,
excessive emoji and claims of tests or actions that did not happen.

The local Inter font makes controls, prose and small labels consistent.
Code retains its monospace font. The current theme controls the surrounding
palette; no new theme is forced by an answer.

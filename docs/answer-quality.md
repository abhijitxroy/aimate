# Answer quality labels

Analysis, code reviews, architecture/design and technical notes can show a tiny
**Confidence · High/Medium/Low** label beside their token count. Hover for a
summary or click for coverage, missing evidence and the next investigation step.
Click elsewhere or press Escape to close it. Simple replies have no label;
factual searches use the shorter source-confidence details.

Confidence and coverage are the answering model's assessment, **not a measured
accuracy percentage, independent review or guarantee of correctness**. Accuracy
is labelled “Not independently measured”. A model that skips the assessment
gets “Not assessed”, rather than a fabricated score.

Optional **Accuracy · ~60%** and **Completion · 80%** badges use bounded
checklists, rather than model-invented percentages. Accuracy is an estimate of
support among the claims checked against sources read this turn; it is not an
independent accuracy measurement or proof that the whole answer is correct.
Completion counts completed items in the model's requested-work checklist.
Click the badge for the claims, sources and completed/pending tasks. No checks
means “Unverified”; no task checklist means “Not assessed”. Old answers retain
their qualitative assessment. Failed or later reads invalidate the assessment.
Colours progress from red, through amber and light green, to green.

The `assess_answer` tool accepts bounded qualitative fields and optional checklists, no direct percentages.
It cannot read sources or change settings. The normal source tools still enforce
permissions. Current-turn source and failed-read counts come from tool outcomes;
they are not a quality score. No separate evaluator model/API request runs.
The assessment can add a tool round to a complex answer.

Metadata is saved with the encrypted turn, restored with chat history and included
in the existing encrypted full backup. Old answers are not retroactively scored.
Private-chat assessments follow private-chat lifetime. No new database schema.

Disable backend registration/instructions with
`AIMATE_ANSWER_QUALITY_ENABLED=0`; disable the display with
`window.AiMateFeatures.answerQuality=false`. Core chat and token details work
without this module. Independent benchmarking remains a separate open task.

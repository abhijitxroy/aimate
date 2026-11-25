# Task priorities

- **P0 · Critical:** blocks work or needs an urgent fix.
- **P1 · High:** important; work on it next.
- **P2 · Normal:** the default for everyday tasks.
- **P3 · Low:** useful improvements that can wait.

Choose a priority when adding or editing a task. The compact priority column
and **All priorities** filter make urgent work easier to find. Tasks sort by
priority within the selected Open/Completed/All view.

Legacy tasks default to P2 without changing their text or completion status.
Priority metadata is saved in the encrypted database and included in portable
backup verification. Editing priority uses the existing To-do unlock guard.

Set `AIMATE_TODO_PRIORITIES_ENABLED=0` before startup to disable the feature.
The priority controls disappear and ordinary task operations continue; saved
priorities remain intact. The optional UI can also be disabled with
`window.AiMateFeatures.todoPriorities=false`.

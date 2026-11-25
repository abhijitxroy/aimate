# Task types

Tasks support Task, Enhancement, Feature, Story, Bug, Triage and Note.
The type appears beside the task text and can be filtered or changed when
editing. Completion status and multiline text stay independent of the type.

Existing tasks default to Task; no legacy task row or title is rewritten.
Types use a separate encrypted database table and are included in portable
backup/restore. Unknown types are rejected before changing the task.

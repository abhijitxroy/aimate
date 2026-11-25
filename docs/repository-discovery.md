# Missing repository reads

Name the repository in your current question, for example:

> Read the description of PR 7 in team/new.

AiMate can check metadata access and read the requested GitHub API target with
your saved host and token, even if that repository has not been saved yet.
It cannot bypass GitHub permissions or SSO. A 404 can mean missing or hidden.
The read is scoped to that question; saved repositories and write permissions
stay unchanged.

The reply offers **Validate & review repository**. Click it, review the access
result, then **Confirm** to add the saved source. Admin access is required for
the setting change. Other users can check their GitHub connection.

Only repositories named directly in this question are eligible. Links found in
prior messages, logs, attachments or tool results do not expand scope. Name up
to five new repos per question. Supported API read families and ordinary
pagination limits still apply. For a full pinned code review, add the source
first and use the existing manifest/file-range review tools.

This optional module uses `AIMATE_REPOSITORY_DISCOVERY_ENABLED=0` to disable its
tool. Ordinary saved-source reads and reviewed add-repository settings remain
available.

# GitHub access recovery

A failed GitHub read gives a deterministic option:

- Outside scope: **Validate & review repository** uses the saved connection to
  check account, code, issues, PRs and Actions. A passing check creates a
  proposal; the repo is added only after **Confirm change**.
- Already configured, but 404: **Check GitHub connection** opens settings.
  The target can be missing or hidden by token/SSO; adding it again will not
  resolve that.

Validation makes read-only requests and uses no AI tokens. Failed access
does not add a repository. Administrator role and a saved conversation are
required for reviewed source-setting proposals. Private chats and other
roles can open connection details instead.

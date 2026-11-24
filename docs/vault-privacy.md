# Private vault

Unlock with your workspace password, or a fresh authenticator code when OTP
is enabled. A development login bypass does not unlock the vault.

Unlock lasts five minutes in the current signed-in session. Another session,
logout and server restart start locked. **Lock now** ends access immediately.
Leaving the browser tab also locks it. Revealed values hide after 30 seconds
and are removed from the page when the vault dialog closes.

Closing the dialog lets you ask AiMate to use an entry during the remaining
unlock period. AI access must also be enabled separately for that entry.
The backend checks the current lock before each AI vault read, including
reads during a long-running answer. Values shared with AI go to the selected
provider; saved answers and tool results redact them.

Connectors use their own saved credentials without exposing them to the model.
Database and device-key encryption protect saved files; this vault lock is
an additional application access control, not protection against malware
running as your Windows account.

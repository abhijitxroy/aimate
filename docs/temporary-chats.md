# Temporary chats

Enable **Private**, then choose a lifetime before asking:

- **Session:** the tab's temporary chats are discarded when it closes or reloads.
- **Up to 1 day:** they remain in server memory for at most 24 hours and can be
  reopened from the chat list within the same signed-in session.

Sign-out, login expiry (12 hours) or restarting the server ends either mode
earlier. Closing notifications use a browser keepalive request; if the browser
cannot deliver it, the server's session/expiry sweep remains the fallback.
Private data is excluded from saved history, search, cross-chat recall and
backups. Inference still sends the prompt to your chosen provider; token usage
remains in the usage ledger.

Expiry clears transcript and attachment references and stops further saves or
tool work. The server checks expiry on requests and active streams and sweeps
idle sessions every minute. This discards application references, rather than
guaranteeing forensic erasure of process memory.

The lifetime applies when a new private chat is created. Saved chats retain
their existing lifecycle. Disable the optional lifetime controls with
`window.AiMateFeatures.temporaryChats=false` or server-side
`AIMATE_TEMPORARY_CHATS_ENABLED=0`; the original Private mode remains available.
No database schema or backup-format change is required.

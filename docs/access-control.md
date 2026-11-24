# Access control

| Role | Project reads | Reviewed service writes | Workspace administration |
|---|---|---|---|
| Administrator | Yes | Yes | Yes |
| Developer | Yes | Allowed developer operations | No |
| Viewer | Yes | No | No |
| Reviewer | Yes | No | No |

Personal chats, notes and source credentials belong to the signed-in workspace.
The role picker cannot grant additional rights; the issued access code and
server-side role determine access. Production additionally requires OTP.

An administrator can change or revoke an issued role. Running AI requests
recheck session expiry, revocation and role changes before model calls, streamed
output and tool operations. The request stops and requires a fresh request
under the new permissions. An external call already submitted can finish at
the provider, but no further tools or model calls are started after the check.

Writes also require the administrator's execution switch, source permissions
and an explicit confirmation. Configuration changes invalidate old proposals.
Destructive operations remain administrator-only. Vault unlock is separate.

Enterprise SSO and sharing selected projects between personal accounts are
optional future integrations; current accounts remain isolated.

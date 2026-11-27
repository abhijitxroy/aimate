# Recurrence prevention

| Incident | Cause | Prevention | Validation |
| --- | --- | --- | --- |
| Jira redirected and Jenkins received proxy-denied responses after restart | An inherited proxy skipped the launcher's Windows PAC direct-route checks | Always refresh direct routes for saved service URLs; retain explicit proxy values and existing bypasses | Repeated-start, inherited HTTPS proxy, ALL proxy, opt-out and resolver-error tests |
| Askbar heartbeat was too faint | Opacity-only animation was hard to see | Visible red up/down wave with a moving trace; no editor movement | Browser checks cover geometry, animation, completion/cancel, off switch and reduced motion |
| Resumed source reading crashed | Restored list ranges were sorted together with new tuple ranges | Sort by numeric range endpoints | Persist/reopen/reread/finish regression preserves existing checkpoints |

The proxy-routing module is `tools/proxy_routing.ps1`, registered by
`run_aimate.ps1`. `AIMATE_PROXY_ROUTING=0` disables its automatic routing.
It preserves TLS verification and service authentication. This prevents the
identified routing regression; token expiry and changes to VPN/service access
still need current connection checks.

The matching To-do records retain validation remarks and CI links. A regression
task is reopened when new evidence shows the same behavior has returned.

# Latest Claude choices

For a saved Bedrock connection, Settings and the askbar show one latest version
per Claude family: Haiku, Sonnet, Opus and Fable. Older versions and duplicate
US/Global/foundation routes do not clutter the menus. Version comparison is
numeric; new named Claude families are included when listed by the catalog.
The underlying catalog contains organization presets plus active AWS models.
Discovery is automatic and cached for five minutes in memory. Refresh models
forces a new list. The cache is separated by credentials, region, endpoint and
authentication method; changing a key cannot reuse another account's catalog.
No keys or model-list cache are written to disk.

The askbar's **Claude** group shows one latest model per family, with short
guidance: Haiku (Fastest, low-cost high-volume work), Sonnet (Balanced, daily
work), Opus (High capability, detailed knowledge work), and Fable (Premium).
Names omit route/profile IDs; Connections retains those details.
The active saved Auto policy keeps running internally and appears as its model
name, without a second equivalent model entry. Reply details still show routing.
Choosing another named model explicitly fixes that model for the request.
Other providers fall back to distinct configured model names.

Direct selection chooses the exact model/profile
for that request. It bypasses Auto classification and preserves the configured
Standard/Analysis slots. The selected ID is recorded in the reply's model details
and usage. Exact routes remain internal: an existing selected/configured route
is preferred at the latest version; otherwise choose a listed regional profile,
then Global, then a direct model. Mantle prefers its direct IDs.
Saved Standard/Analysis settings are never automatically upgraded.
An older configured model remains available through the existing slot/custom
field. A previous direct choice absent from the latest list resets to Auto
with a visible notice; choose a model again before sending.

Listing proves catalog visibility, not invocation permission. Save & test verifies
configured slots; direct selections are checked when invoked. Opus/Fable may cost
more. No premium model is invoked just to populate a dropdown, and Auto does not
silently escalate to these models.

Fable works when explicitly chosen in the askbar, configured as a Standard or
Analysis slot used by routing, or selected and verified in a Final PR review
panel. Merely listing Fable does not invoke it. Its current organization preset
is `us.anthropic.claude-fable-5-2`; the key, endpoint, model entitlement and
available premium budget must allow the call. An expired key or denied premium
access is not fixed by choosing Fable. Automated fixtures verify selection and
request wiring, not this account's live Fable entitlement; no premium call is
made just to test the menu.

If AWS listing is unavailable, organization presets and the existing Auto/manual
slots remain usable. Custom model/profile IDs in Settings remain available.
Local AI and other providers keep their own model selection.

Disable automatic listing with `AIMATE_CLAUDE_CATALOG_ENABLED=0`, or remove direct
askbar choices with `AIMATE_MANUAL_MODELS_ENABLED=0`. Both preserve the core editor,
permissions, confirmation checks and saved settings.

Set `window.AiMateFeatures.latestModelChoices=false` to disable the compact
latest-family presentation for debugging. The original catalog and request
validation remain available.

Set `window.AiMateFeatures.cleanModelPicker=false` to restore explicit
Auto/Standard/Analysis labels for troubleshooting. Routing and permissions are
unchanged by this presentation switch.

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

The askbar's **Claude · latest models** group chooses the exact model/profile
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

If AWS listing is unavailable, organization presets and the existing Auto/manual
slots remain usable. Custom model/profile IDs in Settings remain available.
Local AI and other providers keep their own model selection.

Disable automatic listing with `AIMATE_CLAUDE_CATALOG_ENABLED=0`, or remove direct
askbar choices with `AIMATE_MANUAL_MODELS_ENABLED=0`. Both preserve the core editor,
permissions, confirmation checks and saved settings.

Set `window.AiMateFeatures.latestModelChoices=false` to disable the compact
latest-family presentation for debugging. The original catalog and request
validation remain available.

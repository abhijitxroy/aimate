# All Claude choices

For a saved Bedrock connection, Settings and the askbar list organization presets
plus active Claude foundation models and inference profiles returned by AWS.
Discovery is automatic and cached for five minutes in memory. Refresh models
forces a new list. The cache is separated by credentials, region, endpoint and
authentication method; changing a key cannot reuse another account's catalog.
No keys or model-list cache are written to disk.

The askbar's **Claude · direct selection** group chooses the exact model/profile
for that request. It bypasses Auto classification and preserves the configured
Standard/Analysis slots. The selected ID is recorded in the reply's model details
and usage. US, Global and foundation routes stay distinct.

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

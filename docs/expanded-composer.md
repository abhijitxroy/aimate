# Expanded askbar

Click the diagonal-arrow icon at the askbar's top right to expand the editor.
Click it again, or press Escape, to restore the compact view. The same editor
stays mounted: draft text, formatting, selection and attached files are retained.
Large tables and multiline inputs have more room; this does not change upload
limits or the model's context limit.

The view follows the current theme, contains keyboard focus while expanded,
and restores background controls when closed. It works with the inline editor
and the plain-text fallback. Expansion is temporary and is not saved to chat
history or applied to another device.

Disable independently with `window.AiMateFeatures.composerExpand = false` before
the module loads. The normal askbar and all existing controls remain usable.

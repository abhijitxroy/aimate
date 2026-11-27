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

## Reply glow

A visible, thin soft-red border gives two gentle heartbeat pulses followed by a
quiet pause while the visible chat prepares its reply. The cycle lasts three
seconds and never flashes to darkness. Beige uses a darker red for visibility.
It stops on completion, cancellation, error or navigation to an idle chat.
File imports alone do not trigger it. Reduced-motion preferences use a steady
border; hidden tabs pause the effect. Only opacity animates, without flashing or
moving gradients.

Turn it off in **Appearance → Reply border light**. This is a browser preference,
like the selected theme; it persists on reload and is not part of the portable
user-data backup. Set `window.AiMateFeatures.composerGlow = false` before loading
the module to remove the effect and its setting independently.

## Compact message rail

Markers sit vertically centered in the left chat gutter. Hovering or focusing
a marker widens its line; neighbouring lines taper smoothly toward their normal
size. This changes only the marker drawing, so the chat content does not move.
The preview, click-to-jump and bookmark controls retain their existing behaviour.
Escape or moving away clears the preview and hover emphasis. Reduced motion
disables the width transition.

# Expanded askbar

While AiMate works, the red border includes a pulse wave across its upper edge.
The bright trace follows repeated up/down peaks every 2.4 seconds; the editor does
not move. The wave disappears on completion, cancellation or switching to an
idle chat. Appearance → Reply border light turns both effects off. Reduced motion
shows a steady wave instead of animation.
Choose **Heartbeat colour** in Appearance to change the pulse and border colour.
**Default** restores the current theme's red. The colour is saved in this browser,
like the theme and border-light switch; it is not an AI connection or server setting.

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
border and wave; hidden tabs pause the effect. The border changes opacity and
the bright trace follows the small wave; neither effect moves the editor.

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

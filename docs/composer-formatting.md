# Message formatting

The askbar shows **B, I, U, colour, lists and code** by default. **More** opens headings, paragraphs, indentation, horizontal rules, tables, quotes, panels and wrapping. Select text and choose a format; a live preview opens automatically. Ctrl/Cmd+B, I and U also apply formatting.

Formatting is stored as portable Markdown text, so copying/exporting/editing retains the original source. Underline uses `++text++`; colour uses `[colour:#79baff]text[/colour]`. Bold, italic, underline and colour can be combined on the same text. Code fences keep all markup literal. The editor shows source; the preview shows its formatting.

The editor grows with multiline text, including generated warnings, tables and code. It reveals the inserted text automatically; long messages scroll within a bounded editor so the send controls remain available. Clearing the editor returns it to its compact height.

Type `---` on its own line and press **Shift+Enter** to create a visible
horizontal rule and continue typing directly below it, without extra blank
rows. It is saved as the equivalent Markdown `***` so preceding text cannot
turn it into a heading. Code blocks keep literal dashes.
Undo restores the typed line. Disable this shortcut and its inline decoration
with `window.AiMateFeatures.horizontalRule=false`; normal Shift+Enter still works.

Pasted prose removes empty bullets and repeated blank lines, and closes extra
spacing between list items. Paragraph breaks stay readable. Fenced/indented code,
JSON, uploaded files and large clipboard attachments keep their contents.
Set `window.AiMateFeatures.pasteCleanup=false` to disable this optional cleanup.
Formatted user messages use Markdown layout rather than displaying the
renderer’s HTML line breaks as extra empty rows. Lists stay compact; separate
paragraphs, plain-text line breaks and literal code spacing remain readable.
Existing saved messages also benefit without rewriting their stored text.

After a bold/italic/underlined/coloured word, collapse the selection with Right
and press Space to continue in plain text. The space is inserted outside the
closing formatting markers so the word stays styled and markers stay hidden.
Spaces inside a word or literal code are unchanged. Undo remains available.
Disable this optional boundary behaviour with
`window.AiMateFeatures.inlineFormatBoundary=false`.

Blue buttons indicate the format at the current caret/selection. Moving into plain text clears the relevant highlight. Preview, Wrap and More show their actual on/open state. Bold, italic and underline can be toggled off without removing other inline formats. Insert-only actions such as paragraph breaks and outdent do not pretend to be persistent modes.

**Foreground** applies the chosen text colour. Choosing a different colour
replaces the existing one; choosing the same colour again resets the selection
to default text colour. Repeated clicks do not nest tags. Existing nested colour
wrappers are flattened when updated, keeping other text and formatting intact.

Raw HTML, arbitrary CSS and embedded remote images remain disabled. Colour values accept only six-digit hex codes. Advanced options start collapsed; none of the formatting buttons submits a request. The editor retains Markdown source alongside its rendered preview.

The feature lives in `app/static/composer_ui.js`, with a pure selection inspector in `app/static/composer_formats.js`. Set `window.AiMateFeatures.composerFormatting = false` before loading it to disable formatting authoring while retaining the normal askbar, attachments and saved-message rendering. Without the optional inspector, ordinary format insertion still works; selection indicators and inline toggling fall back to basic authoring.

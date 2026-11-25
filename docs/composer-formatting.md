# Message formatting

The askbar shows **B, I, U, colour, lists and code** by default. **More** opens headings, paragraphs, indentation, horizontal rules, tables, quotes, panels and wrapping. Select text and choose a format; a live preview opens automatically. Ctrl/Cmd+B, I and U also apply formatting.

Formatting is stored as portable Markdown text, so copying/exporting/editing retains the original source. Underline uses `++text++`; colour uses `[colour:#79baff]text[/colour]`. Bold, italic, underline and colour can be combined on the same text. Code fences keep all markup literal. The editor shows source; the preview shows its formatting.

The editor grows with multiline text, including generated warnings, tables and code. It reveals the inserted text automatically; long messages scroll within a bounded editor so the send controls remain available. Clearing the editor returns it to its compact height.

Blue buttons indicate the format at the current caret/selection. Moving into plain text clears the relevant highlight. Preview, Wrap and More show their actual on/open state. Bold, italic and underline can be toggled off without removing other inline formats. Insert-only actions such as paragraph breaks and outdent do not pretend to be persistent modes.

Raw HTML, arbitrary CSS and embedded remote images remain disabled. Colour values accept only six-digit hex codes. Advanced options start collapsed; none of the formatting buttons submits a request. The editor retains Markdown source alongside its rendered preview.

The feature lives in `app/static/composer_ui.js`, with a pure selection inspector in `app/static/composer_formats.js`. Set `window.AiMateFeatures.composerFormatting = false` before loading it to disable formatting authoring while retaining the normal askbar, attachments and saved-message rendering. Without the optional inspector, ordinary format insertion still works; selection indicators and inline toggling fall back to basic authoring.

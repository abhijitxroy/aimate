# Askbar formatting

Bold, italic, underline and colour appear directly in the editor. Select text
and use the toolbar or Ctrl+B, Ctrl+I and Ctrl+U. Undo restores the previous draft.
Enter sends; Shift+Enter adds a line. Formatting preserves portable Markdown in
saved messages and exports.

Preview is optional, particularly for tables and Info/Note/Warning panels.
Code blocks keep their source text. Pasted HTML is treated as plain text;
screenshots and large text continue through the attachment handler.
Drafts remain limited to 30,000 characters.

The bundled CodeMirror editor runs locally without CDN requests or AI calls.
Set `window.AiMateFeatures.richComposer=false` before application startup to
use the original textarea; other features and permissions remain unchanged.

Frontend dependencies and the lockfile live in `frontend/`. Build with
`pnpm --dir frontend install --frozen-lockfile --ignore-scripts`, then
`node frontend/build.mjs`. Commit the generated bundle and MIT license notices.
Quality CI verifies reproducible output; Security CI audits editor dependencies.
The editor applies its trusted stylesheet through CSSOM to preserve AiMate's
existing Content Security Policy; pasted content cannot supply styles or scripts.

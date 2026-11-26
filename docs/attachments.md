# Attachments

Pasting more than 4,000 characters into the askbar creates a **Pasted text.txt**
card, preserving the complete text and the current question. This works inside
the styled editor's lines as well as the plain editor. Short pastes stay in the
askbar. File-size or import errors appear above it; no part is silently dropped.

Documents accept up to 20 MB each (4 MB with `AIMATE_LARGE_UPLOADS_ENABLED=0`);
images accept up to 12 MB before browser
compression and 4 MB after compression. Six attachments including at most four
images/scanned pages fit a message. Documents can contain up to one million text
characters each and three million together. Pasted text over 4,000 characters
becomes a file card. Full text is encrypted and paged/searchable through
`read_attachment`, with an explicit next offset; it is not stuffed into every prompt.

Supported content: UTF-8 text/code/logs, PDF text (80 pages), DOCX text,
PPTX slide text, XLSX cell values with shared-string resolution and ZIP text entries. Office macros are never
run. Layout, drawings and formulas are not reproduced. Scanned PDFs of up to
four pages are rendered as images for the selected vision model; larger scans
require selected pages. This is model-based recognition, not guaranteed OCR.
Other binaries show a clearly marked size/hash card; their content is not interpreted.

ZIPs are validated before any reads: no traversal/absolute paths, duplicate
case-insensitive paths, links or encrypted entries; at most 500 entries,
4 MB per extracted entry, 20 MB total and a 100:1 compression ratio.
Everything is read in memory; no archive path is written to disk. Nested binary
archives are listed as unreadable entries. Do not claim whole-archive analysis
unless all relevant text pages have been read.

Saved attachment text belongs to its conversation/account. Private attachment
text stays in session memory. Restarted saved chats can read their full attachment
text again. Providers receive the excerpts/pages/images needed for the request.

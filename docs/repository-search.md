# Repository discovery and content search

Two read-only tools search saved GitHub repositories:

- `find_repository_files`: a path glob or filename/path substring.
- `search_repository_text`: a literal string in UTF-8 source, with original line
  numbers and commit-pinned links.

The first read pins the requested/default branch for that turn. Follow the
returned `next` object exactly and keep the same query/path scope. A final page
does not certify earlier pages: combine all pages and their gaps. Search hits are
leads; use `read_github_file` to inspect full source before a review conclusion.

Each search reads at most 20 files and returns bounded excerpts. Sources over
1.4 MB, binary files, access failures and incomplete trees are explicit gaps.
Known credential paths and symlinks are excluded. Narrow `directory` or
`path_pattern` for large repositories. A path glob uses full-path `fnmatch`
semantics, including `*` across directory separators.

Per-turn caches hold at most 24 trees and 8 MB of decoded text; they do not add
another persistent data store. Cached reads recheck access and public-data policy.
All network requests are scoped GETs through the existing connection adapter.
Disable both tools with `AIMATE_REPOSITORY_SEARCH_ENABLED=0`.

Knowledge-repository indexing, domain database queries, reusable incident memory
and benchmark parity are separate open items in `search-quality-plan.md`.

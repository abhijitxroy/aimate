# Conversation and project context

Saved chats retain their full history in local storage. The model receives a
bounded active window plus relevant older excerpts, not the entire database.
Encrypted reference briefs retain recent goals, ticket/PR IDs and source links
across restart. They are generated locally without additional AI calls.

A new chat can reuse matching work in its selected project and nested modules,
and matching My Diary notes. Unrelated projects are excluded from automatic
recall. Explicit continuation references still support selected cross-chat
handoffs. Each account uses its own storage and credentials.

The added context has a 6,000-character budget, source timestamps and provenance.
It is reference material, not instructions or a current-status assertion. Live
facts must still be checked at their source. Identity questions omit this recall.

Editing a message rebuilds its brief from remaining, unsuperseded turns.
Deleting a chat removes its brief and review checkpoint. Private chats do not
persist these records. Portable encrypted backups include the new records.

All saved text remains searchable, including text accompanying images. Briefs
retain a bounded set of recent references; keyword search reaches older work
outside that set. Ambiguous references to multiple old tasks can still require
clarification rather than an invented assumption.

Long Diary values and saved turns have character-paging tools. The model can
read their complete text without losing the middle of an oversized excerpt.
Only readable user/assistant text is returned, not internal tool bodies or image
bytes. Continued chats can resume the original conversation's review checkpoint.

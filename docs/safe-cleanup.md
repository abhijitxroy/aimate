# Safe cleanup

Admin → Safe cleanup previews managed content before confirmation. It can
remove expired evidence snapshots, attachment text whose chat is deleted and
has no remaining saved references/revisions/pending actions, and the previous
diagnostic log if older than seven days.

The server rechecks dependencies against the preview; a changed plan or an
expired five-minute review must be previewed again. Cleanup waits until that
workspace has no answering chats. Administrator/developer access is required;
personal workspace cleanup cannot touch the owner's records.

Live chats and their attachments, My Diary, tasks, vault entries, settings,
keys, database/WAL files, portable backups and arbitrary original user files
are protected. No recursive filesystem deletion is used. Removing database
content does not immediately shrink the database file; no automatic VACUUM
is performed during user work.

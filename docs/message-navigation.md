# Message navigation

The slim rail in the left chat gutter shows one marker per message. Hover or
focus a marker for a text preview, click to jump, and bookmark to existing
Favorites. Up/Down and Home/End move between markers; Escape or clicking outside
closes the preview. The current message and saved favorites have stronger markers.

Previews read only the messages already displayed in the current chat. They do
not fetch other chats, request AI answers or store additional copies. Bookmarks
use the existing saved-message/private-chat checks. Switching chats clears the
previous preview and marker targets. The rail stays hidden in an empty chat and
on screens up to 760 pixels wide.

Optional module: `app/static/message_navigation.js` and its CSS. Set
`window.AiMateFeatures.messageNavigation=false` before scripts load to disable it.
The main chat, composer and Favorites continue to work.

Repository-setting proposals disappear when completed, cancelled, expired or
superseded, including on reload. Only the confirmation status line reports
completion; saved connection details remain in Settings. Failed or uncertain
changes keep their review/diagnostic information. Repeated read errors and recovery
options are collapsed under Activity, rather than repeated after the answer.

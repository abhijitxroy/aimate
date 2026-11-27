# Conversation width

Open **Appearance** at the top right, then choose **Current** or **Wide**.
Current keeps the existing reading width (860 px where space allows). Wide
allows up to 1440 px for prompts, replies and the aligned askbar. On a smaller
screen both fit the available space without widening the sidebar.

Switching preserves the draft, formatting, attachments and saved conversation.
It changes presentation only, without a model call or extra tokens.
The choice is saved in this browser, like the theme; it is not part of the
encrypted workspace backup or synced to another browser.

The optional module consists of `conversation_width.js` and
`conversation_width.css`. Set `window.AiMateFeatures.conversationWidth=false`
before the module loads to disable it, or call
`AiMateConversationWidth.apply("current")` after disabling it. Current remains
usable and disabling the feature does not erase the saved preference.

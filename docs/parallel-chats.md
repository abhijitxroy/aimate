# Parallel chats

Up to three separate chats can answer in one account workspace. Navigate or
start a new chat while another answers; its stream and message nodes retain
their own conversation ID. Opening that chat again restores its live reply.
Stop cancels only the visible chat; sign out cancels all this page's streams.

The server applies the same three-stream bound across sessions for that
workspace. A second request to an already answering conversation is refused.
Completed answers are persisted; cancelling, closing or restarting the app
does not manufacture a saved completed answer. Interrupted provider usage is
tracked as unknown where no final usage report was received.

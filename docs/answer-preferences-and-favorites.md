# Answer preferences and Favorites safety

Say **“Keep your answers short”** or **“Reply only yes/no”** to keep replies brief
in that conversation. **“Explain in detail”** returns to normal detail.
The setting is stored in existing encrypted turn metadata after a completed
reply and survives reopening. A failed or cancelled reply does not save a new
preference. It does not change another chat or user account.
Temporary chats keep the preference only in their session memory; closing or
expiring them clears it together with the transcript.

AiMate starts with a simple gist, then relevant detail when useful. A model may
still fail to follow formatting guidance; this is a tested instruction and
persistence mechanism, not a guarantee about every generated answer.
`AIMATE_ANSWER_PREFERENCE_ENABLED=0` disables the policy without erasing the saved
preference. Quoted code and appended attachment text cannot set it.

Favorites are locked by default on page load and whenever their panel opens.
The top lock enables intentional unpinning. Pinning new messages, opening the
source chat and copying remain available while locked. The API also requires
an explicit `confirm_unpin: true` acknowledgement for removing a pin.
The existing `AIMATE_MESSAGE_FAVORITES_ENABLED=0` switch disables Favorites.

This lock protects against accidental clicks; it is separate from role/access
authorization. A 24-hour recycle bin and retaining favorite snapshots after
chat deletion remain tracked separately. Until those are delivered, deleting a
chat removes its original turns and Favorites references.

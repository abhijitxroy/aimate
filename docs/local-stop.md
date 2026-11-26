# Stop local AI

Open **Connections & settings → AI model → Local LLM · offline**.
Local AI starts **Off** on every page load. Selecting this provider, checking
access, saving settings or an offline notice does not enable it.

**Enable local AI** selects the installed model for this page's next questions.
It does not generate an answer or overwrite saved cloud credentials.
**Stop & disable** switches this page back to its saved cloud connection, cancels
all its local chats, and requests model memory release. Another page/session
using the same model can prevent unloading; the panel reports the actual error.
Other requests and applications are not killed.

Local enable/disable controls appear only in Connections. Offline notices link
there, keep the draft intact and never switch automatically. The askbar retains
its ordinary per-request **Stop**, which also closes local inference at the
backend without saving an unfinished reply.

Controls require a signed-in session, CSRF validation and the local development
deployment on loopback. Cancellation uses the exact session and request ID,
so a late Stop cannot cancel a newer request. No incomplete answer is saved.
Disable this optional module with `AIMATE_LOCAL_CONTROL_ENABLED=0`; ordinary
browser Stop remains available.

Stopping generation reduces its CPU load. Fan speed may take time to settle as
the laptop cools; other processes can also use CPU.

# Stop local AI

**Stop** cancels the selected chat's local request at the backend and closes its
Ollama connection. **Stop & unload**, beside the askbar and in Local LLM settings,
also asks Ollama to release that model's memory and checks the loaded-model list.
It is available while local AI is selected, including when idle.

Another AiMate chat using the same model prevents unloading; stop that chat first.
Other requests and applications are not killed. Selecting local AI again can
reload the installed weights when you ask a question.

Controls require a signed-in session, CSRF validation and the local development
deployment on loopback. Cancellation uses the exact session and request ID,
so a late Stop cannot cancel a newer request. No incomplete answer is saved.
Disable this optional module with `AIMATE_LOCAL_CONTROL_ENABLED=0`; ordinary
browser Stop remains available.

Stopping generation reduces its CPU load. Fan speed may take time to settle as
the laptop cools; other processes can also use CPU.

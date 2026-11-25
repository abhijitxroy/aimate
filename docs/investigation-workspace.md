# Investigation workspace

Open a saved chat's menu → **Investigation workspace**. Choose Ticket → PR → build, PR review or Build investigation. Save the target, checklist and a multiline checkpoint. **Continue in askbar** saves progress and prepares a follow-up; press Ask yourself to run it.

The checkpoint survives restart and follows the chat when moved. Relevant continuation/review/debug questions receive the compact checkpoint in both AI providers. Checklist ticks are operator notes, not verified findings.

Read evidence comes only from actual tool results saved in the same chat's last 50 turns, with at most 40 source links. Links outside current configured scope are hidden. Source timestamp, result fingerprint and explicit page/coverage limitations are shown. A historical read is not proof of current access or correctness; mutable sources must be rechecked.

The workspace uses the account's encrypted database and portable backup. Private/session-only chats do not create durable checkpoints. Its save/continue buttons do not call a model, run code or change GitHub/Jira/Jenkins.

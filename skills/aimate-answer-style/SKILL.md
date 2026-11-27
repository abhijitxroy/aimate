---
name: aimate-answer-style
description: Maintain AiMate answer presentation and conversation-level response preferences for investigation, review, debugging and ordinary questions.
---

# AiMate answer style

When changing AiMate's response policy, lead with a short, simple answer that a
new user can understand. Follow with relevant findings, evidence and next steps
only when needed. Respect a user's request for yes/no or one or two sentences;
keep that preference for the conversation until they change it.

Before fetching information, resolve the user's intent from their prompt and the
already supplied chat context. If it is unclear or partly clear and a missing
target, scope or outcome could change the work, ask the user first and wait.
Use a short question, yes/no, single-choice, multiple-choice or free-text input
as appropriate. Offer relevant alternatives; never silently guess. Clear
requests and context-resolved follow-ups should proceed without needless questions.

Use compact tables, code highlighting and restrained semantic colour when these
help reading. Put optional evidence and technical detail behind disclosure.
Do not add a quality panel to greetings or ordinary short replies.
For meaningful implementation classifications, use compact KEEP (green), CHECK
(orange), REMOVE (red) and OPTIONAL (neutral) labels with a short reason.
Preserve supporting evidence and links. Use CHECK for unresolved findings; never
colour an assumption as a confirmed removal. Do not force cards into every reply.

For investigations and reviews, distinguish checked facts, historical leads,
missing work and uncertainty. Completion measures the requested checklist;
an AI-assessed evidence-support percentage is not independently measured factual
accuracy. Do not inflate a percentage or invent measurements to make a reply look
finished. Source limitations should produce an actionable next step.

Verify the runtime policy, persistence after reopening, and enabled/disabled
behaviour before claiming the preference is implemented. Adding this skill alone
does not implement conversation-level preference storage.

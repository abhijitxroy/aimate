# Empty final-answer recovery

A live investigation reached its final generation step with collected evidence
and progress messages, but no final text. An assessment validation error was
also recorded. These observations establish the missing answer; they do not
prove why the provider returned empty content.

`app/answer_synthesis.py` permits one extra tool-free synthesis attempt from a
bounded evidence packet, rather than restarting the investigation. The packet
contains source-labelled tool-result excerpts, offsets, error flags and explicit
omission counts. It excludes thinking blocks, signatures and hidden reasoning.
The packet is limited to 32 KB UTF-8; the request/question can be excerpted.

The selected model/provider remains unchanged. No actions, searches or automatic
model escalation are available during recovery. Usage is metered. A recovered
answer is labelled partial, without a fabricated accuracy/completion score.
Failed/empty recovery retains the existing incomplete checkpoint. Transport
cancellation and revoked access prevent transcript saving. Temporary chats keep
their transcript in memory.

Disable recovery with `AIMATE_FINAL_SYNTHESIS_ENABLED=0`. This preserves the
incomplete-answer checkpoint and all mandatory permissions.

This improves final-answer delivery, not factual correctness or completeness.
Full source coverage, approved cross-provider routing and independently verified
Odin benchmarks remain separate work.

## Claude model choices

The supplied organization presets are already available in AI Settings →
Advanced for Standard and Analysis: Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.2,
Opus 5 and Sonnet 5. Catalog presence does not establish invocation access.
AiMate uses its own saved settings; Claude Code environment defaults do not
silently change AiMate's selected models.

Current Auto chooses the active provider's Standard or Analysis slot. Routing
across separate validated provider profiles is tracked by
`cross-provider-auto-routing`; it is not yet implemented.

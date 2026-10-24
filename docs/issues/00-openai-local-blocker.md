# Diagnose local OpenAI failures before continuing quality work

The reported Windows checkout was bc49d59 (PR #4). Budget reservations, actionable provider errors
and final-download refresh fixes landed in PR #5, merged as b8fa084. Restarting Streamlit without
pulling does not install those fixes.

A live cloud diagnostic on the larger saved evidence library completed generation and all three
reviews, then exhausted the default 250000-token budget before revision. Four completed calls
reported 115706 tokens total; conservative reservation for another request exceeded the remaining
allowance. This is distinct from authentication failure. A follow-up diagnostic uses 500000.
Do not silently raise users' configured spend limits or claim a local Windows test was performed.

Local steps: stop Streamlit, `git pull --ff-only origin main`, confirm b8fa084 or later, restart,
and inspect the specific current error. For this larger profile, explicitly select a 500000-token
budget if running two revision cycles. Privacy-preserving input compaction is a follow-up opportunity.

The 500000-budget follow-up completed both revision cycles with four initial cached stages.
It stopped normally at the revision limit as needs_review; factual objections still block final
export. The separate composition-plan synthetic live run completed with zero final factual
errors (50556 reported tokens, no cached calls). Neither result is a writing-quality benchmark.

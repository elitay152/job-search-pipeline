# Plan application composition before generating prose

Problem: atomic evidence records can become isolated fragments instead of a readable resume and letter.
Add a persisted plan with ordered role sections, compatible evidence themes, target bullet counts,
and explicit purposes for cover-letter paragraphs. Give the plan to generator and reviewers.

Acceptance:
- Plan groups facts by their employment scope and project; unrelated employers are never combined as one experience.
- Every planned theme retains eligible evidence IDs; no new personal fact is created during planning.
- Shared or ambiguous role placement is explicit rather than guessed.
- Letter plan covers role relevance, supported examples and a concise close; no ledger-like metric dump.
- Existing factual gates and bounded revision remain enforced.
- Test grouping, scope ambiguity, plan persistence and generator/reviewer delivery.
- Compare live synthetic output before claiming improvement in writing quality.

Reference: ai-job-search application workflow and cover-letter composition checklist (MIT).

Implementation on `feat/composition-quality`: `composition.py` builds and persists role-scoped themes
and paragraph purposes; generator and reviewers receive the same plan. Cross-employer records are
flagged for clarification. Synthetic tests cover scope, uncertainty, ordering and stage delivery.
This organizes evidence but does not yet establish a measured improvement in writing quality.

Live synthetic verification: run 354da532-56f8-4718-a64b-8d4c1bd73dd9 completed two revision cycles,
all reviewer stages, and zero final factual errors. It remains an unapproved draft.
Human preference/editing-effort comparison is pending.

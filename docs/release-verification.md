# Release verification — 2026-10-24

This reviews the six issue specifications in `docs/issues`. The user created GitHub issues,
but GitHub's issue API is inaccessible from this workspace (403). Issue numbers and closure
states have not been independently verified; do not automatically close all GitHub issues.

| Specification | Implemented behavior | Verification / remaining work |
|---|---|---|
| 00 OpenAI failure | Review fields constrained to valid ID namespaces; bounded correction supplies valid IDs; safe saved failure explanations | Uploaded audit identified employment/passage IDs in evidence fields. Regression schema checks and live synthetic verification; personal failed run not regenerated. |
| 01 Composition | Role-scoped evidence themes and paragraph purposes delivered to generator/reviewers | Grouping, scope, delivery tests. Human preference comparison remains unmeasured. |
| 02 Content quality | Configurable presentation warnings and missing-content checks feed bounded revision | Synthetic fragment, repetition, chronology and section regressions. No claim of human-rated writing improvement. |
| 03 Readiness | Commit/version, key presence, explicit synthetic connection checks, budget explanation, output limits, separate app states, refreshed approved downloads | UI/transport regressions; live OpenAI generator and recruiter readiness calls passed. Windows CI configured, not executed in this Linux workspace. |
| 04 Fit report | Company/role history labels; requirement excerpts, priority, evidence and passage links; gaps/constraints and judgment sources explicit | Named-run/report regressions and existing persistent-follow-up UI tests. Lexical matching remains approximate. |
| 05 Layout | Optional local PDF conversion, page/geometry heuristics, version/hash-bound visual-review acknowledgement | Real synthetic PDF geometry tested; converter integration simulated. LibreOffice unavailable here, so actual DOCX-to-PDF conversion and visual inspection remain unverified. |

Export regression: hidden XML-invalid controls are caught before revisions finish. Draft-only
replacement preserves original source data; final approval still blocks invalid text. Audit
JSON downloads independently of DOCX conversion. UTF-8 file I/O is explicit for Windows.

No personal facts, API credentials, uploaded audit or generated application files belong in this
public change. Live synthetic requests used fictional fixture data. Anthropic was not retested.
The benchmark uses deterministic mock models and does not measure live writing quality.

## Results from this workspace

- `python -m pip install -e '.[dev,layout]'`: successful on Linux/Python 3.12.
- `python -m pip check`: no broken requirements.
- `pytest -q`: 108 passing tests, including Streamlit interactions, provider contracts,
  revision regression, optional renderer absence, PDF geometry and artifact hash binding.
- `career evaluate`: six synthetic benchmark cases completed across A/B/C; explicitly labeled
  mock results. No human preference or editing-effort measurements were supplied.
- Live OpenAI/gpt-4.1 readiness: generator and reviewer structured requests passed using
  fictional evidence (921 and 1,606 total reported tokens respectively).
- Initial full live synthetic run: all reviewer stages completed but a later presentation
  revision regressed from a factually passing version to five validation failures. Final export
  remained blocked. This exposed a revision-selection bug rather than a provider failure.
- Fixed regression handling: retain every attempted version, restore the last fully reviewed
  passing packet when a later edit introduces errors, then revalidate the restored packet.
  Do not approve automatically or waive any findings on the rejected packet.
- Final live synthetic run `3eb8d330-2f3d-4251-9644-e9cd7af10d29`: all three reviews passed,
  zero final validation errors, one revision attempt, stopped by factual-regression rollback.
  Reported 35,792 tokens and 28.26 seconds. Synthetic-only approval and final DOCX export were
  exercised; exported text had neither a draft label nor internal evidence IDs. This validates
  workflow behavior, not human writing preference or a real applicant's final approval.

Relaunch gate: merge the branch and check the Windows/Ubuntu CI matrix. PDF rendering remains
optional; actual LibreOffice conversion and visual review should stay open until performed.
Do not claim the user's larger private application has been regenerated or approved by these tests.

## Windows CI cleanup correction — 2026-10-25

The supplied Windows traceback identified `test_evaluation`: temporary SQLite files were still
open when `TemporaryDirectory` attempted deletion (WinError 32). Linux allowed the unlink,
so the earlier Linux runs did not expose the leaked handles. Evaluation now uses a closing
`Store` context for each case, including exceptions in generation or judging. Regression tests
retain all connection references and verify they are closed before temporary-directory cleanup.
The updated Linux suite passes 111 tests; the evaluation CLI also completes. Windows CI must
rerun to confirm the reported platform failure is resolved.

## Job intake and work-history correction

Unbulleted job descriptions could yield no extracted requirements. Selection then retained
education/publications/standalone skills while omitting employment evidence. Intake now handles
plain qualification and responsibility lines, numbered lists and Markdown headings, retaining
original excerpts. Empty extraction displays an explanation rather than zero-match counters.

Selection independently anchors confirmed employment scopes, ranking their evidence by relevance.
A deterministic completeness gate blocks approval/final export when a confirmed employment scope
has no rendered resume passage. An unsupported target skill remains a gap and cannot erase real
career history. Uncertain employment evidence is not forced into the document.

The top-level cover-letter checkbox is persisted through planning, generation, review, and export;
resume-only runs return no letter claims or files. Default and older runs continue to require both.
The CLI provides `--resume-only`.

Validation: 124 automated tests passed on Linux, including multiple employment scopes, empty
retrieval, unsupported target tools, education/publication-only output, plain-text counter updates,
resume-only approval/export and existing factual gates. Mock evaluation CLI completed. Windows
CI must verify the branch after push; personal application output was not regenerated here.

Live OpenAI/gpt-4.1 synthetic verification also completed: two requirements recognized from plain
text, employer and Professional Experience rendered, zero cover-letter claims when unselected,
and zero final factual-validation errors. It stopped as an unapproved draft after restoring the
previous passing version following a revision regression (27.46 seconds). This is a workflow
check using fictional evidence, not a human assessment of writing quality.

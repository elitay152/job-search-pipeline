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

## Saved baseline and resume-file intake

- Resume job headers and chronology now come from a versioned saved employment baseline,
  including supported legacy imports; model bullet selection cannot remove a job header.
- Missing job bullets are restored verbatim from source records before reviews, with evidence
  references and restoration IDs retained in the manifest. Missing source bullets stop generation
  before a model call. Export blocks empty job sections, including older incomplete runs.
- Shared-role source statements remain explicitly labeled as shared under each referenced role;
  they are not silently attributed as exclusive work for one role.
- DOCX/TXT upload and CLI intake extract structured history through the selected provider, validate
  exact source wording/date/role placement, retain original uploads locally, and merge without
  deleting saved history. Conflicting dates are not silently overwritten. PDF/OCR is unsupported.
- Direct entries, uploaded resumes, explicit backup imports and saved gap answers are authoritative
  `user_provided` inputs, without a redundant confirmation checkbox. Existing confirmed inputs remain
  usable. Unknown ownership stays unspecified on import; it is not inferred from a job title.
- Factual review remains output-versus-input checking. User review of the final application is still
  required. No claim is made that the application independently verifies a person's career facts.

Live synthetic OpenAI intake checks: a TXT fixture extracted one job and its bullet plus education
and training; a DOCX fixture with two jobs extracted both jobs and source bullets. The two-job import
then completed a deterministic mock pipeline with both employers present and zero validation errors.
These are live extraction checks, not a new live-generation quality benchmark. Personal files were
not sent in these checks. Windows CI must run on the pushed revision.

Final local verification for this change: 139 tests passed on Linux; `git diff --check` passed.
The synthetic mock evaluation CLI also completed. Windows CI is pending after push.

## Intake error correction

The saved private profile had four older employment records without linked source accomplishments.
Six original bullets were recovered from the previously uploaded master resume and added only to
the private evidence backup; existing records, titles and dates were preserved. Every saved job in
that repaired backup now has source bullets. No personal data was added to this public repository.
The UI now identifies missing jobs before generation rather than showing an unspecified blocker.

Resume intake now asks the model to select numbered source lines instead of retyping paragraphs.
Source text is reconstructed locally, preserving punctuation and qualifiers. A single bounded
correction handles invalid selections. Technical projects and summaries have explicit extraction
fields, avoiding false omission failures for project bullets. Source wording, role placement and
unsupported-date guards remain in place.

Live OpenAI validation against the previously uploaded master DOCX completed with seven jobs,
26 employment statements and four project statements. This tested extraction; it did not overwrite
existing corrected career facts or claim a new final application was generated. Synthetic tests
cover punctuation, multiline headers, invalid line IDs, correction bounds and project preservation.

Final local checks: 142 tests passed on Linux, and `git diff --check` passed. Windows CI is pending
on the pushed branch. The corrected private backup was pushed separately from application code.

## Bounded evidence-review responses

Live evidence review now uses groups of at most four claims (smaller with a lower per-call
output cap). A truncated group splits into two, down to a single claim; incomplete results
never authorize export. Each group retains its cited source records and undergoes the existing
review contract checks. Combined receipts must cover the complete resume and letter. Recruiter
and voice editors still see the whole document. Batch statuses and accepted responses are saved
in the review history; all calls remain subject to the configured budgets and stage cache.
Successful provider calls consume actual request counts, not their unused transient-retry allowance.
Unknown failed-attempt token usage is still conservatively reserved.

The evidence auditor receives the active factual policy explicitly and does not receive professional
writing-style instructions. In model-reviewed mode, semantic equivalence is permitted without
weakening metric, scope, technology, source-quote or date checks. An initial live paraphrase check
exposed over-rejection of equivalent verbs; the final prompt separates this from strict copying.

Validation: 149 tests passed on Linux, including synthetic truncation/splitting, complete receipts,
single-claim failure, approval blocking, persistent negative findings and call-budget exhaustion.
A live GPT-4.1 review of a seeded synthetic packet (12 resume claims and three letter claims)
completed four evidence batches plus recruiter/voice reviews. The final paraphrase check returned
15 assessments, zero factual validation errors, and draft status in 13.3 seconds, using 24,325
reported tokens. This tested live review, not new document generation, a human writing-quality
benchmark, Windows execution, or a new live Anthropic run. No personal career data was sent in
these checks. The earlier practical-constraint follow-up removal is included in this branch.

## Real-resume acceptance check — incomplete final live verification

On 2026-10-25, testing used the user's uploaded master DOCX, previously corrected private career
history, approved writing profile, and a real pasted job description. No personal documents or
career facts are included in the public fixtures or this report.

The actual Streamlit upload control saved all seven source jobs with bullets, and a fresh app
session reloaded the history. Full live OpenAI runs were then exercised through Create my draft,
Review & download, and Prepare documents. DOCX files were opened with python-docx and checked for
source job headings, education, publications, draft labels, and absence of internal evidence IDs.
Several earlier runs completed, but manual reading found errors not caught by the initial automated
checks. Therefore those runs are not treated as final acceptance of the revised implementation.

Issues found and addressed:
- Excessive duplicated source context and input-byte token reservations exhausted otherwise usable
  budgets. Shared context is now losslessly referenced; OpenAI token estimates use its tokenizer.
- Reviewers retyped quotations incorrectly. They now select numbered literal source excerpts; the
  backend resolves text and shared-source links without inventing quotes.
- Unchanged user-supplied facts were unnecessarily re-questioned. Exact source comparisons and
  model-reviewed paraphrases now have separate receipts. Unknown ownership is not a negation of
  explicit source actions.
- Shared employment accomplishments were printed twice; education/publication anchors could be
  dropped or rewritten. Rendering now preserves the baseline and groups same-employer shared work.
- A reduction became a usage level, and one uncertainty qualifier was applied to a different metric.
  Metric meaning and number-specific qualifiers now have deterministic regression checks.
- Revisions could introduce new errors into passed passages. Source-backed restoration is recorded;
  a later budget stop can return a previously fully reviewed packet, never an unreviewed revision.
- Unicode punctuation was repeatedly escaped through model input. Source text now uses Unicode JSON;
  canonical education/publication text is restored from input before review. Invalid XML characters
  still block approval and are visibly replaced only in labeled draft exports.
- Known factual errors are repaired before paid reviews. A skipped-review receipt no longer crashes
  the readable report.

Latest live attempt: both DOCX download controls worked with no Streamlit exception, but the final
review was interrupted by OpenAI HTTP 429 / `credit_balance_exhausted` (`insufficient_quota`).
Further live calls were stopped. No personal packet was marked approved. The final code includes
an additional tested guard that does not retry exhausted-credit responses. This final code has NOT
completed a new full live run after that provider limit. The application is not declared fully ready
on the strength of unit tests alone. The exact generated drafts and unresolved editorial findings
are stored only in the user's private repository.

Final local checks: 166 tests passed on Linux; `git diff --check` passed. Tests use synthetic data
and do not download tokenizer assets. Tokenizer and regex dependency metadata support Python 3.11.
Windows execution, live Anthropic calls, browser file-save behavior on the user's machine, and Word/
PDF visual pagination were not verified here. LibreOffice is unavailable. Live testing consumed API
credits; exact charges are unavailable because pricing was not configured in the run settings.

### Follow-up without paid requests (2026-10-25)

The remaining saved draft was replayed against local checks. All three saved versions now
flag CI/CD authorship inferred from deployment use, and training topics inferred from unrelated
optimization/deployment work. These checks run before model review and during assessment validation;
rewriting the statements does not waive source support. Generation instructions also distinguish
these scopes and request concise bullets and connected cover-letter paragraphs.

A new Streamlit acceptance test uses the actual OpenAI SDK with a synthetic HTTP transport. It
exercises Create my draft, correction of unsupported initial claims, truncation and batch splitting,
all three review roles, draft preparation, explicit approval, and final resume/letter DOCX output.
Both final documents contain the intended corrected text and no DRAFT label or evidence IDs. A
fresh UI session keeps saved history without another provider request. This verifies application
behavior with simulated responses; it does not measure a live model's writing quality.

The suite blocks real HTTPX transports and tokenizer downloads, so an accidentally unmocked model
call fails locally rather than charging the account. Local result: **177 passed**, Linux;
`git diff --check` passed. No live provider requests were made in this follow-up. Model names and
per-application request/token/revision limits are visible beside the draft action. Those limits
are not a dollar estimate or a global account spending cap.

The earlier live acceptance limitation still applies. Windows execution and visual Word/PDF
pagination remain unverified. Changes are prepared for merging; no new personal packet has been
approved and the old draft artifacts remain explicitly unapproved.

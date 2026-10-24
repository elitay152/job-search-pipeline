# Running the actual tailoring and adversarial review pipeline

An editorial document written outside `career run` is not a pipeline result. Only runs in SQLite,
with stage status, reviewer receipts, version hashes and validation outcomes, establish which stages
executed. Mock reviewer receipts prove software execution, not live-model judgment or writing quality.

## Personal evidence and month-only dates

Employment dates accept `YYYY-MM` or `YYYY-MM-DD`. A month string stays a month string in snapshots;
no first/last day is manufactured as a career fact. End-before-start is rejected when the ordering
is established by the supplied precision. Explicit `employments` allow official/display titles and
multiple roles to be retained separately. An evidence record can cite multiple `employment_ids`
without claiming every action happened independently in each role.

Confirmed factual statements and user-approved application wording are distinct:

- `sources[].status=user_confirmed` establishes eligible facts, not approval of a packet.
- `confirmed_statements` contains factual source text; `approved_wording` may contain separately
  approved phrasing. Both are exact support anchors for the current conservative factual gate.
- `fact_details` and source excerpts preserve context/qualifiers for the evidence auditor.
- In strict mode, new paraphrases fail. In live-reviewed mode, structured source-grounded assessments
  and independent guards are required; ungrounded wording, invented numbers or unknown references fail.
- Raw sources with uncertain verification remain excluded from generation and explicitly listed
  as source-confirmation gaps. In particular, a source-only publication is not silently verified.
- Review of the final packet remains a separate user action. No importer or mock pass approves it.

For live-supported paraphrases, set `Settings(reviewer="anthropic", factual_mode="model_reviewed")`.
CLI/UI select that mode by default when a live reviewer is chosen; `--factual-mode strict` remains
available. The evidence reviewer must supply an assessment for every paraphrased claim, exact quotes
from every cited record, and explicit checks for wording, metrics, technology, ownership, dates/titles.
The gate validates quote authenticity, reference coverage, numeric/unit consistency, qualifiers,
known-tool changes and common scope upgrades before accepting the model assessment. Missing or
negative assessments keep the claim unsupported. Mock reviewers cannot authorize this mode. A
positive model judgment is **not** a mathematical proof; final human review and evaluation remain
necessary. Unknown semantic errors outside these checks remain a limitation.

For a private intake folder produced during evidence collection:

```bash
.venv/bin/career import-intake \
  --intake private/resume_intake \
  --output private/career-v1.json
```

The supported intake files are `career.evidence-draft.json` (records and confirmed role metadata)
and `user-confirmations.json` (scoped `confirmed_facts`, record references and source statements).
The converter creates a new evidence snapshot and import report, refuses to overwrite an existing
snapshot, normalizes only the structured confirmed fact fields, and **ignores unapproved
candidate_wording**. It does not mine academic style samples for career facts. Review the converted
input and pending-record report before using it. No private input ships with this repository.

## Run and inspect all stages

```bash
.venv/bin/career --db private/runs.sqlite run \
  --jd private/job.txt \
  --career private/career-v1.json \
  --style private/writing_style/approved-v1 \
  --generator mock --reviewer mock \
  --report private/review-report.md

.venv/bin/career --db private/runs.sqlite inspect RUN_ID \
  --output private/inspect-report.md

.venv/bin/career --db private/runs.sqlite export RUN_ID \
  --career private/career-v1.json --draft --output private/artifacts
```

Optional `--seed-packet private/existing-packet.json` reviews/revises an existing structured Packet
instead of generating the first candidate. It never bypasses factual gates. The Packet schema is
`{resume: Claim[], cover_letter: Claim[], skills: evidence_id[]}`; every claim has an ID, factual
text, and evidence IDs. This is useful for testing a deficient earlier packet, not a hidden manual
replacement for generation. Saved initial and revised candidates remain inspectable.

The renderer uses evidence kinds (`experience`, `project`, `education`, `publication`, `skill`) to
place claims in sections. Skills are rendered from referenced technology records into one categorized
section with portfolio, academic and training labels. Titles/dates come from the input snapshot,
not model-authored headings. Education and publications are explicit document anchors; relevant
employment groups receive a minimum supported bullet count capped by available evidence.

Every version receives these separate reviewer calls with the configured reviewer model:

1. **Evidence auditor:** challenges factual wording, dates, titles, metrics, technology and ownership.
   It must account for every claim ID. Deterministic support checks run independently and cannot
   be waived by the model. Model factual errors also block approval, even if exact-wording checks pass.
2. **Recruiter reviewer:** challenges supported requirement coverage, ordering, role depth, skills,
   and missing sections. Missing-section objections cite a section/evidence rather than a nonexistent
   passage. Genuine experience gaps are separate from fixable presentation problems.
3. **Voice editor:** reviews the explicitly loaded approved profile, repetition, inflated language
   and keyword insertion, without authority to change facts.

Findings retain role, severity, passage/section/requirement target and evidence references. Different
roles have different system prompts and separately cached calls. The generator sees actionable
findings for revisions but is still constrained by factual support. Strict/mock runs do not claim
the live semantic-audit capability was exercised. Default two cycles, hard maximum
three; repeated/oscillating candidates stop early. Errors, remaining findings and stopping reason
are recorded. A candidate is saved *before* reviewers run, so provider failures do not erase it.

## Live model configuration

Set `ANTHROPIC_API_KEY` securely in environment settings; never put its value in a command, Git,
logs or chat. Then select live providers and models explicitly:

```bash
.venv/bin/career --db private/runs.sqlite run \
  --jd private/job.txt --career private/career-v1.json \
  --style private/writing_style/approved-v1 \
  --generator anthropic --reviewer anthropic \
  --generator-model YOUR_ACCESSIBLE_MODEL \
  --reviewer-model YOUR_ACCESSIBLE_REVIEW_MODEL \
  --report private/live-review-report.md
```

An SDK tool-result schema constrains both generation and reviewer responses. Up to three attempts
handle transient failures; malformed results or incomplete reviewer receipts do not silently pass.
Token budgets reserve conservative input/output/retry bounds and settle successful calls using
reported usage. Failed-call usage/cost is unavailable. Default call budget is 48 retry reservations,
enough for generation/revision plus three review roles through the hard revision maximum; tokens
and credentials can still stop a run. Rates must be configured to estimate live cost.

Live calls send the job, selected evidence and factual context, generated packet and approved style
guidance to the provider. Raw writing samples are not loaded. A saved secret requirement is not a
configured key or a successful call. No live-model efficacy is established by mocked SDK tests.

## UI and approval

The UI can load a local evidence JSON path, select a private approved style directory, configure
model/budget settings, display all per-version reviewer receipts/findings and revision diffs, and
download packet documents plus an audit report. Mock review is prominently labeled. Historical
previews/approval/export use the saved run's evidence snapshot rather than the current editor contents.

Final approval requires explicit user review, no factual errors and all three reviewers completed.
Incomplete/failed reviews cannot be converted into approval. One-shot benchmark arms also need a
full review run before final export. Source gaps and unresolved suggestions remain visible. A
labeled draft export is available even for a failed review if a candidate was saved.

## Validation boundary

Regression tests start with a deliberately thin synthetic packet missing publications/education and
skills. The pipeline itself detects these problems, revises, runs all three reviews again, and exports
through the same renderer after explicit synthetic-test approval. Other tests cover month precision,
unsupported inventions, failed/incomplete reviews, role-specific SDK contracts without network,
source-only citations, and unapproved candidate-prose exclusion. These are software checks, not
claims of live recruiter judgment, document pagination quality or hiring outcomes.

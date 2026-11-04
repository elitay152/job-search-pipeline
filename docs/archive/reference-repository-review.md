# Reference repository review — 2026-10-24

Scope: static inspection of source, prompts, templates, and license files. No external application,
scraper, authentication flow, or model integration was executed. Popularity and README outcome
claims were not independently verified. External instructions were reviewed as source material,
not executed. No source code or prompt text was imported into this project.

## Sources inspected

| Repository | Inspected commit | License observation |
|---|---|---|
| career-ops-hq/career-ops | dff0d65ec613c5688a080073fa809398d0f1c39a | MIT |
| MadsLorentzen/ai-job-search | e16acee3abdaae57f8026789338a3c6eebf4608b | MIT |
| adrianhajdin/job_pilot | 788baa5784f94264c33780fd051f9d0b17a68f60 | No license file found in the inspected checkout; do not copy code assuming permission |
| sreekar2858/JobSearch-Agent | 1b52cafe923b8b2bd925b0c7a5bf3af75d8518f1 | README advertises MIT, but LICENSE contains GPLv3; resolve before reuse |

## What is worth adapting

### career-ops

- `verify-cv-facts.mjs` validates quantities, tools and attribution against sources. Its handling of
  direct authorship versus coordinated vendor work is relevant to our ownership safeguards.
- `verify-cv-structure.mjs` explicitly distinguishes factual fabrication from omissions/reordering:
  missing company descriptions, missing skills categories and chronological changes. An unsupported
  source layout is reported as unverified instead of a false pass. This addresses our observed
  missing-publication, thin-role and mixed-employer problems.
- `config/profile.example.yml`, `modes/oferta.md`, and `modes/_writing.md` separate preferences,
  assessment and writing rules. Dealbreakers should stay distinct from skill matching.
- Keep our typed evidence IDs and immutable run snapshots; source-text presence alone does not
  establish that a source supports the particular candidate claim.

### ai-job-search

- `.claude/commands/apply.md` requires new confirmed facts to reach persistent candidate sources
  in the same interaction. It treats old tailored CVs as style/structure references rather than
  fresh evidence. Our gap-answer persistence is the right foundation; source consistency and
  propagation tests should include publications and education corrections.
- Its reviewer returns exact old/new passage edits plus broader narrative objections. Adapt
  this to claim-ID edits with an expected prior-text hash, evidence links and a stated reason.
  Reject stale patches, re-audit changed claims, retain our two-cycle default and three-cycle cap.
- `.claude/skills/job-application-assistant/06-cover-letter-templates.md` describes an opening,
  relevant examples, a role/company connection and a concise close, plus a forward-looking
  checklist. This is much stronger composition guidance than merely asking for a coherent letter.
- `/apply` requires rendered-page inspection, including orphaned headings and page overflow.
  DOCX text assertions cannot substitute for a rendered-layout check. Add optional rendering
  with an explicit unavailable status if the renderer is absent.
- Its evaluation includes behavioral/culture and career-motivation scores. Do not infer those
  from writing samples or adopt its automatic hard stops for undeclared attributes. Ask the user
  about practical constraints; missing evidence remains unknown.

### JobPilot

- `components/find-jobs/JobFilters.tsx` provides company/role search and sorting. Its named job
  inventory is a useful UX model for our UUID-centric run history. Link runs and document versions
  to stable job records with company, role, source, timestamp and status.
- The inspected `app/api/agent/find/route.ts` imports Adzuna search and asks GPT-4o for scores,
  explanations, matched skills and missing skills. That route is not evidence of a validated
  advanced matching algorithm or of authenticated LinkedIn discovery.
- `app/api/resume/generate/route.tsx` composes profile-based summary/bullets, renders a PDF and
  stores it. The inspected prompt does not receive a particular job description. JSON parsing
  plus a TypeScript cast does not establish factual support. Borrow presentation patterns,
  not its factual assurance or generic resume generation as our tailoring architecture.
- Its autonomous application/browser infrastructure is outside our current scope.

### JobSearch-Agent

- `src/agents/coverLetter_writer_adk.py` explicitly orchestrates draft, critic, fact-check,
  revision and bounded iteration. `src/prompts/cover_letter_prompts.py` separates composition,
  criticism, factual checks and revision. We already have separate review roles; improve their
  contracts and composition inputs rather than adding a second orchestration framework.
- `src/utils/document_database.py` relates documents to job IDs and records generation metadata.
  Useful model for stable application records; preserve our versioned artifacts instead of
  replacing them with a single mutable generated document.
- A prompt requesting fact checking is not itself an entailment validator. We should retain
  quote verification, provenance and deterministic factual gates.
- Neither the README nor this inspection proves that its scraping avoids blocks. Scraping,
  credential-sharing and automated applications are not needed for our resume workflow.

## Recommended implementation order

1. **Composition plan before prose.** Select a few evidence-backed themes per role, group compatible
   atomic facts into complete accomplishment bullets, and give the letter an explicit paragraph
   purpose. Each planned passage retains evidence IDs and ownership boundaries. Keep shared,
   multi-role evidence scoped; do not automatically assign it to one employer. Acceptance: no
   raw ledger fragments or unexplained scientific notation in live output; no unsupported tools,
   realized outcomes or ownership; the cover letter explains relevance rather than listing metrics.
2. **Separate factual, content and layout checks.** Add chronological-role ordering, accidental
   cross-employer grouping, missing selected sections, excessive fragmentation/repetition, numeric
   display and letter structure checks. Presentation preferences should be configurable warnings,
   while factual errors continue blocking final export. Acceptance: regression fixtures reproduce
   the user's weak example without embedding personal data in the public tests.
3. **Live readiness and product states.** Check credentials/model access with synthetic input,
   show estimated input budget before private generation, and distinguish practice, generation,
   review-needed, approved and final-export states. Approval must select newly generated final
   artifacts. Recent fixes cover missing-key diagnostics, adaptive retry reservations and stale
   draft downloads; a user-visible readiness test and realistic live benchmark remain future work.
4. **Useful fit report.** Separate required and preferred requirements, direct and transferable
   support, unresolved questions and practical constraints. Link every judgment to the JD excerpt
   and evidence. Current lexical matching should be labeled baseline; any model rubric must have
   explicit reasons and uncertainty. Do not turn a model's 1–5 or 0–100 judgment into hiring odds.
5. **Jobs as durable records and incremental edits.** Save job identity and versions, give the user
   named application cards and one clear next action, and apply bounded reviewer edits to identified
   passages. Later compare versions using actual human editing time and blind preferences when
   supplied, separately from deterministic factual checks and model judgments.

## Evaluation before claiming improvement

Use the same synthetic career/JD benchmark for the existing generator and a composition-plan
variant. Record unsupported claims per factual claim, supported requirement coverage, section
retention and chronology, reviewer-contract failures, revisions, latency, tokens and cost where
known. Add labeled synthetic examples of fragments, mixed employer headings, missing publications
and a cover letter consisting only of metrics. A factual pass is not a writing-quality pass.
Use independent human review when available; do not use the optimizing reviewer as the sole judge.
We have not measured whether these proposed adaptations improve output quality yet.

License handling: MIT adaptations require retaining applicable notices. Do not copy JobPilot code
without establishing permission, or treat JobSearch-Agent's MIT badge as overriding its GPLv3 file.
Conceptual observations here are independently summarized; no third-party implementation was copied.

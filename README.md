# Evidence / Application Studio

A single-user, evidence-grounded job application workbench for data engineering roles. Python + Pydantic + SQLite + Streamlit, with a CLI and editable DOCX exports. **The bundled candidate and job are synthetic.** No scraping, applications, email sending, or autonomous publishing.

The key safety boundary is deliberately conservative: factual claims must exactly match wording explicitly approved in a confirmed evidence record. A valid evidence ID alone does not pass validation. New paraphrases require evidence editing and a new run. This trades prose flexibility for inspectable support rather than pretending an LLM can prove entailment.

## Setup

Python 3.11+ (validated here on Python 3.12). From the checkout root:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/pytest -q
.venv/bin/streamlit run career_pipeline/ui.py --server.headless true
```

`requirements.lock` pins the validated Python dependencies, including test tooling. No database server or credentials are required in mock mode. Run commands from the root so fixture and writing-profile paths resolve. SQLite and output directories are created automatically. Each cloud task already has an isolated checkout; a worktree is unnecessary.

## Synthetic walkthrough

```bash
.venv/bin/career run --jd fixtures/job.txt --career fixtures/career.json
.venv/bin/career history
# Substitute the run ID printed above:
.venv/bin/career export RUN_ID --career fixtures/career.json --draft
# Inspect artifacts/RUN_ID/draft, evidence references and audit.json before approving:
.venv/bin/career approve RUN_ID --career fixtures/career.json --reviewed
.venv/bin/career export RUN_ID --career fixtures/career.json
```

The example selects Python/SQL ingestion and Airflow evidence, retains **estimated** savings, and surfaces Kubernetes and hybrid-location questions as gaps. No Kubernetes experience is invented. Drafts are labeled; final export is blocked until the deterministic audit passes and the user acknowledges review. Approval is bound to packet and evidence hashes. The CLI acknowledgement is an explicit user action, not an automated hiring or quality certification.

The UI supports validated JSON evidence editing and local saving, a requirement map, previews, provenance, findings, revision diffs when present, run history, approval, and DOCX/Markdown/audit downloads. Resume and letter text can be edited in DOCX; edits made outside the app are outside its audit boundary. To use edited evidence, paste it into the editor or provide the local JSON to the CLI. UI preview uses the current evidence editor; exports reject an evidence-snapshot mismatch.

## Architecture and data flow

```text
untrusted JD -> validated ingestion -> excerpt-preserving requirements
             -> tag/lexical retrieval -> evidence coverage map
confirmed evidence + approved profile -> provider -> structured packet
             -> deterministic evidence auditor + recruiter + voice review
             -> bounded revision -> revalidation -> user review -> exports
                               \-> SQLite snapshots, versions, findings, telemetry
```

- `models.py`: employers, official titles/dates, projects, personal actions, ownership, technology usage, qualified metrics, sources, verification, approved wording and prohibited inferences. IDs must be stable and unique. Conflicting dates for the same employer/title are rejected. Unconfirmed evidence is ineligible.
- `pipeline.py`: framework-independent orchestration. Requirement extraction is a transparent line/heading baseline, with required/preferred/ambiguous labels and verbatim excerpts. Location and practical constraints require clarification; no sensitive personal characteristics are inferred. Retrieval is a replaceable protocol, currently tag and lexical overlap. “Direct” means all non-stopword tokens match available evidence text/tags; “transferable” means partial overlap, **not** a semantic certification. Inspect the map for multi-tool or nuanced requirements.
- `providers.py`: provider protocol, deterministic mock and Anthropic adapter. Generator/reviewer settings are separate. Approved style instructions are loaded explicitly. Job descriptions, evidence, and reviewer messages remain data in prompts; generated facts still face a deterministic gate. The model reviewer cannot replace the factual auditor. Recruiter objections must reference a known claim and requirement; voice objections require a known claim.
- `store.py`: SQLite run manifests, input snapshots, version events, rejected revision candidates, and content-addressed stage cache. Cache keys include provider/model, prompt version, settings and full stage payload. Manifests include hashes, schema/prompt/profile versions, model settings, stage latency/status, available usage/cost, revisions, stopping reason, validation, artifact paths and checksums. SQLite contains private content; stdout does not print snapshots.
- `export.py`: Markdown/DOCX renderer uses official employment metadata with separately user-approved descriptive display titles, excludes internal IDs from application files, and writes a separate audit report. PDF is an optional capability stub returning an explicit unavailable result; no rendering dependency is required.

Every generated revision candidate is persisted. The default revision limit is two, hard maximum three. Stop conditions include resolved actionable findings, limit, repeated/oscillating output, and budgets. Experience gaps remain visible and do not trigger endless edits. Factual failures yield `needs_review`, prevent approval/final export, and permit labeled draft previews. Schema/provider failures yield `failed` with the completed stage history retained.

### Evidence authoring contract

Only mark sources `user_confirmed` after inspecting the facts and approved wording. The app does not authenticate source documents or infer missing facts. Approved wording is the explicit human-supported assertion boundary; structured fields provide context, not independent proof. Preserve estimated/expected/realized qualifiers, titles, dates, familiarity versus production use, contribution versus ownership, and education status. Do not approve paraphrases implying leadership, database administration or a completed degree without that evidence. `prohibited_inferences` is available to model context and human review; arbitrary natural-language prohibitions are not a semantic rules engine. The deterministic auditor catches deviations from approved wording, not errors a human has already approved.

## Live configuration

Mock is the default. For live calls set environment variables securely (never commit `.env`):

```bash
export GENERATOR_PROVIDER=anthropic
export REVIEWER_PROVIDER=anthropic
export GENERATOR_MODEL=claude-sonnet-4-5
export REVIEWER_MODEL=claude-sonnet-4-5
# Set ANTHROPIC_API_KEY through your environment's secure settings.
.venv/bin/career run --jd private/job.txt --career private/career.json
```

`TOKEN_BUDGET` and `CALL_BUDGET` configure CLI limits. Python callers can set all `Settings` fields, including maximum output tokens and separate input/output USD-per-million rates. Prices are intentionally not hard-coded: live cost is unavailable unless rates are supplied. Mock usage/cost are zero. Live budget reservations conservatively account for three attempts and byte-based input upper bounds plus maximum output; cached stages consume no new budget. Up to three attempts use short exponential backoff for connection, rate-limit and server errors; authentication and invalid JSON errors fail without unchanged retries. Reservations can stop a run earlier than actual token usage would suggest. Live outputs are not promised to regenerate identically.

The Streamlit provider selectors use the same API key; model overrides and detailed budgets are currently CLI/Python configuration features. **Live Anthropic calls have not been exercised as part of credential-free validation.** A valid key, model access and HTTPS access to `api.anthropic.com` are required. No second provider is included.

## Writing profile calibration

`writing_style/` is a portable package: SKILL.md, versioned neutral profile, labeled optional examples and calibration instructions. The application explicitly loads this skill; arbitrary SKILL.md discovery by Claude Code is not assumed. No user samples were supplied, so the current profile is clearly a neutral default.

Put selected samples and a manifest under ignored `private/`. Label authorship `user-authored`, `assistant-assisted`, or `explicitly-user-approved`; assistant-assisted samples alone cannot establish the user's voice. Follow [calibration.md](writing_style/calibration.md) to generate an unapproved proposal, inspect its sentence-length observations and synthetic before/after illustration, edit, approve and version it. Calibration is intentionally local and limited; it does not claim to learn personality or a full voice model. Raw examples are never loaded as pipeline instructions. Conversational style remains separate from professional style.

## Evaluation and tests

```bash
.venv/bin/pytest -q
.venv/bin/career evaluate --output local/evaluation.json
```

The small benchmark compares A: full confirmed record one-shot, B: retrieval plus generation, C: retrieval plus bounded review, on a standard job and a prompt-injected variant. It reports measured unsupported-claim rate, manually labeled supported-requirement coverage, wording/metric consistency, title/date rendering consistency, latency, tokens and available cost. Results are **deterministic mock measurements**, not live efficacy or hiring predictions. All arms use the same safe mock; do not infer that review improves quality from equal scores. The independent deterministic holdout judge is separate from the optimizing reviewer. Model judgments, human editing effort and blind human preference are null until supplied; none are fabricated.

`fixtures/adversarial.json` lists absent tools, injected instructions, conflicting dates, realized-versus-estimated savings, invented leadership and unsupported reviewer requests. Tests exercise these boundaries, end-to-end mock execution, uncertain sources, unknown IDs, snapshot gates, revision limits, repeated outputs, DOCX content and UI rendering. The benchmark itself is intentionally small; nuanced retrieval and live-model quality need a larger independently labeled corpus and blinded human evaluation.

## Privacy and limits

Local SQLite snapshots, cache, artifacts, personal evidence and samples contain private data. `.gitignore` excludes `local/`, `private/`, `artifacts/`, credentials and databases by default. Do not put personal files in public fixtures or writing_style/examples. Review files before staging. Delete the local database and artifacts to remove retained content; no automatic retention schedule or encryption at rest is implemented. Use a private machine and encrypted storage for sensitive data.

Mock mode makes no model calls. Live mode transmits the job description, selected evidence (the full confirmed record for baseline A), approved profile, packet and findings to Anthropic. Raw writing samples are not sent. Provider retention and account policies apply. No private content is intentionally logged, but provider exception handling by external tooling should be reviewed before deployment. The UI is for a trusted single user: no authentication, multi-user isolation or internet deployment hardening is included. Structured inputs, factual gates and prompt boundaries reduce injection risk but are not a universal injection defense. Source verification and final editorial responsibility remain human tasks.


## Adapted resume development guidance

The explicitly loaded [resume guide](writing_style/resume_guidance.md) adapts selected items from
**ResumeSkills** and **resume-tailoring-skill** only: source-library organization, requirement mapping,
concrete technical bullets, optional experience discovery, and readable document formatting.
[Sources and retained MIT notices](writing_style/SOURCES.md) identify the upstream revisions.
No external skill collection or third-party automation is installed. The other two researched
projects (Proficiently and Anthropic DOCX) are excluded from this adaptation.

[Detailed guidance](docs/resume-development.md) explains the workflow. The compact model-facing guide
is loaded along with SKILL.md and profile.json; the combined hash covers all loaded instructions,
so guidance changes invalidate stage caches. This is general guidance, not sample-learned voice.
Custom style directories can omit the optional guide for backward compatibility; copy it and its
attribution/licenses if you want the adapted guidance in your custom package.

Optional discovery questions for weak/unsupported requirements are persisted in each run manifest
and shown in the UI. They are prompts for separate evidence editing, not automatically confirmed
answers or an extension of revision limits. A genuine experience gap can stay a gap.

For descriptive resume headings, set `resume_display_title` and
`resume_display_title_approved: true` in the evidence JSON **only after user approval**. The
`official_title` remains unchanged for audit and employment verification. Unapproved display titles
fail input validation. This does not authorize invented seniority or responsibilities.

Resume exports group accomplishments for the same role, use month/year display dates, native Word
bullets, US Letter pages, 11-point body text and consistent margins/spacing. Visual pagination and
live-model response quality have not been validated by these changes; DOCX text/style checks and
mock/UI tests are covered. Arbitrary page-count and ATS pass guarantees are intentionally absent.

Mock requests reserve one dry-run attempt rather than three live retry attempts; mock telemetry
still reports zero actual provider tokens/cost. Live instructions appear once in the system prompt,
not duplicated in user data. Prompt version v2 records this serialization change.

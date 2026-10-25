# Evidence / Application Studio

A single-user, evidence-grounded job application workbench for data engineering roles. Python + Pydantic + SQLite + Streamlit, with a CLI and editable DOCX exports. **The bundled candidate and job are synthetic.** No scraping, applications, email sending, or autonomous publishing.

The factual gate supports two modes. **Strict** mode requires exact supported source wording.
**Live-reviewed** mode permits paraphrases only when a separate evidence auditor returns exact
source quotes and wording/metric/technology/scope/date checks, and independent deterministic guards
pass. A valid evidence ID or quote alone is insufficient. Model judgments remain fallible; factual
confirmation is separate from final user approval. Mock reviewers cannot authorize paraphrases.

## Setup

Python 3.11+ (validated here on Python 3.12). From the checkout root:

On Windows PowerShell, from the repository folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m streamlit run career_pipeline/ui.py
```

On macOS/Linux:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run career_pipeline/ui.py
```

Open the local browser address Streamlit prints. `requirements.lock` is the validated cloud
Python 3.12 snapshot; its NumPy/pandas pins do not support Python 3.11. The commands above
resolve dependencies compatible with your interpreter. Windows installation has not been run
in the Linux cloud environment. No credentials are needed in practice mode.

### Use the workbench

Your experience is stored locally and reused on every run; it is not recreated for each job.
On first use, import your private evidence backup in the sidebar, use the My experience forms,
or load the clearly labeled synthetic example. Confirmed facts are saved to `local/career.json`;
only confirmed records can generate claims. Role, evidence, tool, metric and source edits use
forms. Saving an edited record requires factual confirmation again; otherwise it becomes uncertain.
Back up the evidence file privately. Historical runs keep their original snapshots.

In Create application, paste a job description or load one public HTTPS posting link. Review
imported text before generating: some sites block access or require JavaScript/login. Paste text
instead in those cases. The importer follows at most three redirects, limits page size, rejects
local/private destinations, and does not crawl, log in or bypass site restrictions. Page content
remains untrusted data. URL handling is tested with simulated responses; site access varies.

The app maps requirements, asks optional gap questions, and saves explicitly confirmed factual
answers to your reusable library. Training, portfolio and academic work retain their context.
“No relevant experience” and practical preferences are saved separately, never promoted into
experience. Unanswered gaps remain visible and do not prevent a truthful draft. Generation mode
can be practice (no credentials), OpenAI, or Anthropic; model, review and writing-profile controls
are optional advanced settings. A private approved style bundle at
`private/writing_style/approved-v3` is selected when present; otherwise guidance is a neutral default.

Review & download shows rendered resume/letter previews, readable objections, evidence behind
passages, revision text diffs and a downloadable report. The report measures evidence coverage,
not hiring probability or ATS success. Lexical matches and evidence links are not proof of semantic
coverage. Factual errors prevent approval/final export; a labeled draft remains available. Final
approval always requires your explicit review. History shows status, latency and available cost.
JSON is reserved for optional backup/import and the expandable technical audit.

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

The UI supports validated JSON evidence editing and local saving, a requirement map, previews, provenance, findings, revision diffs when present, run history, approval, and DOCX/Markdown/audit downloads. Resume and letter text can be edited in DOCX; edits made outside the app are outside its audit boundary. To use edited evidence, paste it into the editor or provide the local JSON to the CLI. Historical UI previews use the saved run snapshot; CLI exports reject an evidence-snapshot mismatch.

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
- `providers.py`: provider protocol, deterministic mock, Anthropic and OpenAI Chat Completions adapters. Generator/reviewer settings are separate. Approved style instructions are loaded explicitly. Job descriptions, evidence, and reviewer messages remain data in prompts; generated facts still face a deterministic gate. The model reviewer cannot replace the factual auditor. Recruiter objections must reference a known claim and requirement; voice objections require a known claim.
- `store.py`: SQLite run manifests, input snapshots, version events, rejected revision candidates, and content-addressed stage cache. Cache keys include provider/model, prompt version, settings and full stage payload. Manifests include hashes, schema/prompt/profile versions, model settings, stage latency/status, available usage/cost, revisions, stopping reason, validation, artifact paths and checksums. SQLite contains private content; stdout does not print snapshots.
- `export.py`: Markdown/DOCX renderer uses official employment metadata with separately user-approved descriptive display titles, excludes internal IDs from application files, and writes a separate audit report. PDF is an optional capability stub returning an explicit unavailable result; no rendering dependency is required.

Every generated revision candidate is persisted. The default revision limit is two, hard maximum three. Stop conditions include resolved actionable findings, limit, repeated/oscillating output, and budgets. Experience gaps remain visible and do not trigger endless edits. Factual failures yield `needs_review`, prevent approval/final export, and permit labeled draft previews. Schema/provider failures yield `failed` with the completed stage history and saved candidate retained. Each candidate receives separate evidence, recruiter and voice reviewer calls.

### Evidence authoring contract

Only mark sources `user_confirmed` after inspecting the factual source statements. The app does not authenticate source documents or infer missing facts. Approved wording and confirmed factual statements are explicit support anchors; neither constitutes approval of a generated packet. Structured fields and source excerpts provide context, not independent proof. Preserve estimated/expected/realized qualifiers, titles, dates, familiarity versus production use, contribution versus ownership, and education status. Do not approve paraphrases implying leadership, database administration or a completed degree without that evidence. `prohibited_inferences` is available to model context and human review; arbitrary natural-language prohibitions are not a semantic rules engine. Strict checks catch deviations from supported source wording; live-reviewed mode additionally validates structured assessments and independent number/unit/qualifier/tool/scope guards. Neither authenticates source facts or proves entailment. The separate evidence reviewer can raise additional factual objections, which block approval.

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

`TOKEN_BUDGET` and `CALL_BUDGET` configure CLI limits. Python callers can set all `Settings` fields, including maximum output tokens and separate input/output USD-per-million rates. Prices are intentionally not hard-coded: live cost is unavailable unless rates are supplied. Mock usage/cost are zero. Live budgets reserve three attempts and byte-based input/schema bounds plus maximum output, then settle successful calls using reported usage; cached stages consume no new budget. Up to three attempts use short exponential backoff for connection, rate-limit and server errors; authentication and invalid JSON errors fail without unchanged retries. Reservations can stop a run earlier than actual token usage would suggest. Live outputs are not promised to regenerate identically.

The Streamlit controls support separate generator/reviewer models, budgets, local evidence loading and an approved style directory; each selected provider uses its configured key binding. **Live Anthropic calls have not been exercised as part of credential-free validation.** A valid provider key, model access and HTTPS access to its API are required. OpenAI is also supported; see the configuration below.

## Writing profile calibration

`writing_style/` is a portable package: SKILL.md, versioned neutral profile, labeled optional examples and calibration instructions. The application explicitly loads this skill; arbitrary SKILL.md discovery by Claude Code is not assumed. The public profile is a labeled neutral default; personal samples and profiles belong in ignored private storage.

Put selected samples and a manifest under ignored `private/`. Label authorship `user-authored`, `assistant-assisted`, or `explicitly-user-approved`; assistant-assisted samples alone cannot establish the user's voice. Follow [calibration.md](writing_style/calibration.md) to generate an unapproved proposal, inspect its sentence-length observations and synthetic before/after illustration, edit, approve and version it. Calibration is intentionally local and limited; it does not claim to learn personality or a full voice model. Raw examples are never loaded as pipeline instructions. Conversational style remains separate from professional style.

Use the [private-profile workflow](writing_style/private_profiles.md) to approve and version a
personal package, load it explicitly with `--style`, understand what live providers receive, and
back it up privately. A [generic profile example](writing_style/examples/profile.generic.example.json)
supports a credential-free walkthrough without publishing anyone's writing. Sample approval and
profile approval are separate. The UI now accepts an explicit approved-style directory as well as local evidence JSON.
Profiles are never selected automatically from local selection notes.

## Evaluation and tests

```bash
.venv/bin/pytest -q
.venv/bin/career evaluate --output local/evaluation.json
```

The small benchmark compares A: full confirmed record one-shot, B: retrieval plus generation, C: retrieval plus bounded review, on a standard job and a prompt-injected variant. It reports measured unsupported-claim rate, manually labeled supported-requirement coverage, wording/metric consistency, title/date rendering consistency, latency, tokens and available cost. Results are **deterministic mock measurements**, not live efficacy or hiring predictions. All arms use the same safe mock; do not infer that review improves quality from equal scores. The independent deterministic holdout judge is separate from the optimizing reviewer. Model judgments, human editing effort and blind human preference are null until supplied; none are fabricated.

`fixtures/adversarial.json` lists absent tools, injected instructions, conflicting dates, realized-versus-estimated savings, invented leadership and unsupported reviewer requests. Tests exercise these boundaries, end-to-end mock execution, uncertain sources, unknown IDs, snapshot gates, revision limits, repeated outputs, DOCX content and UI rendering. The benchmark itself is intentionally small; nuanced retrieval and live-model quality need a larger independently labeled corpus and blinded human evaluation.

## Privacy and limits

Local SQLite snapshots, cache, artifacts, personal evidence and samples contain private data. `.gitignore` excludes `local/`, `private/`, `artifacts/`, credentials and databases by default. Do not put personal files in public fixtures or writing_style/examples. Review files before staging. Delete the local database and artifacts to remove retained content; no automatic retention schedule or encryption at rest is implemented. Use a private machine and encrypted storage for sensitive data.

Mock mode makes no model calls. Live mode transmits the job description, selected evidence (the full confirmed record for baseline A), approved profile, packet and findings to the selected provider (Anthropic or OpenAI). Raw writing samples are not sent. Provider retention and account policies apply. No private content is intentionally logged, but provider exception handling by external tooling should be reviewed before deployment. The UI is for a trusted single user: no authentication, multi-user isolation or internet deployment hardening is included. Structured inputs, factual gates and prompt boundaries reduce injection risk but are not a universal injection defense. Source verification and final editorial responsibility remain human tasks.


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


## Personal pipeline and adversarial review

See [the integrated pipeline guide](docs/pipeline-review.md) for month-precision dates, importing
private scoped confirmations, education/publication records, categorized skills, independent review
roles, reviewing an existing packet, inspecting saved findings and using the approval/export gates.
The UI uses saved input snapshots for historical runs. All three reviews must complete before
approval; model factual errors cannot be waived by the deterministic auditor or vice versa.
Software tests include a deficient-packet regression that catches thin role coverage, missing
publications/education and missing skills, revises, and revalidates through the actual pipeline.
Live adversarial quality remains unverified without a configured key and actual service calls.


## OpenAI provider

Select OpenAI independently for generator and reviewer. Default OpenAI model: `gpt-4.1`; override
it with `GENERATOR_MODEL` / `REVIEWER_MODEL` or the corresponding CLI/UI fields. Model availability
and API billing depend on your account; a ChatGPT subscription alone is not API access.

```bash
# Put the API credential in secure environment settings, never here or in Git.
export GENERATOR_PROVIDER=openai
export REVIEWER_PROVIDER=openai
.venv/bin/career run --jd private/job.txt --career private/career-v1.json \
  --style private/writing_style/approved-v1 --report private/openai-review.md
```

The adapter uses the official OpenAI SDK Chat Completions API with strict function-result schemas,
separate reviewer-role prompts, bounded transient retries and actual reported token usage. All
existing factual/semantic assessment and final approval gates apply to OpenAI too. Tests use
mocked HTTP transport; they do not establish live authentication or response quality.

For a new cloud configuration, use the non-reserved variable `CAREER_OPENAI_API_KEY`. Local
installations also support the standard `OPENAI_API_KEY`; cloud settings reserve names beginning
with `OPENAI_`. Existing bindings can be used explicitly with `CAREER_OPENAI_KEY_VARIABLE` set
to that binding's variable **name**, not its value. The binding must allow `api.openai.com` and
network policy must allow the same hostname. The app does not copy credentials or infer which
provider a key belongs to.

When a key was originally saved under a differently named binding, preserve it rather than adding
a duplicate. Edit the existing binding's allowed destination in environment settings. For example,
a binding named `ANTHROPIC_API_KEY` that actually contains an OpenAI key can be selected with
`CAREER_OPENAI_KEY_VARIABLE=ANTHROPIC_API_KEY` and allowed at `api.openai.com`. This is explicit
migration configuration; Anthropic still requires a genuine Anthropic key if selected later.
Draft saves do not apply runtime changes; review/save and publish when required by the UI.
Do not broaden the key's destinations to unrelated hosts or extract proxy-held values.

### Writing-quality checks

Live runs also apply presentation heuristics, separately from factual validation. They flag short
experience fragments, source-record labels, repeated passages, scientific notation, role chronology,
passages spanning employers, omitted selected skill categories and ledger-like cover letters.
Selected education/publication omissions remain part of document review. These suggestions enter
the existing bounded revision loop; unresolved presentation suggestions can be reviewed and approved,
whereas factual errors still block final export. No check rewrites a fact automatically.

Under Writing style & advanced settings, disable the checks or adjust minimum bullet/letter word
preferences. Python callers can also configure repetition similarity and individual check groups
through `Settings.content_quality`. The minimum letter-word preference defaults to disabled;
length alone does not establish quality. Practice runs report quality as not assessed. Old run
reports display not recorded, rather than retroactively claiming checks ran.

### Readiness and release checks

The sidebar shows the running commit (or installed package version). In **Provider readiness**,
key presence means only that a value is configured. **Test selected providers with synthetic data**
makes one small structured request for the generator and one for the reviewer, using fictional
facts only. These requests can incur API charges and are separate from the application budget.
A successful test verifies that configuration, not the quality or completion of a larger run.
The panel explains call counts and conservative token reservations before generation.

Enter optional company and role names to identify saved applications. Match reports retain job
excerpts, evidence IDs and linked passages, and distinguish lexical coverage from model findings.
Practical constraints remain separate from career evidence. No summary predicts hiring outcomes.

The full audit is downloadable even if document export fails. Invalid hidden characters are
flagged during review; labeled drafts show visible replacement marks and retain originals in the
audit. Final approval blocks invalid text. Review the audit locally: it includes private content.

### Optional PDF and layout inspection

Editable DOCX and Markdown do not require a PDF renderer. To enable local PDF conversion,
install LibreOffice and ensure `soffice` or `libreoffice` is on PATH. For page geometry checks:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[layout]"
```

On Linux/macOS use `.venv/bin/python -m pip install -e '.[layout]'`.
In **Review & download → Optional PDF & layout review**, render the current documents. Page-count
preferences, dense-text, possible clipping and possible orphaned-heading warnings are heuristics,
not a visual-quality guarantee. Download and open the PDFs before recording visual review.
That acknowledgement is bound to PDF hashes and document version; it never bypasses factual
approval. Missing dependencies or conversion failures leave DOCX/Markdown available.

CLI equivalents:

```text
career check-provider --provider openai --model gpt-4.1 --role generator
career check-provider --provider openai --model gpt-4.1 --role reviewer
career layout RUN_ID --draft
```

Run `python -m pip install -e ".[dev,layout]"` and `python -m pytest -q` to test.
CI is configured for Windows and Ubuntu on Python 3.11 and 3.12. A workflow configuration is not
proof those jobs passed; inspect GitHub Actions before release. See
[release verification](docs/release-verification.md) for measured checks and remaining verification.

If presentation edits introduce new review errors after a packet has passed, the pipeline restores
that exact passing packet and stops. Both the rejected edit and restored version remain in the
audit. Restoring a version does not mark it user-approved or remove unresolved presentation gaps.

At the top of **Create application**, **Include a cover letter** controls which documents are
created. Clear it for a resume-only run; the selection is saved with the run and honored by
review, approval, and export. The CLI equivalent is `career run ... --resume-only`.
Existing runs retain their original document selection.

Job intake recognizes ordinary qualification/responsibility lines, numbered lists and Markdown
headings. If no requirements are recognized, the UI explains that extraction is empty instead
of showing a misleading zero-match summary. Coverage remains lexical and should be reviewed.

Confirmed work history is retained independently of job-description keyword matching. Retrieval
chooses relevant evidence within each employment scope; it cannot remove every job when a posting
has unfamiliar wording. A resume missing a confirmed employment scope is marked incomplete and
blocked from final approval/export. Uncertain evidence remains excluded. Old runs are preserved;
create a new run to use the updated selection and document options.

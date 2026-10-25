"""Human-facing workbench; pipeline and factual gates remain independent of Streamlit."""
import difflib
import json
import os
import uuid
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from career_pipeline.models import Career, Evidence, Employment, Packet, Settings, DEFAULT_MODELS
from career_pipeline.store import Store, digest
from career_pipeline.pipeline import run
from career_pipeline.export import approve, export, preview, export_pdf
from career_pipeline.workbench import save_profile, analyze_job, add_gap_answer, fit_report, application_label, user_provided_profile
from career_pipeline.job_input import load_job_url
from career_pipeline.models import Requirement, ContentQualitySettings
from career_pipeline.report import review_report
from career_pipeline.readiness import app_version, check_provider, budget_plan
from career_pipeline.baseline import missing_source_jobs
from career_pipeline.ui_errors import configuration_problem, failure_message


def lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def save_career(career):
    save_profile(career)
    st.session_state.career = career.model_dump(mode='json')
    st.session_state.library_error = False


def validation_message(exc):
    if isinstance(exc, ValidationError):
        for error in exc.errors(include_input=False):
            st.error(error['msg'].removeprefix('Value error, '))
    else:
        st.error(str(exc))


def findings_view(findings):
    labels = {'evidence': 'Factual accuracy', 'recruiter': 'Relevance & presentation', 'voice': 'Writing style'}
    for finding in findings:
        role = labels.get(finding['role'], finding['role'])
        target = finding.get('claim_id') or finding.get('section') or finding.get('requirement_id')
        text = f"**{role}** · {target or 'Packet'}\n\n{finding['message']}"
        {'error': st.error, 'gap': st.warning, 'suggestion': st.info}[finding['severity']](text)
    if not findings:
        st.success('No outstanding findings.')


st.set_page_config(page_title='Application Studio', layout='wide')
st.title('Application Studio')
st.caption('Your experience, tailored to the role. Every factual claim stays connected to its source.')
store = Store(os.getenv('CAREER_DB', 'local/pipeline.sqlite'))
if 'career' not in st.session_state:
    path = next((p for p in (Path('local/career.json'), Path('private/career-v3.json')) if p.exists()), Path('local/career.json'))
    try:
        st.session_state.career = (Career.model_validate_json(path.read_text(encoding='utf-8')).model_dump(mode='json')
                                   if path.exists() else Career(display_name='', evidence=[]).model_dump(mode='json'))
    except (ValueError, OSError):
        st.session_state.career = Career(display_name='', evidence=[]).model_dump(mode='json')
        st.session_state.library_error = True
if st.session_state.get('library_error'):
    st.warning('The saved experience library could not be read. The original file is untouched. Import a valid backup from the sidebar before continuing.')
career = Career.model_validate(st.session_state.career)

with st.sidebar:
    st.header('Workspace')
    st.caption('App version: ' + app_version())
    st.caption('Personal evidence is saved on this computer. It is not included in the public repository.')
    st.metric('Saved source records', sum(e.eligible for e in career.evidence))
    with st.expander('Try the synthetic example'):
        st.caption('Replaces the current workspace with fictional evidence. Export a backup first if needed.')
        if st.button('Load synthetic example'):
            save_career(Career.model_validate_json(Path('fixtures/career.json').read_text(encoding='utf-8')))
            st.rerun()
    with st.expander('Import / backup'):
        upload = st.file_uploader('Import an evidence backup', type=['json'])
        if st.button('Import backup', disabled=upload is None):
            try:
                save_career(user_provided_profile(Career.model_validate_json(upload.getvalue())))
                st.rerun()
            except ValueError as exc:
                validation_message(exc)
        st.download_button('Download evidence backup', career.model_dump_json(indent=2), 'career-evidence.json', 'application/json')
        st.caption('For evidence already on this computer:')
        path = st.text_input('Evidence file', placeholder='private/career-v3.json')
        if st.button('Load evidence file', disabled=not path):
            try:
                save_career(user_provided_profile(Career.model_validate_json(Path(path).read_text(encoding='utf-8'))))
                st.rerun()
            except (ValueError, OSError):
                st.error('Could not load a valid evidence file. Check the path and file format.')

apply_tab, evidence_tab, review_tab, history_tab = st.tabs(['Create application', 'My experience', 'Review & download', 'History'])

with evidence_tab:
    st.header('My experience')
    st.write('Your uploaded resumes and saved entries are the source of truth. Reviews check generated output against them; you do not need to confirm each input fact again.')
    resume_upload = st.file_uploader('Load a resume as my history', type=['docx', 'txt'])
    intake_provider = st.selectbox('Resume extraction provider', ['openai', 'anthropic'])
    st.caption('Extraction sends this resume to the selected provider and may incur API charges. The original is saved locally; extracted history is added without deleting existing facts.')
    intake_problem = configuration_problem(intake_provider)
    if resume_upload is not None and intake_problem:
        st.error(intake_problem)
    if st.button('Import resume', disabled=resume_upload is None or bool(intake_problem)):
        try:
            from career_pipeline.resume_intake import extract_resume, merge_resume
            with st.spinner('Extracting job history and source bullets…'):
                data = resume_upload.getvalue()
                imported, source_text = extract_resume(data, resume_upload.name, intake_provider, DEFAULT_MODELS[intake_provider])
                folder = Path('local/resume_sources')
                folder.mkdir(parents=True, exist_ok=True)
                (folder / (digest(data.hex()) + Path(resume_upload.name).suffix.lower())).write_bytes(data)
                save_career(merge_resume(career, imported))
            st.rerun()
        except ValueError as exc:
            validation_message(exc)
        except Exception as exc:
            st.error(failure_message(exc))
    st.info('Employment history is your resume baseline. Every saved job stays in reverse chronological order; job tailoring changes supported bullets, not your employers, titles or dates.')
    with st.form('identity'):
        name = st.text_input('Name', career.display_name)
        contact = st.text_area('Contact details', '\n'.join(career.contact), placeholder='Email, location, portfolio link — one per line')
        if st.form_submit_button('Save contact details'):
            updated = career.model_copy(update={'display_name': name, 'contact': lines(contact)})
            save_career(updated)
            st.rerun()
    with st.expander('Employment history', expanded=not career.employments):
        for job in career.employments:
            st.write(f'**{job.employer}** · {job.resume_display_title or job.official_title}')
            st.caption(f'Official title: {job.official_title} · {job.start} – {job.end or "Present"}')
        chosen_role = st.selectbox('Add or update a role', ['New role'] + [j.id for j in career.employments],
            format_func=lambda x: x if x == 'New role' else next(f'{j.employer} — {j.official_title}' for j in career.employments if j.id == x))
        job = next((j for j in career.employments if j.id == chosen_role), None)
        with st.form('role_' + chosen_role):
            employer = st.text_input('Employer', job.employer if job else '')
            title = st.text_input('Official job title', job.official_title if job else '')
            display = st.text_input('Descriptive resume title (optional)', (job.resume_display_title or '') if job else '')
            display_ok = st.checkbox('I approve this descriptive title', value=job.resume_display_title_approved if job else False)
            left, right = st.columns(2)
            start = left.text_input('Start (YYYY-MM)', str(job.start) if job else '')
            end = right.text_input('End (blank if current)', str(job.end) if job and job.end else '')
            if st.form_submit_button('Save role'):
                try:
                    if not employer.strip() or not title.strip():
                        raise ValueError('Employer and official job title are required.')
                    record = Employment(id=job.id if job else 'job-' + uuid.uuid4().hex[:12], employer=employer,
                        official_title=title, start=start, end=end or None, resume_display_title=display or None,
                        resume_display_title_approved=display_ok)
                    data = career.model_dump(mode='json')
                    data['employments'] = [j for j in data['employments'] if j['id'] != record.id] + [record.model_dump(mode='json')]
                    save_career(Career.model_validate(data))
                    st.rerun()
                except ValueError as exc:
                    validation_message(exc)
    st.subheader('Evidence library')
    search = st.text_input('Find evidence', placeholder='Search projects, tools or accomplishments')
    filtered = [e for e in career.evidence if not search or search.lower() in json.dumps(e.model_dump(mode='json')).lower()]
    if not career.evidence:
        st.info('Start with a role above, then add an accomplishment below. You can also load the synthetic example from the sidebar.')
    for e in filtered:
        with st.expander(f'{e.project}'):
            st.caption(f'{e.kind.title()} · {e.ownership.title()}')
            for statement in e.supported_wording:
                st.write(statement)
            if e.technologies:
                st.write('**Tools:** ' + '; '.join(f'{t.name} — {t.usage} ({t.context})' for t in e.technologies))
            for source in e.sources:
                st.caption(f'Source: {source.reference}')
            if e.prohibited_inferences:
                st.write('**Do not imply:** ' + '; '.join(e.prohibited_inferences))
    edit_id = st.selectbox('Add or edit evidence', ['New evidence'] + [e.id for e in career.evidence],
        format_func=lambda x: x if x == 'New evidence' else next(e.project for e in career.evidence if e.id == x))
    current = next((e for e in career.evidence if e.id == edit_id), None)
    with st.form('evidence_' + edit_id):
        project = st.text_input('Project or accomplishment', current.project if current else '')
        kinds = ['experience', 'project', 'education', 'publication', 'skill']
        kind = st.selectbox('Type', kinds, index=kinds.index(current.kind) if current else 0)
        roles = st.multiselect('Related roles', [j.id for j in career.employments], default=current.employment_ids if current else [],
            format_func=lambda ident: next(f'{j.employer} — {j.official_title}' for j in career.employments if j.id == ident))
        ownerships = ['contributed', 'owned', 'familiarity', 'unspecified']
        ownership = st.selectbox('Your involvement', ownerships, index=ownerships.index(current.ownership) if current else 0,
            format_func=lambda x: {'contributed': 'Shared contribution', 'owned': 'Owned this work', 'familiarity': 'Familiarity / learning', 'unspecified': 'Not specified in source'}[x])
        statements = st.text_area('Factual statements — one per line', '\n'.join(current.supported_wording) if current else '',
            help='Describe what you personally did. Preserve metric units and qualifiers such as estimated or expected.')
        actions = st.text_area('Actions you personally performed — one per line', '\n'.join(current.actions) if current else '')
        st.caption('Add actual tool use below. Mark coursework, training and portfolio work accurately.')
        tools = st.data_editor([t.model_dump() for t in current.technologies] if current and current.technologies else
            [{'name': '', 'usage': '', 'context': 'professional', 'category': 'Tools'}], num_rows='dynamic',
            column_config={'context': st.column_config.SelectboxColumn('Context', options=['professional', 'portfolio', 'academic', 'training'], required=True)}, key='tools_' + edit_id)
        metrics = st.data_editor([m.model_dump() for m in current.metrics] if current and current.metrics else
            [{'value': 0.0, 'unit': '', 'qualifier': 'estimated'}], num_rows='dynamic',
            column_config={'qualifier': st.column_config.SelectboxColumn('Qualifier', options=['realized', 'estimated', 'expected'], required=True)}, key='metrics_' + edit_id)
        prohibited = st.text_area('What this must not imply — one per line', '\n'.join(current.prohibited_inferences) if current else '',
            placeholder='Peer training does not mean people management')
        st.caption('Saving adds these statements as user-provided source data. Generated claims must stay supported by them.')
        if st.form_submit_button('Save evidence'):
            try:
                if not project.strip() or not lines(statements):
                    raise ValueError('Add a project name and at least one factual statement.')
                data = current.model_dump(mode='json') if current else {'id': 'ev-' + uuid.uuid4().hex[:12]}
                data.update(project=project, kind=kind, employment_ids=roles, ownership=ownership,
                    approved_wording=[], confirmed_statements=lines(statements), actions=lines(actions),
                    technologies=[t for t in tools if str(t.get('name') or '').strip()],
                    metrics=[m for m in metrics if str(m.get('unit') or '').strip()],
                    prohibited_inferences=lines(prohibited),
                    sources=[{'reference': 'User entry', 'status': 'user_provided', 'excerpt': statements}])
                record = Evidence.model_validate(data)
                data = career.model_dump(mode='json')
                data['evidence'] = [e for e in data['evidence'] if e['id'] != record.id] + [record.model_dump(mode='json')]
                save_career(Career.model_validate(data))
                st.rerun()
            except ValueError as exc:
                validation_message(exc)

with apply_tab:
    st.header('Tailor your next application')
    if not career.evidence:
        st.info('First, add your experience in My experience, import a backup, or try the synthetic example in the sidebar.')
    include_cover_letter = st.checkbox('Include a cover letter', value=True, help='Choose your documents here. Turn this off to create and download only a resume.')
    st.subheader('1. Choose the role')
    company_name = st.text_input('Company (optional)')
    role_name = st.text_input('Role (optional)')
    with st.expander('Load a job posting link'):
        job_url = st.text_input('Job posting URL', placeholder='https://company.example/careers/data-engineer')
        if st.button('Load posting', disabled=not job_url):
            try:
                with st.spinner('Reading the posting…'):
                    st.session_state.job_description = load_job_url(job_url)
                st.success('Posting loaded below. Review the extracted text before continuing.')
            except ValueError as exc:
                validation_message(exc)
        st.caption('Public pages only. LinkedIn and sites requiring sign-in may block access; paste the description instead.')
    jd = st.text_area('Paste the job description', height=240, key='job_description', placeholder='Paste the full job description, including qualifications and responsibilities.')
    if len(jd.strip()) >= 20 and career.evidence:
        try:
            requirements = analyze_job(jd, career)
        except ValueError as exc:
            validation_message(exc)
            requirements = []
        summary = fit_report(requirements)
        if not requirements:
            st.warning('No job requirements were recognized. Add the responsibilities and qualifications from the posting; these counters are not a zero-match assessment.')
        else:
            cols = st.columns(3)
            cols[0].metric('Direct evidence', summary['direct'])
            cols[1].metric('Transferable evidence', summary['transferable'])
            cols[2].metric('Gaps to review', summary['gaps'] + summary['clarifications'])
            st.caption('Evidence coverage uses transparent lexical matching, not an ATS score or a prediction of hiring outcomes.')
        gaps = [q for q in requirements if q.classification in ('unsupported', 'needs_clarification')]
        job_hash = digest(jd)
        intake_id = 'intake-' + job_hash
        saved_answers = store.follow_up_answers(job_hash)
        if gaps:
            st.subheader('A few follow-up questions')
            st.caption('Answer only where you have relevant facts to add. Genuine gaps can stay gaps; you can still generate a draft.')
        for q in gaps:
            with st.expander(q.text):
                if q.id in saved_answers:
                    st.info('Saved response: ' + saved_answers[q.id]['answer'])
                with st.form('followup_' + job_hash[:12] + q.id):
                    if q.kind == 'constraint':
                        answer = st.text_input('Does this practical requirement work for you?', placeholder='Confirm, describe a constraint, or leave unresolved')
                        if st.form_submit_button('Save preference'):
                            if answer.strip():
                                store.event(intake_id, 'follow_up', {'requirement_id': q.id, 'answer': answer, 'kind': 'preference'})
                                st.rerun()
                    else:
                        choice = st.radio('Do you have relevant experience?', ['Add experience', 'No relevant experience', 'Decide later'], key='choice_' + job_hash[:12] + q.id)
                        answer = st.text_area('What did you personally do?', key='answer_' + job_hash[:12] + q.id,
                            help='Include scope and actual results. Label estimates and training; do not turn shared work into sole ownership.')
                        role_ids = st.multiselect('Where did you do this?', [j.id for j in career.employments],
                            format_func=lambda ident: next(f'{j.employer} — {j.official_title}' for j in career.employments if j.id == ident), key='roles_' + job_hash[:12] + q.id)
                        tool = st.text_input('Tool or technology (optional)', key='tool_' + job_hash[:12] + q.id)
                        usage = st.text_input('How you used it', key='usage_' + job_hash[:12] + q.id)
                        context = st.selectbox('Experience context', ['professional', 'portfolio', 'academic', 'training'], key='context_' + job_hash[:12] + q.id)
                        ownership = st.selectbox('Scope of involvement', ['contributed', 'owned', 'familiarity'], key='ownership_' + job_hash[:12] + q.id)
                        if st.form_submit_button('Save answer'):
                            try:
                                if choice == 'Add experience':
                                    updated = add_gap_answer(career, q, answer, role_ids=role_ids, tool=tool, usage=usage,
                                        context=context, ownership=ownership, confirmed=True, jd_hash=job_hash)
                                    st.session_state.career = updated.model_dump(mode='json')
                                store.event(intake_id, 'follow_up', {'requirement_id': q.id, 'answer': answer if choice == 'Add experience' else choice, 'kind': 'evidence' if choice == 'Add experience' else 'gap'})
                                st.rerun()
                            except ValueError as exc:
                                validation_message(exc)

    st.subheader('2. Choose how to create your draft')
    mode = st.radio('Generation mode', ['Practice with mock models', 'Use OpenAI', 'Use Anthropic'], horizontal=True,
        help='Practice mode exercises the pipeline without API credentials; it does not use live model reviewers.')
    provider = {'Practice with mock models': 'mock', 'Use OpenAI': 'openai', 'Use Anthropic': 'anthropic'}[mode]
    st.caption(f'{sum(e.eligible for e in career.evidence)} saved source records available. Generated claims are checked against your inputs.')
    if provider == 'mock':
        st.info('Practice mode copies source statements. To create a polished application, choose a live provider above and configure its API key on this computer.')
    if provider != 'mock':
        st.info(f'This sends the job description, career evidence, approved style guidance and drafts to {provider.title()} for generation and review. API credentials belong in environment variables on this computer; cloud keys do not transfer here.')
    with st.expander('Writing style & advanced settings'):
        style_path = st.text_input('Approved style package', 'private/writing_style/approved-v3' if Path('private/writing_style/approved-v3').exists() else 'writing_style', help='The bundled profile is a neutral default. Select your approved private package to use personal guidance.')
        generator = st.selectbox('Generation provider', ['mock', 'openai', 'anthropic'], index=['mock', 'openai', 'anthropic'].index(provider), key='gen_' + provider)
        reviewer = st.selectbox('Review provider', ['mock', 'openai', 'anthropic'], index=['mock', 'openai', 'anthropic'].index(provider), key='rev_' + provider)
        generator_model = st.text_input('Generation model', DEFAULT_MODELS[generator], key='gm_' + generator)
        reviewer_model = st.text_input('Review model', DEFAULT_MODELS[reviewer], key='rm_' + reviewer)
        factual_mode = st.selectbox('Factual checking', ['model_reviewed', 'strict'] if reviewer != 'mock' else ['strict'],
            help='Live-reviewed paraphrases require source quotes and independent factual checks. Strict mode requires exact supported wording.')
        quality_enabled = st.checkbox('Check writing quality', value=True)
        minimum_bullet_words = st.number_input('Flag experience bullets shorter than this many words', 0, 30, 4)
        minimum_letter_words = st.number_input('Preferred minimum cover-letter words (0 disables)', 0, 400, 0)
        cycles = st.number_input('Maximum revision cycles', 0, 3, 2)
        token_budget = st.number_input('Token budget', min_value=1000, value=250000)
        output_limit = st.number_input('Maximum output tokens per call', min_value=256, max_value=16000, value=6000, help='Separate from the total budget. A truncated response can require a larger per-call allowance.')
        call_budget = st.number_input('Call budget (includes retry reservations)', min_value=1, max_value=100, value=48)
    with st.expander('Provider readiness'):
        for label, selected_provider in [('Generator', generator), ('Reviewer', reviewer)]:
            present = not configuration_problem(selected_provider)
            st.caption(f'{label}: {selected_provider} · ' + ('no key needed' if selected_provider == 'mock' else 'key configured (not yet verified)' if present else 'key missing'))
        st.caption('The connection test sends only fictional evidence. Each selected configuration makes one request, capped at 1,500 output tokens; API charges may apply separately from the application budget.')
        if st.button('Test selected providers with synthetic data'):
            for label, selected_provider, model in [('generator', generator, generator_model), ('reviewer', reviewer, reviewer_model)]:
                with st.spinner('Testing ' + label + '…'):
                    result = check_provider(selected_provider, model, label)
                store.event('readiness', 'synthetic_provider_test', result)
                (st.success if result['status'] == 'passed' else st.error)(label.title() + ': ' + result['message'])
        plan = budget_plan(Settings(max_revisions=cycles, max_calls=call_budget, token_budget=token_budget, max_output_tokens=output_limit))
        st.write(f"Up to {plan['normal_calls']} stage calls across the selected revision cycles; up to {plan['with_contract_corrections']} with reviewer corrections, before transient retries. Early stopping and cache hits may reduce this.")
        st.caption('Before each request, the pipeline reserves a conservative input-byte estimate plus the output limit and affordable retry capacity. Successful requests settle to reported token usage. A total budget can stop a run even when earlier calls succeeded; it is never raised automatically.')
    problems = [message for p in set((generator, reviewer)) if (message := configuration_problem(p))]
    missing_jobs = missing_source_jobs(career)
    if missing_jobs:
        labels = '; '.join(j['employer'] + ' — ' + j['official_title'] for j in missing_jobs)
        problems.append('These saved jobs have no linked source bullets: ' + labels + '. Import your resume in My experience or restore a complete evidence backup. No new accomplishments need to be invented.')
    for message in problems:
        st.error(message)
    if st.button('Create my draft', type='primary', disabled=bool(problems) or not any(e.eligible for e in career.evidence) or len(jd.strip()) < 20):
        try:
            with st.spinner('Matching evidence, writing and reviewing your application…'):
                m = run(jd, career, store, Settings(generator=generator, reviewer=reviewer, factual_mode=factual_mode, include_cover_letter=include_cover_letter,
                    generator_model=generator_model, reviewer_model=reviewer_model, max_revisions=cycles,
                    token_budget=token_budget, max_calls=call_budget, max_output_tokens=output_limit, content_quality=ContentQualitySettings(enabled=quality_enabled,
                        minimum_bullet_words=minimum_bullet_words, minimum_letter_words=minimum_letter_words)), style_path=style_path, application={'company': company_name, 'role': role_name})
            st.session_state.run_id = m['id']
            if m['status'] == 'needs_review':
                st.warning('The run finished with unresolved findings. Open Review & download to inspect the draft; final export remains blocked when errors remain.')
            else:
                st.success('Your draft is ready. Open Review & download to inspect it.')
        except Exception as exc:
            st.error(failure_message(exc))

with review_tab:
    history = store.history()
    if not history:
        st.info('Your application previews, evidence links and review notes will appear here after creating a draft.')
    else:
        ids = [m['id'] for m in history]
        def run_label(ident):
            item = next(m for m in history if m['id'] == ident)
            return f"{application_label(item)} · {item['created'][:16].replace('T', ' ')} · {item['status'].replace('_', ' ').title()} · {ident[:8]}"
        selected = st.selectbox('Application', ids, format_func=run_label,
            index=ids.index(st.session_state.get('run_id')) if st.session_state.get('run_id') in ids else 0)
        m = store.get(selected)
        st.download_button('Download full run audit (JSON)', json.dumps(m, indent=2), 'audit.json', 'application/json', key='audit_' + selected)
        st.caption(application_label(m))
        st.subheader(m['status'].replace('_', ' ').title())
        if m.get('failure'):
            st.error('Stopped at ' + m['failure']['stage'] + ': ' + m['failure']['message'])
            st.download_button('Download diagnostic summary', json.dumps({'run_id': m['id'], 'failure': m['failure'], 'stages': m['stages']}, indent=2), 'run-diagnostic.json', 'application/json')
        elif m['status'] == 'failed':
            st.warning('This older run has no detailed failure diagnostic. Its stages and saved review attempts remain in Technical audit details.')
        st.caption(f"{m['revision_count']} revision cycles · {m.get('latency', 0):.1f} seconds · {m.get('stopping_reason', 'running').replace('_', ' ')}")
        if m['settings']['reviewer'] == 'mock':
            st.warning('Practice output copies evidence statements to test the workflow. It is not a professionally tailored resume. Choose Use OpenAI or Use Anthropic in Create application for composed documents and live reviews.')
        snapshot = None
        try:
            snapshot = store.career_snapshot(selected)
        except ValueError:
            st.error('The saved evidence snapshot is unavailable. Rerun before approval or export.')
        if m['versions'] and snapshot:
            if 'restored_from_version' in m['versions'][-1]:
                st.info(f"Restored version {m['versions'][-1]['restored_from_version'] + 1} because later edits introduced review errors. The rejected version remains in review history.")
            packet = Packet.model_validate(m['versions'][-1]['packet'])
            resume, letter = preview(packet, snapshot)
            requirements = [Requirement.model_validate(q) for q in m.get('requirements', [])]
            summary = fit_report(requirements, packet)
            st.subheader('How your resume matches this role')
            a, b, c = st.columns(3)
            a.metric('Supported requirements covered', f"{summary['covered']} / {summary['supported']}")
            b.metric('Required items with evidence', f"{summary['required_supported']} / {summary['required_total']}")
            c.metric('Experience gaps', summary['gaps'])
            st.caption('Coverage means a passage cites evidence linked to a requirement. Lexical matching and model review can be imperfect; this is not a hiring prediction or semantic proof.')
            st.download_button('Download match & review report', review_report(m, snapshot), 'match-report.md', 'text/markdown')
            resume_tab, letter_tab, notes_tab, map_tab = st.tabs(['Resume', 'Cover letter', 'Review notes', 'Requirement coverage'])
            with resume_tab:
                st.markdown(resume)
            with letter_tab:
                if m['settings'].get('include_cover_letter', True):
                    st.markdown(letter)
                else:
                    st.info('No cover letter requested for this application.')
            with notes_tab:
                quality_status = m['versions'][-1].get('content_quality_status', 'not_recorded')
                st.caption('Writing-quality checks: ' + quality_status.replace('_', ' ') + '. These are presentation heuristics, not factual certification.')
                findings_view(m['versions'][-1]['findings'])
                for version in m['versions']:
                    with st.expander(f"Version {version['number'] + 1} · review history"):
                        for role, receipt in version.get('reviews', {}).items():
                            st.write(f"{role.title()}: {receipt['status']}")
                            for attempt in receipt.get('attempts', []):
                                if attempt['status'] == 'rejected':
                                    st.warning('Review response corrected: ' + attempt['error'])
                        findings_view(version['findings'])
            with map_tab:
                labels = {'direct': 'Direct evidence', 'transferable': 'Transferable experience', 'unsupported': 'Experience gap', 'needs_clarification': 'Needs clarification'}
                index = {e.id: e for e in snapshot.evidence}
                for q in m.get('requirements', []):
                    with st.expander(f"{labels[q['classification']]} · {q['text']}"):
                        st.caption(q['priority'].title())
                        st.write(q['excerpt'])
                        for ident in q['evidence_ids']:
                            if ident in index:
                                st.write('**' + index[ident].project + '**')
                                for text in index[ident].supported_wording:
                                    st.write(text)
                for question in m.get('discovery_questions', []):
                    saved = m.get('follow_up_answers', {}).get(question['requirement_id'])
                    st.info(question['excerpt'] + '\n\n' + ('Your saved answer: ' + saved['answer'] if saved else question['prompt']))
            with st.expander('Evidence behind each passage'):
                index = {e.id: e for e in snapshot.evidence}
                for claim in packet.resume + packet.cover_letter:
                    st.write('**' + claim.text + '**')
                    for ident in claim.evidence_ids:
                        e = index.get(ident)
                        st.caption(f'{ident} · {e.project if e else "Missing evidence"}')
                        if e:
                            for statement in e.supported_wording:
                                st.write(statement)
            if len(m['versions']) > 1:
                with st.expander('What changed in the latest revision'):
                    before = Packet.model_validate(m['versions'][-2]['packet'])
                    before_text = '\n'.join(preview(before, snapshot)).splitlines()
                    after_text = (resume + '\n' + letter).splitlines()
                    st.code('\n'.join(difflib.unified_diff(before_text, after_text, fromfile='Previous', tofile='Current')), language='diff')
            st.subheader('Review & export')
            blocked = m['status'] == 'failed' or bool(m.get('validation')) or any(f['severity'] == 'error' for f in m['versions'][-1]['findings'])
            if blocked:
                st.warning('Factual or review errors block approval and final export. You can download a labeled draft for inspection.')
            reviewed = st.checkbox('I reviewed the wording, supporting evidence, dates and unresolved gaps.', key='ack_' + selected)
            if st.button('Approve this application', disabled=not reviewed or blocked):
                try:
                    approve(store, selected, snapshot, acknowledged=True)
                    st.session_state['downloads'] = [str(p) for p in export(store, selected, snapshot, draft=False)]
                    st.rerun()
                except ValueError as exc:
                    validation_message(exc)
            draft = not m['approved']
            st.caption('Downloads are final approved documents.' if m['approved'] else 'Downloads are labeled drafts until you approve this application.')
            if st.button('Prepare documents', disabled=not draft and not m['approved']):
                try:
                    st.session_state['downloads'] = [str(p) for p in export(store, selected, snapshot, draft=draft)]
                    if store.get(selected).get('render_warnings'):
                        st.warning('Invalid hidden characters were replaced with visible replacement marks in this draft. The audit preserves the original text. Correct or regenerate it before final approval.')
                except ValueError as exc:
                    validation_message(exc)
            with st.expander('Optional PDF & layout review'):
                st.caption(f"Reviewing document version {m['versions'][-1]['number'] + 1}. Requires local LibreOffice; install the layout extra for geometry checks. Rendering does not approve facts or writing.")
                resume_pages = st.number_input('Preferred maximum resume pages', 1, 10, 2)
                letter_pages = st.number_input('Preferred maximum cover-letter pages', 1, 5, 1)
                if st.button('Render PDFs and inspect layout'):
                    try:
                        paths = export(store, selected, snapshot, draft=draft)
                        result = export_pdf(store, selected, paths, max_resume_pages=resume_pages, max_letter_pages=letter_pages)
                        st.session_state['downloads'] = [str(p) for p in paths] + [d['pdf'] for d in result['documents'] if d.get('pdf')]
                        st.rerun()
                    except ValueError as exc:
                        validation_message(exc)
                layout = m.get('layout_review')
                if layout:
                    st.caption(f"Layout result for version {layout['version'] + 1}: {layout['status']}")
                    if layout.get('reason'):
                        st.info(layout['reason'])
                    for document in layout['documents']:
                        inspection = document.get('inspection', {})
                        st.write(Path(document['source']).name + ': ' + str(inspection.get('page_count', 'unknown')) + ' pages')
                        for warning in inspection.get('warnings', []):
                            st.warning(warning)
                        if inspection.get('reason') or document.get('reason'):
                            st.info(inspection.get('reason') or document['reason'])
                    st.caption('Open the PDFs to inspect typography, clipping and pagination. Automated checks do not replace your visual review.')
                    if layout['status'] == 'rendered' and layout['documents']:
                        visual_ack = st.checkbox('I opened these PDFs and reviewed their layout.', key='layout_ack_' + selected + str(draft))
                        if st.button('Record visual review', disabled=not visual_ack):
                            from career_pipeline.layout import confirm_layout
                            try:
                                confirm_layout(store, selected)
                                st.success('Visual review recorded for these exact PDFs. Factual approval is separate.')
                            except ValueError as exc:
                                validation_message(exc)
            for path in st.session_state.get('downloads', []):
                p = Path(path)
                if selected in str(p) and p.exists() and p.parent.name == ('draft' if draft else 'final'):
                    st.download_button('Download ' + p.name, p.read_bytes(), file_name=p.name)
        else:
            st.info('This run did not save a document version. Check the technical details for completed stages.')
        with st.expander('Technical audit details'):
            st.json(m)

with history_tab:
    history = store.history()
    if not history:
        st.info('No applications yet. Create your first draft to start a history.')
    for m in history:
        with st.container(border=True):
            st.write(f"**{application_label(m)}** · **{m['status'].replace('_', ' ').title()}** · {m['created'][:16].replace('T', ' ')}")
            cost = m.get('estimated_cost')
            st.caption(f"{m.get('latency', 0):.1f} seconds · {m['revision_count']} revisions · Estimated cost: {f'${cost:.4f}' if cost is not None else 'unavailable'}")
            if st.button('Select for review', key='history_' + m['id']):
                st.session_state.run_id = m['id']
                st.rerun()
    st.caption('Select an application, then open Review & download. Live costs are unavailable unless pricing is configured. Practice runs cost zero.')

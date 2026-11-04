"""Human-facing workbench; pipeline and factual gates remain independent of Streamlit."""
import difflib
from html import escape
import json
import os
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from career_pipeline.models import Career, Evidence, Employment, Packet, Settings, DEFAULT_MODELS
from career_pipeline.store import Store, digest
from career_pipeline.pipeline import run, GAP_CLASSIFICATIONS
from career_pipeline.export import approve, export, preview, export_pdf
from career_pipeline.workbench import save_profile, analyze_job, add_gap_answer, fit_report, application_label, user_provided_profile
from career_pipeline.job_input import load_job_url
from career_pipeline.models import Requirement, ContentQualitySettings
from career_pipeline.report import review_report
from career_pipeline.readiness import app_version, check_provider, budget_plan
from career_pipeline.baseline import missing_source_jobs
from career_pipeline.ui_errors import configuration_problem, failure_message
from career_pipeline.duplicates import duplicate_groups, merge_duplicates
from career_pipeline.match_report import build_report, compare_reports, report_label, report_markdown

REPORT_PAGES = ['Match report', 'Report history', 'Compare jobs']
GENERATOR_PAGES = ['Create application', 'My experience', 'Review & download', 'Draft history']
MATCH_COLORS = {'strong': 'green', 'partial': 'orange', 'missing': 'red'}
REPORT_RESUME = Path('local/report_resume.json')  # The resume used for reports, kept on this computer.
STATUS_COLORS = {'approved': 'green', 'draft': 'blue', 'needs_review': 'orange', 'failed': 'red', 'running': 'gray'}
STAGE_LABELS = {'extract': 'Reading the job posting', 'match': 'Matching requirements to your evidence',
                'generate': 'Writing the first draft', 'validate': 'Checking claims against your sources',
                'review_evidence': 'Factual review', 'review_recruiter': 'Relevance review',
                'review_voice': 'Writing-style review', 'revise': 'Revising the draft'}


def lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def save_career(career):
    save_profile(career)
    st.session_state.career = career.model_dump(mode='json')
    st.session_state.library_error = False


def go_to(page):
    # Widget state can only change before the navigation radio is drawn, so defer to the next run.
    st.session_state.nav_target = page


def validation_message(exc):
    if isinstance(exc, ValidationError):
        for error in exc.errors(include_input=False):
            st.error(error['msg'].removeprefix('Value error, '))
    else:
        st.error(str(exc))


def status_title(status):
    return status.replace('_', ' ').title()


def findings_view(findings, passages=None):
    labels = {'evidence': 'Factual accuracy', 'recruiter': 'Relevance & presentation', 'voice': 'Writing style'}
    passages = passages or {}
    groups = [('error', 'Must fix', st.error, lambda f: True), ('gap', 'Gaps', st.warning, lambda f: True),
              ('suggestion', 'Questions for you', st.warning, lambda f: f.get('code') == 'needs_info'),
              ('suggestion', 'Suggestions', st.info, lambda f: f.get('code') != 'needs_info')]
    if not findings:
        st.success('No outstanding findings.')
    for severity, heading, show, belongs in groups:
        selected = [f for f in findings if f['severity'] == severity and belongs(f)]
        if not selected:
            continue
        st.markdown(f'**{heading}** · {len(selected)}')
        for finding in selected:
            role = labels.get(finding['role'], finding['role'])
            # Name the passage by its words, not its internal ID.
            text = passages.get(finding.get('claim_id'))
            target = (f'"{text[:70]}…"' if len(text) > 70 else f'"{text}"') if text else (
                (finding.get('section') or '').replace('_', ' ').title() or 'Whole application')
            show(f"**{role}** · {target}\n\n{finding['message']}")


def evidence_group(e, employers):
    if e.kind == 'experience' and e.employment_ids:
        return ' / '.join(dict.fromkeys(employers.get(i, 'Other role') for i in e.employment_ids))
    return {'project': 'Projects', 'education': 'Education', 'publication': 'Publications',
            'skill': 'Skills'}.get(e.kind, 'Other experience')


def edit_evidence(ident):
    st.session_state.edit_id = ident


def saved_resume():
    try:
        return json.loads(REPORT_RESUME.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def save_resume(name, text):
    REPORT_RESUME.parent.mkdir(parents=True, exist_ok=True)
    REPORT_RESUME.write_text(json.dumps({'name': name, 'text': text}), encoding='utf-8')


STYLE = """
<style>
.hero {padding: 1.5rem 1.75rem; border-radius: 1.1rem; margin: 0 0 1.25rem;
       background: linear-gradient(115deg, #0EA5E9 0%, #6366F1 50%, #C026D3 100%);
       box-shadow: 0 10px 30px rgba(99, 102, 241, .25);}
.hero h1 {margin: 0; padding: 0; font-size: 2rem; color: #fff;}
.hero p {margin: .35rem 0 0; color: rgba(255, 255, 255, .9); font-size: 1.05rem;}
.score-card {display: flex; flex-wrap: wrap; gap: 1.75rem; align-items: center; padding: 1.25rem 1.5rem;
             border-radius: 1rem; background: #151F33; border: 1px solid #25324D; margin-bottom: 1rem;}
.ring {--p: 0; --c: #2DD4BF; width: 128px; height: 128px; border-radius: 50%; flex: none; display: grid;
       place-items: center; background: conic-gradient(var(--c) calc(var(--p) * 1%), #25324D 0);}
.ring span {width: 100px; height: 100px; border-radius: 50%; background: #151F33; display: grid;
            place-items: center; font-size: 2rem; font-weight: 800; color: #F8FAFC;}
.score-text {flex: 1; min-width: 240px;}
.score-text h3 {margin: 0 0 .25rem; color: #F8FAFC;}
.score-text .meta {color: #94A3B8; font-size: .85rem; margin-bottom: .6rem;}
.pill {display: inline-block; padding: .2rem .7rem; border-radius: 999px; font-size: .85rem; font-weight: 700;
       margin: 0 .35rem .35rem 0;}
.pill.strong {background: rgba(16, 185, 129, .18); color: #6EE7B7;}
.pill.partial {background: rgba(245, 158, 11, .18); color: #FCD34D;}
.pill.missing {background: rgba(244, 63, 94, .18); color: #FDA4AF;}
.pill.required {background: rgba(125, 211, 252, .15); color: #7DD3FC;}
.rec {padding: .85rem 1.1rem; border-radius: .8rem; background: #151F33; border: 1px solid #25324D;
      border-left: 5px solid #2DD4BF; margin-bottom: .6rem;}
.rec.question {border-left-color: #F59E0B;}
.rec .tag {font-size: .72rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: #2DD4BF;}
.rec.question .tag {color: #F59E0B;}
.rec .action {color: #F1F5F9; font-weight: 600; margin: .15rem 0;}
.rec .why {color: #94A3B8; font-size: .9rem;}
.delta {padding: .8rem 1.1rem; border-radius: .8rem; margin-bottom: 1rem; border: 1px solid #25324D;
        background: linear-gradient(90deg, rgba(45, 212, 191, .14), rgba(21, 31, 51, .9));}
.delta.down {background: linear-gradient(90deg, rgba(244, 63, 94, .14), rgba(21, 31, 51, .9));}
.delta b {color: #F8FAFC;} .delta li {color: #CBD5E1;}
.bar-row {display: grid; grid-template-columns: 2.2rem minmax(10rem, 1.3fr) 3fr 3.5rem; gap: .75rem; align-items: center;
          padding: .55rem .2rem; border-bottom: 1px solid #25324D;}
.bar-row .rank {color: #94A3B8; font-weight: 800;}
.bar-row .job {color: #F1F5F9; font-weight: 600;}
.bar-row .job small {display: block; color: #94A3B8; font-weight: 400;}
.bar {height: .7rem; border-radius: 999px; background: #25324D; overflow: hidden;}
.bar div {height: 100%; border-radius: 999px;}
.bar-row .pct {font-weight: 800; text-align: right;}
</style>
"""
MATCH_TEXT = {'strong': '#6EE7B7', 'partial': '#FCD34D', 'missing': '#FDA4AF'}


def hero(title, subtitle):
    st.markdown(f'<div class="hero"><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>', unsafe_allow_html=True)


def score_color(percent):
    return '#10B981' if percent >= 75 else '#F59E0B' if percent >= 50 else '#F43F5E'


def report_view(report):
    info = report['application']
    title = ' — '.join(v for v in (info.get('company'), info.get('role')) if v) or 'Job match report'
    cost = report.get('estimated_cost')
    meta = (f"{report['created'][:16].replace('T', ' ')} · {report['model']}"
            + (f" · {report['resume_name']}" if report.get('resume_name') else '')
            + (f' · ${cost:.3f}' if cost else ''))
    score = report['score']
    overall = score['overall'] or 0
    required = '' if score['required'] is None else f'<span class="pill required">{score["required"]}% of required</span>'
    st.markdown(
        f'<div class="score-card"><div class="ring" style="--p:{overall};--c:{score_color(overall)}"><span>{overall}%</span></div>'
        f'<div class="score-text"><h3>{escape(title)}</h3><div class="meta">{escape(meta)}</div>'
        f'<span class="pill strong">{score["strong"]} strong</span><span class="pill partial">{score["partial"]} partial</span>'
        f'<span class="pill missing">{score["missing"]} missing</span>{required}'
        f'<p>{escape(report["summary"])}</p></div></div>', unsafe_allow_html=True)
    changes = report.get('changes')
    if changes:
        delta = changes['score_change']
        moved = ''.join(f"<li>{escape(m['requirement'][:90])}: {m['from']} → <b>{m['to']}</b></li>"
                        for m in changes['improved'] + changes['worse'])
        st.markdown(f'<div class="delta{" down" if delta < 0 else ""}"><b>{delta:+d} points</b> since your previous version '
                    f"({escape(changes['previous_created'][:10])}): {len(changes['improved'])} improved, "
                    f"{len(changes['worse'])} worse.{'<ul>' + moved + '</ul>' if moved else ''}</div>",
                    unsafe_allow_html=True)
    st.caption('Strong matches count fully and partial matches half. A model judgment checked against your resume text, '
               'not an ATS score or hiring prediction.')
    st.markdown('#### What to change')
    st.caption('Questions point at experience your resume does not show; answer them for yourself. '
               'Skip any edit that would add something you have not actually done.')
    if not report['recommendations']:
        st.caption('No changes suggested.')
    cards = ''.join(
        f'<div class="rec {r["kind"]}"><div class="tag">{n} · {"Question" if r["kind"] == "question" else "Edit"}</div>'
        f'<div class="action">{escape(r["action"])}</div><div class="why">{escape(r["reason"])}</div></div>'
        for n, r in enumerate(report['recommendations'], 1))
    if cards:
        st.markdown(cards, unsafe_allow_html=True)
    st.markdown('#### Requirement by requirement')
    order = {'missing': 0, 'partial': 1, 'strong': 2}
    rows = sorted(report['requirements'], key=lambda r: (order[r['match']], r['priority'] != 'required'))
    table = pd.DataFrame([{'Match': r['match'].title(), 'Priority': r['priority'].title(), 'Requirement': r['requirement'],
                           'In your resume': r['resume_quote'], 'Note': r['note']} for r in rows])
    if not table.empty:
        table = table.style.map(lambda value: f"color: {MATCH_TEXT.get(str(value).lower(), 'inherit')}; font-weight: 700",
                                subset=['Match'])
    st.dataframe(table, hide_index=True, width='stretch',
                 column_config={'Requirement': st.column_config.TextColumn(width='large'),
                                'In your resume': st.column_config.TextColumn(width='large')})
    if report['practical_constraints']:
        st.caption('Practical details (not scored): ' + ' · '.join(report['practical_constraints']))
    st.download_button('Download report (Markdown)', report_markdown(report), 'match-report.md', 'text/markdown',
                       key='download_' + report['id'])


st.set_page_config(page_title='Application Studio', layout='wide')
st.markdown(STYLE, unsafe_allow_html=True)
store = Store(os.getenv('CAREER_DB', 'local/pipeline.sqlite'))
if 'career' not in st.session_state:
    path = next((p for p in (Path('local/career.json'), Path('private/career-v3.json')) if p.exists()), Path('local/career.json'))
    try:
        st.session_state.career = (Career.model_validate_json(path.read_text(encoding='utf-8')).model_dump(mode='json')
                                   if path.exists() else Career(display_name='', evidence=[]).model_dump(mode='json'))
    except (ValueError, OSError):
        st.session_state.career = Career(display_name='', evidence=[]).model_dump(mode='json')
        st.session_state.library_error = True
career = Career.model_validate(st.session_state.career)
if 'nav_target' in st.session_state:
    st.session_state.page = st.session_state.pop('nav_target')

with st.sidebar:
    st.title('Application Studio')
    st.caption('See how well your resume fits a job, and what to change.')
    show_generator = st.session_state.get('show_generator', False)
    pages = REPORT_PAGES + (GENERATOR_PAGES if show_generator else [])
    if st.session_state.get('page') not in pages:
        st.session_state.page = pages[0]
    page = st.radio('Go to', pages, key='page', label_visibility='collapsed')
    st.divider()
    st.toggle('Resume & letter generator (experimental)', key='show_generator',
              help='The earlier tool that writes a tailored resume and cover letter from your saved experience.')
    if show_generator:
        st.metric('Saved source records', sum(e.eligible for e in career.evidence))
        with st.expander('Try the synthetic example'):
            st.caption('Replaces your workspace with fictional data. Download a backup first.')
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
            path = st.text_input('Evidence file on this computer', placeholder='private/career-v3.json')
            if st.button('Load evidence file', disabled=not path):
                try:
                    save_career(user_provided_profile(Career.model_validate_json(Path(path).read_text(encoding='utf-8'))))
                    st.rerun()
                except (ValueError, OSError):
                    st.error('Could not load a valid evidence file. Check the path and file format.')
st.sidebar.caption('Saved only on this computer · version ' + app_version())

if show_generator and st.session_state.get('library_error'):
    st.warning('The saved experience library could not be read. The original file is untouched. Import a valid backup from the sidebar before continuing.')

if page == 'Match report':
    hero('Match your resume to a job', 'See how well you fit, what to change, and what to ask yourself before you apply.')
    with st.container(border=True):
        st.subheader('1. Your resume')
        current = saved_resume()
        if current:
            st.caption(f"Using **{current['name']}** · {len(current['text'].split())} words. Upload or paste to replace it.")
        upload = st.file_uploader('Upload your resume', type=['docx', 'txt'])
        if upload is not None and st.button('Use this resume'):
            try:
                from career_pipeline.resume_intake import read_resume
                save_resume(upload.name, read_resume(upload.getvalue(), upload.name))
                st.rerun()
            except ValueError as exc:
                validation_message(exc)
        with st.expander('Or paste resume text'):
            pasted = st.text_area('Resume text', height=200, key='resume_text')
            if st.button('Use pasted text', disabled=len(pasted.strip()) < 50):
                save_resume('Pasted resume', pasted)
                st.rerun()
    with st.container(border=True):
        st.subheader('2. The job')
        company_col, role_col = st.columns(2)
        company = company_col.text_input('Company (optional)', key='report_company')
        role = role_col.text_input('Role (optional)', key='report_role')
        with st.expander('Load from a job posting link'):
            report_url = st.text_input('Job posting URL', key='report_url',
                help='Public pages only. Sites that need a sign-in (such as LinkedIn) usually block this; paste the text instead.')
            if st.button('Load posting', disabled=not report_url, key='report_load'):
                try:
                    with st.spinner('Reading the posting…'):
                        st.session_state.report_jd = load_job_url(report_url)
                    st.success('Posting loaded below. Check the text before continuing.')
                except ValueError as exc:
                    validation_message(exc)
        report_jd = st.text_area('Paste the job description', height=220, key='report_jd',
                                 placeholder='Paste the full job description, including qualifications and responsibilities.')
    with st.container(border=True):
        st.subheader('3. Create the report')
        engine = st.radio('Model', ['OpenAI gpt-5-mini', 'Practice (free, word matching only)'], horizontal=True,
                          help='gpt-5-mini costs about 1–2 cents per report and takes about a minute. '
                               'Practice mode just counts shared words, for trying the page out.')
        report_provider = 'openai' if engine.startswith('OpenAI') else 'mock'
        problem = configuration_problem(report_provider)
        if problem:
            st.error(problem)
        if st.button('Create match report', type='primary',
                     disabled=bool(problem) or not current or len(report_jd.strip()) < 20):
            try:
                with st.spinner('Comparing your resume with the posting…'):
                    report = build_report(report_jd, current['text'], store, report_provider,
                                          application={'company': company, 'role': role}, resume_name=current['name'])
                st.session_state.report_id = report['id']
            except ValueError as exc:
                validation_message(exc)
            except Exception as exc:
                st.error(failure_message(exc))
    shown = next((r for r in store.reports() if r['id'] == st.session_state.get('report_id')), None)
    if shown:
        with st.container(border=True):
            report_view(shown)
            st.markdown('#### Edited your resume?')
            unchanged = bool(current) and digest(current['text']) == shown['resume_hash']
            st.caption('Upload or paste the new version under "1. Your resume", then re-score this job to see what changed.'
                       if unchanged else f"Re-score this job with **{current['name'] if current else 'your resume'}**.")
            rescore_problem = configuration_problem(shown['provider'])
            if st.button('Re-score with my current resume', disabled=unchanged or not current or bool(rescore_problem)):
                try:
                    with st.spinner('Re-scoring with your updated resume…'):
                        updated = build_report(shown['job_description'], current['text'], store, shown['provider'],
                                               application=shown['application'], resume_name=current['name'], previous=shown)
                    st.session_state.report_id = updated['id']
                    st.rerun()
                except ValueError as exc:
                    validation_message(exc)
                except Exception as exc:
                    st.error(failure_message(exc))

elif page == 'Report history':
    hero('Report history', 'Every match report you have run, newest first.')
    reports = store.reports()
    if not reports:
        st.info('No reports yet. Create one on the Match report page.')
    for r in reports:
        with st.container(border=True):
            info_col, action_col = st.columns([5, 1], vertical_alignment='center')
            label = ' — '.join(v for v in (r['application'].get('company'), r['application'].get('role')) if v) or 'Job match report'
            percent = r['score']['overall'] or 0
            info_col.markdown(f'**{escape(label)}** &nbsp;<span class="pill" style="background:{score_color(percent)}26;'
                              f'color:{score_color(percent)}">{percent}% match</span>', unsafe_allow_html=True)
            rescored = f" · re-scored {r['changes']['score_change']:+d}" if r.get('changes') else ''
            info_col.caption(f"{r['created'][:16].replace('T', ' ')} · {r['model']} · {r.get('resume_name', '')}{rescored}")
            if action_col.button('Open', key='report_' + r['id']):
                st.session_state.report_id = r['id']
                go_to('Match report')
                st.rerun()

elif page == 'Compare jobs':
    hero('Compare jobs', 'Rank postings by how well your resume fits, and see what each one still needs.')
    reports = store.reports()
    if len(reports) < 2:
        st.info('Create match reports for at least two jobs to compare them.')
    else:
        # Default to the newest report for each posting, so re-scores do not crowd out other jobs.
        latest = list({r['job_hash']: r for r in reversed(reports)}.values())[::-1]
        labels = {r['id']: f"{report_label(r)} · {r['created'][:10]} · {r['score']['overall']}%" for r in reports}
        chosen = st.multiselect('Reports to compare', list(labels), default=[r['id'] for r in latest[:6]],
                                format_func=labels.get, max_selections=10)
        rows = compare_reports([r for r in reports if r['id'] in chosen])
        bars = ''.join(
            f'<div class="bar-row"><div class="rank">#{n}</div>'
            f'<div class="job">{escape(row["job"])}<small>{row["created"][:10]} · {row["strong"]} strong, '
            f'{row["partial"]} partial, {row["missing"]} missing</small></div>'
            f'<div class="bar"><div style="width:{row["overall"]}%;background:{score_color(row["overall"])}"></div></div>'
            f'<div class="pct" style="color:{score_color(row["overall"])}">{row["overall"]}%</div></div>'
            for n, row in enumerate(rows, 1))
        if bars:
            st.markdown(f'<div class="score-card" style="display:block">{bars}</div>', unsafe_allow_html=True)
        for n, row in enumerate(rows, 1):
            gaps = row['required_gaps']
            with st.expander(f"#{n} {row['job']} — {len(gaps)} required item{'s' if len(gaps) != 1 else ''} missing"):
                st.caption('Required: ' + ('n/a' if row['required'] is None else f"{row['required']}%"))
                for gap in gaps:
                    st.markdown('- ' + gap)
                if not gaps:
                    st.caption('No required items are missing.')
                if st.button('Open report', key='compare_' + row['id']):
                    st.session_state.report_id = row['id']
                    go_to('Match report')
                    st.rerun()

elif page == 'My experience':
    st.header('My experience')
    st.caption('Your resume and saved entries are the source of truth. Generated text is checked against them.')
    resume_tab, jobs_tab, evidence_tab = st.tabs(['Resume & contact', f'Jobs ({len(career.employments)})',
                                                  f'Evidence ({len(career.evidence)})'])
    with resume_tab:
        with st.container(border=True):
            st.subheader('Import a resume')
            resume_upload = st.file_uploader('Load a resume as my history', type=['docx', 'txt'])
            intake_provider = st.selectbox('Resume extraction provider', ['openai', 'anthropic'],
                help='The resume is sent to this provider to extract jobs and bullets (API charges may apply). '
                     'The original is kept locally; existing facts are never deleted.')
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
        with st.form('identity', border=True):
            st.subheader('Contact details')
            name = st.text_input('Name', career.display_name)
            contact = st.text_area('Contact details', '\n'.join(career.contact), placeholder='Email, location, portfolio link — one per line')
            if st.form_submit_button('Save contact details'):
                updated = career.model_copy(update={'display_name': name, 'contact': lines(contact)})
                save_career(updated)
                st.rerun()

    with jobs_tab:
        st.caption('Jobs stay in reverse chronological order. Tailoring changes bullets, never employers, titles or dates.')
        left, right = st.columns([3, 2], gap='large')
        with left:
            if not career.employments:
                st.info('No jobs yet. Import a resume or add a role.')
            for job in sorted(career.employments, key=lambda j: str(j.start), reverse=True):
                with st.container(border=True):
                    st.markdown(f'**{job.employer}** · {job.resume_display_title or job.official_title}')
                    st.caption(f'{job.official_title} · {job.start} – {job.end or "Present"}')
        with right:
            chosen_role = st.selectbox('Add or update a role', ['New role'] + [j.id for j in career.employments],
                format_func=lambda x: x if x == 'New role' else next(f'{j.employer} — {j.official_title}' for j in career.employments if j.id == x))
            job = next((j for j in career.employments if j.id == chosen_role), None)
            with st.form('role_' + chosen_role):
                employer = st.text_input('Employer', job.employer if job else '')
                title = st.text_input('Official job title', job.official_title if job else '')
                display = st.text_input('Descriptive resume title (optional)', (job.resume_display_title or '') if job else '')
                display_ok = st.checkbox('I approve this descriptive title', value=job.resume_display_title_approved if job else False)
                start_col, end_col = st.columns(2)
                start = start_col.text_input('Start (YYYY-MM)', str(job.start) if job else '')
                end = end_col.text_input('End (blank if current)', str(job.end) if job and job.end else '')
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

    with evidence_tab:
        duplicates = duplicate_groups(career)
        if duplicates:
            with st.container(border=True):
                st.warning(f"{len(duplicates)} item{'s are' if len(duplicates) != 1 else ' is'} saved more than once "
                           'in different formats. Drafts already use one copy of each.')
                for group in duplicates:
                    st.caption('• ' + (group[0].supported_wording or [group[0].project])[0][:120])
                if st.button('Merge duplicates', help='Keeps the version you confirmed and records the other copy as an extra source.'):
                    save_career(merge_duplicates(career)[0])
                    st.rerun()
        employers = {j.id: j.employer for j in career.employments}
        groups = {}
        for e in career.evidence:
            groups.setdefault(evidence_group(e, employers), []).append(e)
        if st.session_state.get('edit_id') not in ['New evidence'] + [e.id for e in career.evidence]:
            st.session_state.edit_id = 'New evidence'
        left, right = st.columns([3, 2], gap='large')
        with left:
            search_col, group_col = st.columns([3, 2])
            search = search_col.text_input('Find evidence', placeholder='Projects, tools or accomplishments')
            shown_group = group_col.selectbox('Show', ['All'] + list(groups))
            if not career.evidence:
                st.info('Add a role in Jobs, then add an accomplishment here, or load the synthetic example from the sidebar.')
            for group, records in groups.items():
                matches = [e for e in records if not search or search.lower() in json.dumps(e.model_dump(mode='json')).lower()]
                if shown_group not in ('All', group) or not matches:
                    continue
                st.markdown(f'#### {group} · {len(matches)}')
                for e in matches:
                    first = (e.supported_wording or [''])[0]
                    with st.expander(e.project + (' — ' + first[:60] + ('…' if len(first) > 60 else '') if first else '')):
                        st.caption(f'{e.kind.title()} · {e.ownership.title()}')
                        for statement in e.supported_wording:
                            st.write(statement)
                        if e.technologies:
                            st.write('**Tools:** ' + '; '.join(f'{t.name} — {t.usage} ({t.context})' for t in e.technologies))
                        if e.prohibited_inferences:
                            st.write('**Do not imply:** ' + '; '.join(e.prohibited_inferences))
                        st.caption(' · '.join(f'Source: {source.reference}' for source in e.sources))
                        st.button('Edit', key='edit_' + e.id, on_click=edit_evidence, args=(e.id,))
        with right:
            edit_id = st.selectbox('Add or edit evidence', ['New evidence'] + [e.id for e in career.evidence], key='edit_id',
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
                    help='What you personally did. Keep metric units and qualifiers such as estimated or expected.')
                actions = st.text_area('Actions you personally performed — one per line', '\n'.join(current.actions) if current else '')
                tools = st.data_editor([t.model_dump() for t in current.technologies] if current and current.technologies else
                    [{'name': '', 'usage': '', 'context': 'professional', 'category': 'Tools'}], num_rows='dynamic',
                    column_config={'context': st.column_config.SelectboxColumn('Context', options=['professional', 'portfolio', 'academic', 'training'], required=True)}, key='tools_' + edit_id)
                metrics = st.data_editor([m.model_dump() for m in current.metrics] if current and current.metrics else
                    [{'value': 0.0, 'unit': '', 'qualifier': 'estimated'}], num_rows='dynamic',
                    column_config={'qualifier': st.column_config.SelectboxColumn('Qualifier', options=['realized', 'estimated', 'expected'], required=True)}, key='metrics_' + edit_id)
                prohibited = st.text_area('What this must not imply — one per line', '\n'.join(current.prohibited_inferences) if current else '',
                    placeholder='Peer training does not mean people management')
                if st.form_submit_button('Save evidence', type='primary'):
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

elif page == 'Create application':
    st.header('Tailor your next application')
    if not career.evidence:
        st.info('First add your experience in My experience, import a backup, or try the synthetic example in the sidebar.')
    with st.container(border=True):
        st.subheader('1. The role')
        company_col, role_col = st.columns(2)
        company_name = company_col.text_input('Company (optional)')
        role_name = role_col.text_input('Role (optional)')
        with st.expander('Load from a job posting link'):
            job_url = st.text_input('Job posting URL', placeholder='https://company.example/careers/data-engineer',
                help='Public pages only. Sites that need a sign-in (such as LinkedIn) usually block this; paste the text instead.')
            if st.button('Load posting', disabled=not job_url):
                try:
                    with st.spinner('Reading the posting…'):
                        st.session_state.job_description = load_job_url(job_url)
                    st.success('Posting loaded below. Check the text before continuing.')
                except ValueError as exc:
                    validation_message(exc)
        jd = st.text_area('Paste the job description', height=220, key='job_description',
                          placeholder='Paste the full job description, including qualifications and responsibilities.')
        include_cover_letter = st.checkbox('Include a cover letter', value=True)

    matching = len(jd.strip()) >= 20 and bool(career.evidence)
    if matching:
        try:
            requirements = analyze_job(jd, career)
        except ValueError as exc:
            validation_message(exc)
            requirements = []
        with st.container(border=True):
            st.subheader('2. How you match')
            summary = fit_report(requirements)
            if not requirements:
                st.warning('No job requirements were recognized. Add the responsibilities and qualifications from the posting.')
            else:
                cols = st.columns(4)
                cols[0].metric('Requirements with evidence', 'n/a' if summary['coverage_percent'] is None else f"{summary['coverage_percent']}%",
                               help=f"{summary['supported']} of {summary['total']} requirements share key words with your evidence. "
                                    'This quick preview uses word matching; live runs re-check each requirement with the model and explain it.')
                cols[1].metric('Direct evidence', summary['direct'])
                cols[2].metric('Transferable evidence', summary['transferable'])
                cols[3].metric('Gaps to review', summary['gaps'] + summary['clarifications'])
            gaps = [q for q in requirements if q.kind == 'skill' and q.classification in GAP_CLASSIFICATIONS]
            job_hash = digest(jd)
            intake_id = 'intake-' + job_hash
            saved_answers = store.follow_up_answers(job_hash)
            if gaps:
                st.markdown('**Follow-up questions** — answer only where you have facts to add. Gaps can stay gaps.')
            for q in gaps:
                with st.expander(('✓ ' if q.id in saved_answers else '') + q.text):
                    if q.id in saved_answers:
                        st.info('Saved response: ' + saved_answers[q.id]['answer'])
                    with st.form('followup_' + job_hash[:12] + q.id):
                        choice = st.radio('Do you have relevant experience?', ['Add experience', 'No relevant experience', 'Decide later'],
                                          horizontal=True, key='choice_' + job_hash[:12] + q.id)
                        answer = st.text_area('What did you personally do?', key='answer_' + job_hash[:12] + q.id,
                            help='Include scope and actual results. Label estimates and training; do not turn shared work into sole ownership.')
                        role_ids = st.multiselect('Where did you do this?', [j.id for j in career.employments],
                            format_func=lambda ident: next(f'{j.employer} — {j.official_title}' for j in career.employments if j.id == ident), key='roles_' + job_hash[:12] + q.id)
                        tool_col, usage_col = st.columns(2)
                        tool = tool_col.text_input('Tool or technology (optional)', key='tool_' + job_hash[:12] + q.id)
                        usage = usage_col.text_input('How you used it', key='usage_' + job_hash[:12] + q.id)
                        context_col, ownership_col = st.columns(2)
                        context = context_col.selectbox('Experience context', ['professional', 'portfolio', 'academic', 'training'], key='context_' + job_hash[:12] + q.id)
                        ownership = ownership_col.selectbox('Scope of involvement', ['contributed', 'owned', 'familiarity'], key='ownership_' + job_hash[:12] + q.id)
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

    with st.container(border=True):
        st.subheader(('3' if matching else '2') + '. Create your draft')
        mode = st.radio('Generation mode', ['Practice with mock models', 'Use OpenAI', 'Use Anthropic'], horizontal=True,
            help='Practice mode runs the whole workflow without API keys by copying your source statements. '
                 'Live providers write and review a tailored draft.')
        provider = {'Practice with mock models': 'mock', 'Use OpenAI': 'openai', 'Use Anthropic': 'anthropic'}[mode]
        if provider == 'mock':
            st.caption('Practice mode copies source statements; choose a live provider for a polished draft.')
        else:
            st.caption(f'Sends the job description, your evidence and drafts to {provider.title()} for writing and review.')
        with st.expander('Advanced settings'):
            separate = st.checkbox('Use a different provider for reviews', key='separate_reviewer')
            generator = provider
            reviewer = (st.selectbox('Review provider', ['mock', 'openai', 'anthropic'], index=['mock', 'openai', 'anthropic'].index(provider), key='rev_' + provider)
                        if separate else provider)
            model_col, review_model_col = st.columns(2)
            generator_model = model_col.text_input('Generation model', DEFAULT_MODELS[generator], key='gm_' + generator)
            reviewer_model = review_model_col.text_input('Review model', DEFAULT_MODELS[reviewer], key='rm_' + reviewer)
            factual_mode = st.selectbox('Factual checking', ['model_reviewed', 'strict'] if reviewer != 'mock' else ['strict'],
                help='Model-reviewed allows paraphrases backed by exact source quotes and independent checks. Strict requires exact source wording.')
            style_path = st.text_input('Approved style package', 'private/writing_style/approved-v3' if Path('private/writing_style/approved-v3').exists() else 'writing_style',
                help='The bundled profile is a neutral default. Point to your approved private package for personal guidance.')
            st.markdown('**Usage limits**')
            limit_cols = st.columns(4)
            cycles = limit_cols[0].number_input('Revision cycles', 0, 3, 2)
            token_budget = limit_cols[1].number_input('Token budget', min_value=1000, value=500000, step=50000)
            output_limit = limit_cols[2].number_input('Max output tokens per call', min_value=256, max_value=16000, value=12000,
                help='Separate from the total budget. Raise it if responses are cut off.')
            call_budget = limit_cols[3].number_input('Call budget', min_value=1, max_value=100, value=48, help='Includes retries.')
            st.markdown('**Writing checks**')
            check_cols = st.columns(3)
            quality_enabled = check_cols[0].checkbox('Check writing quality', value=True)
            minimum_bullet_words = check_cols[1].number_input('Flag bullets shorter than (words)', 0, 30, 4)
            minimum_letter_words = check_cols[2].number_input('Minimum cover-letter words (0 = off)', 0, 400, 0)
            plan = budget_plan(Settings(max_revisions=cycles, max_calls=call_budget, token_budget=token_budget, max_output_tokens=output_limit))
            st.caption(f"About {plan['normal_calls']} model calls with these settings ({plan['with_contract_corrections']} if reviewers need corrections). "
                       'Budgets are hard limits and are never raised automatically.')
        with st.expander('Provider readiness'):
            for label, selected_provider in [('Generator', generator), ('Reviewer', reviewer)]:
                present = not configuration_problem(selected_provider)
                st.caption(f'{label}: {selected_provider} · ' + ('no key needed' if selected_provider == 'mock' else 'key configured (not yet verified)' if present else 'key missing'))
            if st.button('Test selected providers with synthetic data', help='Sends one small request with fictional data per provider.'):
                for label, selected_provider, model in [('generator', generator, generator_model), ('reviewer', reviewer, reviewer_model)]:
                    with st.spinner('Testing ' + label + '…'):
                        result = check_provider(selected_provider, model, label)
                    store.event('readiness', 'synthetic_provider_test', result)
                    (st.success if result['status'] == 'passed' else st.error)(label.title() + ': ' + result['message'])
        problems = [message for p in set((generator, reviewer)) if (message := configuration_problem(p))]
        missing_jobs = missing_source_jobs(career)
        if missing_jobs:
            labels = '; '.join(j['employer'] + ' — ' + j['official_title'] for j in missing_jobs)
            problems.append('These saved jobs have no source bullets: ' + labels + '. Import your resume in My experience or restore a complete backup.')
        for message in problems:
            st.error(message)
        if st.button('Create my draft', type='primary', disabled=bool(problems) or not any(e.eligible for e in career.evidence) or len(jd.strip()) < 20):
            with st.status('Creating your draft…', expanded=True) as progress:
                def show_stage(name, revision):
                    if name in STAGE_LABELS:
                        progress.write(STAGE_LABELS[name] + (f' (revision {revision})' if revision else ''))
                try:
                    m = run(jd, career, store, Settings(generator=generator, reviewer=reviewer, factual_mode=factual_mode, include_cover_letter=include_cover_letter,
                        generator_model=generator_model, reviewer_model=reviewer_model, max_revisions=cycles,
                        token_budget=token_budget, max_calls=call_budget, max_output_tokens=output_limit, content_quality=ContentQualitySettings(enabled=quality_enabled,
                            minimum_bullet_words=minimum_bullet_words, minimum_letter_words=minimum_letter_words)), style_path=style_path,
                        application={'company': company_name, 'role': role_name}, on_stage=show_stage)
                except Exception as exc:
                    progress.update(label='Draft stopped', state='error')
                    st.error(failure_message(exc))
                else:
                    progress.update(label='Draft complete', state='complete', expanded=False)
                    st.session_state.run_id = m['id']
                    st.session_state.flash = (('warning', 'Finished with findings to review. Final export stays blocked while errors remain.')
                                              if m['status'] == 'needs_review' else ('success', 'Your draft is ready.'))
                    go_to('Review & download')
                    st.rerun()

elif page == 'Review & download':
    history = store.history()
    flash = st.session_state.pop('flash', None)
    if flash:
        getattr(st, flash[0])(flash[1])
    if not history:
        st.info('Your application previews and review notes appear here after you create a draft.')
    else:
        ids = [m['id'] for m in history]
        def run_label(ident):
            item = next(m for m in history if m['id'] == ident)
            return f"{application_label(item)} · {item['created'][:16].replace('T', ' ')} · {status_title(item['status'])}"
        selected = st.selectbox('Application', ids, format_func=run_label,
            index=ids.index(st.session_state.get('run_id')) if st.session_state.get('run_id') in ids else 0)
        m = store.get(selected)
        st.caption(application_label(m))
        st.subheader(status_title(m['status']), divider=STATUS_COLORS.get(m['status'], 'gray'))
        failed = m['status'] == 'failed'
        if m.get('failure'):
            st.error('Stopped at ' + m['failure']['stage'].replace('_', ' ') + ': ' + m['failure']['message'])
        elif failed:
            st.error('This run failed before saving a detailed diagnostic. Its stages are in Technical audit details.')
        st.caption(f"{m['revision_count']} revision cycles · {m.get('latency', 0):.1f} seconds · {m.get('stopping_reason', 'running').replace('_', ' ')}")
        if m['settings']['reviewer'] == 'mock':
            st.info('Practice output copies your evidence statements to test the workflow; it is not a tailored resume.')
        snapshot = None
        try:
            snapshot = store.career_snapshot(selected)
        except ValueError:
            st.error('The saved evidence snapshot is unavailable. Rerun before approval or export.')
        if failed and m['versions'] and snapshot:
            st.caption('This run did not finish. Its last unreviewed version is kept for inspection only.')
            with st.expander('Last saved version (incomplete)'):
                packet = Packet.model_validate(m['versions'][-1]['packet'])
                resume, letter = preview(packet, snapshot)
                st.markdown(resume)
                if m['settings'].get('include_cover_letter', True):
                    st.divider()
                    st.markdown(letter)
        elif m['versions'] and snapshot:
            if 'restored_from_version' in m['versions'][-1]:
                reason = ('the remaining budget could not cover the latest revision review'
                          if m.get('budget_stop') else
                          f"a later {m['restored_after_failure']['stage'].replace('_', ' ')} step failed"
                          if m.get('restored_after_failure') else
                          'a later review did not complete'
                          if m.get('stopping_reason') == 'review_unavailable_rollback'
                          else 'later edits introduced review errors')
                st.info(f"Showing reviewed version {m['versions'][-1]['restored_from_version'] + 1} because {reason}. All versions remain in the review history.")
            packet = Packet.model_validate(m['versions'][-1]['packet'])
            resume, letter = preview(packet, snapshot)
            requirements = [Requirement.model_validate(q) for q in m.get('requirements', [])]
            summary = fit_report(requirements, packet)
            final_findings = m['versions'][-1]['findings']
            model_matched = m.get('requirement_matching', {}).get('method') == 'model'
            def percent(value):
                return 'n/a' if value is None else f'{value}%'
            a, b, c, d = st.columns(4)
            a.metric('Requirements covered', percent(summary['coverage_percent']),
                     help=f"{summary['covered']} of {summary['total']} requirements are addressed by a passage that cites matching evidence. "
                          + ('Matching was checked by the model; see Requirement coverage for the reason behind each.' if model_matched
                             else 'Matching used shared words and can over-count related experience.')
                          + ' Not an ATS score or hiring prediction.')
            b.metric('Required covered', percent(summary['required_coverage_percent']),
                     help=f"Of the {summary['required_total']} requirements the posting marks as required.")
            c.metric('Experience gaps', summary['gaps'], help='Requirements with no matching evidence. See Requirement coverage.')
            d.metric('Must-fix findings', sum(f['severity'] == 'error' for f in final_findings))
            resume_tab, letter_tab, notes_tab, map_tab, export_tab = st.tabs(['Resume', 'Cover letter', 'Review notes', 'Requirement coverage', 'Approve & download'])
            with resume_tab:
                with st.container(border=True):
                    st.markdown(resume)
            with letter_tab:
                if m['settings'].get('include_cover_letter', True):
                    with st.container(border=True):
                        st.markdown(letter)
                else:
                    st.info('No cover letter requested for this application.')
            with notes_tab:
                quality_status = m['versions'][-1].get('content_quality_status', 'not_recorded')
                st.caption('Writing-quality checks: ' + quality_status.replace('_', ' ') + '. These are presentation heuristics, not factual certification.')
                findings_view(final_findings, {c.id: c.text for c in packet.resume + packet.cover_letter})
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
                with st.expander('Review history'):
                    for version in m['versions']:
                        st.markdown(f"**Version {version['number'] + 1}** · " + ', '.join(
                            f"{role} {receipt['status']}" for role, receipt in version.get('reviews', {}).items()))
                        for receipt in version.get('reviews', {}).values():
                            for attempt in receipt.get('attempts', []):
                                if attempt['status'] == 'rejected':
                                    st.caption('Review response corrected: ' + attempt['error'])
            with map_tab:
                labels = {'direct': 'Direct evidence', 'transferable': 'Transferable', 'unsupported': 'Gap', 'needs_clarification': 'Needs clarification'}
                order = {'unsupported': 0, 'needs_clarification': 1, 'transferable': 2, 'direct': 3}
                skills = sorted((q for q in m.get('requirements', []) if q.get('kind') != 'constraint'),
                                key=lambda q: (order[q['classification']], q['priority'] != 'required'))
                index = {e.id: e for e in snapshot.evidence}
                if not m.get('requirement_matching', {}).get('method') == 'model':
                    st.caption('Matched by shared words. Live runs explain each match.')
                st.dataframe([{'Match': labels[q['classification']], 'Priority': q['priority'].title(), 'Requirement': q['text'],
                               'Why': q.get('rationale') or '',
                               'Evidence': ', '.join(dict.fromkeys(index[i].project for i in q['evidence_ids'] if i in index))}
                              for q in skills], hide_index=True, width='stretch',
                             column_config={'Requirement': st.column_config.TextColumn(width='large'),
                                            'Why': st.column_config.TextColumn(width='large')})
                saved_answers = m.get('follow_up_answers', {})
                questions = [q for q in m.get('discovery_questions', []) if q.get('classification') in GAP_CLASSIFICATIONS]
                if questions:
                    st.markdown('**Gaps you can follow up on**')
                for question in questions:
                    saved = saved_answers.get(question['requirement_id'])
                    st.info(question['excerpt'] + '\n\n' + ('Your saved answer: ' + saved['answer'] if saved else question['prompt']))
            with export_tab:
                blocked = bool(m.get('validation')) or any(f['severity'] == 'error' for f in final_findings)
                if blocked:
                    st.warning('Must-fix findings block approval and final export. You can still download a labeled draft.')
                reviewed = st.checkbox('I reviewed the wording, supporting evidence, dates and unresolved gaps.', key='ack_' + selected)
                approve_col, prepare_col = st.columns(2)
                if approve_col.button('Approve this application', type='primary', disabled=not reviewed or blocked):
                    try:
                        approve(store, selected, snapshot, acknowledged=True)
                        st.session_state['downloads'] = [str(p) for p in export(store, selected, snapshot, draft=False)]
                        st.rerun()
                    except ValueError as exc:
                        validation_message(exc)
                draft = not m['approved']
                if prepare_col.button('Prepare documents', help='Downloads are labeled drafts until you approve this application.'):
                    try:
                        st.session_state['downloads'] = [str(p) for p in export(store, selected, snapshot, draft=draft)]
                        if store.get(selected).get('render_warnings'):
                            st.warning('Invalid hidden characters were replaced with visible marks in this draft. Correct or regenerate it before final approval.')
                    except ValueError as exc:
                        validation_message(exc)
                for path in st.session_state.get('downloads', []):
                    p = Path(path)
                    if selected in str(p) and p.exists() and p.parent.name == ('draft' if draft else 'final'):
                        st.download_button('Download ' + p.name, p.read_bytes(), file_name=p.name)
                st.download_button('Download match & review report', review_report(m, snapshot), 'match-report.md', 'text/markdown')
                with st.expander('Optional PDF & layout review'):
                    st.caption(f"Version {m['versions'][-1]['number'] + 1}. Needs LibreOffice installed locally. Rendering does not approve facts or writing.")
                    page_cols = st.columns(2)
                    resume_pages = page_cols[0].number_input('Preferred maximum resume pages', 1, 10, 2)
                    letter_pages = page_cols[1].number_input('Preferred maximum cover-letter pages', 1, 5, 1)
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
                        if layout['status'] == 'rendered' and layout['documents']:
                            visual_ack = st.checkbox('I opened these PDFs and reviewed their layout.', key='layout_ack_' + selected + str(draft))
                            if st.button('Record visual review', disabled=not visual_ack):
                                from career_pipeline.layout import confirm_layout
                                try:
                                    confirm_layout(store, selected)
                                    st.success('Visual review recorded for these exact PDFs. Factual approval is separate.')
                                except ValueError as exc:
                                    validation_message(exc)
        elif not m['versions']:
            st.info('This run did not save a document version.')
        with st.expander('Technical details'):
            if m.get('failure'):
                st.download_button('Download diagnostic summary', json.dumps({'run_id': m['id'], 'failure': m['failure'], 'stages': m['stages']}, indent=2), 'run-diagnostic.json', 'application/json')
            st.download_button('Download full run audit (JSON)', json.dumps(m, indent=2), 'audit.json', 'application/json', key='audit_' + selected)
            # The full audit can be megabytes; only send it to the browser on request.
            if st.toggle('Show full audit here', key='show_audit_' + selected):
                st.json(m, expanded=False)

elif page == 'Draft history':
    st.header('Draft history')
    history = store.history()
    if not history:
        st.info('No applications yet. Create your first draft to start a history.')
    for m in history:
        with st.container(border=True):
            info_col, action_col = st.columns([5, 1], vertical_alignment='center')
            cost = m.get('estimated_cost')
            info_col.markdown(f"**{application_label(m)}** · :{STATUS_COLORS.get(m['status'], 'gray')}[{status_title(m['status'])}]")
            info_col.caption(f"{m['created'][:16].replace('T', ' ')} · {m.get('latency', 0):.1f} s · {m['revision_count']} revisions · "
                             f"cost {f'${cost:.4f}' if cost is not None else 'not configured'}")
            if action_col.button('Open', key='history_' + m['id']):
                st.session_state.run_id = m['id']
                go_to('Review & download')
                st.rerun()

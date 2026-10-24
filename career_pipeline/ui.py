import difflib
import json
import os
from pathlib import Path
import streamlit as st
from career_pipeline.models import Career, Packet, Settings, DEFAULT_MODELS
from career_pipeline.store import Store
from career_pipeline.pipeline import run
from career_pipeline.export import approve, export, preview

st.set_page_config(page_title='Evidence / Application Studio', layout='wide')
st.title('Evidence / Application Studio')
st.caption('Single-user workspace · verified facts · visible gaps · bounded review')
store = Store()
tab1, tab2, tab3 = st.tabs(['Evidence & job', 'Packet & review', 'Run history'])
with tab1:
    st.info('The bundled candidate is synthetic. Put personal files in ignored private/ or local/. Live mode sends the job, selected career evidence, profile and drafts to the selected live provider. Run history contains private snapshots locally.')
    evidence_path = st.text_input('Local evidence JSON path', 'fixtures/career.json')
    if st.button('Load local evidence'):
        try:
            st.session_state['career_editor'] = Path(evidence_path).read_text()
        except OSError:
            st.error('Could not read the selected local evidence file.')
    if 'career_editor' not in st.session_state:
        st.session_state['career_editor'] = Path('fixtures/career.json').read_text()
    raw = st.text_area('Career evidence JSON — inspect and edit', height=300, key='career_editor')
    style_path = st.text_input('Approved style package directory', 'writing_style')
    career = None
    try:
        career = Career.model_validate_json(raw)
        st.success(f'{sum(e.eligible for e in career.evidence)} confirmed records')
    except ValueError as exc:
        st.error(str(exc))
    if st.button('Save evidence locally') and career:
        Path('local').mkdir(exist_ok=True)
        Path('local/career.json').write_text(career.model_dump_json(indent=2))
        st.success('Saved local/career.json')
    jd = st.text_area('Job description', Path('fixtures/job.txt').read_text(), height=180)
    c1, c2 = st.columns(2)
    providers = ['mock', 'anthropic', 'openai']
    generator_default = os.getenv('GENERATOR_PROVIDER', 'mock')
    reviewer_default = os.getenv('REVIEWER_PROVIDER', 'mock')
    generator = c1.selectbox('Generator', providers, index=providers.index(generator_default) if generator_default in providers else 0)
    reviewer = c2.selectbox('Reviewer', providers, index=providers.index(reviewer_default) if reviewer_default in providers else 0)
    with st.expander('Model and budget settings'):
        generator_model = st.text_input('Generator model', DEFAULT_MODELS[generator], key='generator_model_' + generator)
        reviewer_model = st.text_input('Reviewer model', DEFAULT_MODELS[reviewer], key='reviewer_model_' + reviewer)
        token_budget = st.number_input('Token budget', min_value=1000, value=250000)
        call_budget = st.number_input('Call budget (includes retry reservations)', min_value=1, max_value=100, value=48)
    factual_mode = st.selectbox('Factual validation mode', ['model_reviewed','strict'] if reviewer != 'mock' else ['strict'])
    cycles = st.number_input('Maximum revision cycles', 0, 3, 2)
    if st.button('Create auditable draft', type='primary', disabled=career is None):
        try:
            m = run(jd, career, store, Settings(generator=generator, reviewer=reviewer, factual_mode=factual_mode, generator_model=generator_model, reviewer_model=reviewer_model, max_revisions=cycles, token_budget=token_budget, max_calls=call_budget), style_path=style_path)
            st.session_state['run_id'] = m['id']
            st.success('Draft created. Open Packet & review.')
        except Exception as exc:
            st.error(f'Run failed ({type(exc).__name__}). Inspect run history; document contents are not logged.')
with tab2:
    history = store.history()
    ids = [m['id'] for m in history]
    if ids:
        selected = st.selectbox('Run', ids, index=ids.index(st.session_state.get('run_id')) if st.session_state.get('run_id') in ids else 0)
        m = store.get(selected)
        st.write(f"Status: **{m['status']}** · Revisions: {m['revision_count']} · Stop: {m.get('stopping_reason', 'running')}")
        if m.get('requirements'):
            st.dataframe(m['requirements'], width='stretch')
        if m.get('discovery_questions'):
            with st.expander('Optional questions for evidence gaps'):
                st.caption('Answers require a separate evidence edit and confirmation; they do not auto-fill gaps.')
                st.json(m['discovery_questions'])
        if m['settings']['reviewer'] == 'mock':
            st.warning('MOCK review: deterministic pipeline validation, not a live adversarial model assessment.')
        snapshot = None
        try:
            snapshot = store.career_snapshot(selected)
        except ValueError:
            st.error('Saved input snapshot unavailable; rerun before approval/export.')
        if m['versions'] and snapshot:
            packet = Packet.model_validate(m['versions'][-1]['packet'])
            left, right = st.columns(2)
            resume, letter = preview(packet, snapshot)
            left.markdown(resume)
            right.markdown(letter)
            st.subheader('Findings & unresolved gaps')
            for version in m['versions']:
                with st.expander(f"Version {version['number']} — reviewer receipts and findings", expanded=version is m['versions'][-1]):
                    st.json(version.get('reviews', {}))
                    st.json(version['findings'])
            with st.expander('Claim provenance & manifest'):
                st.json(m)
            if len(m['versions']) > 1:
                before = json.dumps(m['versions'][-2]['packet'], indent=2).splitlines()
                after = json.dumps(packet.model_dump(), indent=2).splitlines()
                st.code('\n'.join(difflib.unified_diff(before, after)), language='diff')
            reviewed = st.checkbox('I reviewed the wording, evidence, dates and unresolved gaps for this packet.')
            if st.button('Approve packet', disabled=not reviewed):
                try:
                    approve(store, selected, snapshot, acknowledged=True)
                    st.success('Approved')
                except ValueError as exc:
                    st.error(str(exc))
            draft = st.checkbox('Export labeled draft', value=True)
            if st.button('Prepare downloads'):
                try:
                    st.session_state['downloads'] = [str(p) for p in export(store, selected, snapshot, draft=draft)]
                except ValueError as exc:
                    st.error(str(exc))
            for path in st.session_state.get('downloads', []):
                p = Path(path)
                if selected in str(p):
                    st.download_button(p.name, p.read_bytes(), file_name=p.name)
    else:
        st.write('Create a draft to inspect its requirement map and provenance.')
with tab3:
    st.dataframe([{k: m.get(k) for k in ('id','created','status','latency','estimated_cost','revision_count')} for m in store.history()], width='stretch')
    st.caption('Mock usage is zero. Unknown live cost is shown as unavailable, never estimated without configured rates.')

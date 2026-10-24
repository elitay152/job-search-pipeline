import difflib
import json
from pathlib import Path
import streamlit as st
from career_pipeline.models import Career, Packet, Settings
from career_pipeline.store import Store
from career_pipeline.pipeline import run
from career_pipeline.export import approve, export, preview

st.set_page_config(page_title='Evidence / Application Studio', layout='wide')
st.title('Evidence / Application Studio')
st.caption('Single-user workspace · verified facts · visible gaps · bounded review')
store = Store()
tab1, tab2, tab3 = st.tabs(['Evidence & job', 'Packet & review', 'Run history'])
with tab1:
    st.info('The bundled candidate is synthetic. Put personal files in ignored private/ or local/. Live mode sends the job, selected career evidence, profile and drafts to Anthropic. Run history contains private snapshots locally.')
    raw = st.text_area('Career evidence JSON — inspect and edit', Path('fixtures/career.json').read_text(), height=300)
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
    generator = c1.selectbox('Generator', ['mock', 'anthropic'])
    reviewer = c2.selectbox('Reviewer', ['mock', 'anthropic'])
    cycles = st.number_input('Maximum revision cycles', 0, 3, 2)
    if st.button('Create auditable draft', type='primary', disabled=career is None):
        try:
            m = run(jd, career, store, Settings(generator=generator, reviewer=reviewer, max_revisions=cycles, token_budget=100000))
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
        if m['versions'] and career:
            packet = Packet.model_validate(m['versions'][-1]['packet'])
            left, right = st.columns(2)
            resume, letter = preview(packet, career)
            left.markdown(resume)
            right.markdown(letter)
            st.subheader('Findings & unresolved gaps')
            st.json(m['versions'][-1]['findings'])
            with st.expander('Claim provenance & manifest'):
                st.json(m)
            if len(m['versions']) > 1:
                before = json.dumps(m['versions'][-2]['packet'], indent=2).splitlines()
                after = json.dumps(packet.model_dump(), indent=2).splitlines()
                st.code('\n'.join(difflib.unified_diff(before, after)), language='diff')
            reviewed = st.checkbox('I reviewed the wording, evidence, dates and unresolved gaps for this packet.')
            if st.button('Approve packet', disabled=not reviewed):
                try:
                    approve(store, selected, career, acknowledged=True)
                    st.success('Approved')
                except ValueError as exc:
                    st.error(str(exc))
            draft = st.checkbox('Export labeled draft', value=True)
            if st.button('Prepare downloads'):
                try:
                    st.session_state['downloads'] = [str(p) for p in export(store, selected, career, draft=draft)]
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

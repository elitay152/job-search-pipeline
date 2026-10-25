"""Regression: the user's structural objections must be caught by the pipeline itself.

All career data in this module is synthetic. Network integrations are separately mocked.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from docx import Document
from career_pipeline.models import Career, Evidence, Employment, Packet, Claim, Settings
from career_pipeline.pipeline import run, extract
from career_pipeline.providers import MockProvider, AnthropicProvider
from career_pipeline.store import Store
from career_pipeline.export import export, approve, preview
from career_pipeline.report import review_report

@pytest.fixture
def career():
    job = Employment(id='job-1', employer='Synthetic Warehouse Co', official_title='Analyst III',
        resume_display_title='Data Engineer', resume_display_title_approved=True,
        start='2023-10', end='2026-08')
    records = []
    statements = ['Built Python data ingestion.', 'Configured pipeline alerts.',
                  'Documented reusable warehouse tables.', 'Added duplicate checks.']
    for i, text in enumerate(statements):
        records.append(Evidence(id=f'e{i}', employment_ids=['job-1'], project='Synthetic ingestion',
            actions=[text], ownership='contributed', technologies=[{'name':'Python','usage':'Ingestion','category':'Languages'}],
            sources=[{'reference':'synthetic://confirmed','status':'user_confirmed'}], confirmed_statements=[text]))
    for kind, ident, text in [('publication','p1','Example, M. (2026). Synthetic Pipeline Study. Example Journal.'),
                             ('education','d1','MS, Example University | 2023-06')]:
        records.append(Evidence(id=ident, kind=kind, project=kind, actions=[], ownership='contributed',
            technologies=[], sources=[{'reference':'synthetic://confirmed','status':'user_confirmed'}], confirmed_statements=[text]))
    records.append(Evidence(id='training', kind='skill', project='Training', actions=[], ownership='familiarity',
        technologies=[{'name':'Azure Data Factory','usage':'Training only','context':'training','category':'Platforms'}],
        sources=[{'reference':'synthetic://confirmed','status':'user_confirmed'}], confirmed_statements=['Completed Azure Data Factory training.']))
    return Career(display_name='Morgan Example (Synthetic)', employments=[job], evidence=records)

@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path/'runs.sqlite'))

JD = 'Qualifications\n- Python data ingestion and pipeline alerts.\n- SQL Server experience required.\n- Azure DevOps preferred.\n- Documentation required.'

def thin(career):
    text = career.evidence[0].confirmed_statements[0]
    return Packet(resume=[Claim(id='r1', text=text, evidence_ids=['e0'])],
                  cover_letter=[Claim(id='c1', text=text, evidence_ids=['e0'])])

def test_actual_review_revision_and_export(career, store, tmp_path):
    m = run(JD, career, store, seed_packet=thin(career))
    assert m['revision_count'] == 1
    assert len(m['versions']) == 2 and not m['approved']
    first, final = m['versions']
    assert {'thin_role','missing_skills','missing_section_content'} <= {f['code'] for f in first['findings']}
    for version in m['versions']:
        assert set(version['reviews']) == {'evidence','recruiter','voice'}
        assert all(x['status']=='passed' for x in version['reviews'].values())
    assert not [f for f in final['findings'] if f['severity'] in ('error','suggestion')]
    assert any(f['severity']=='gap' for f in final['findings'])  # SQL Server isn't invented.
    assert m['review_mode']=='mock'
    assert {t['role'] for t in m['telemetry'] if t['stage']=='review'} == {'evidence','recruiter','voice'}
    report = review_report(m, career)
    assert 'MOCK' in report and 'Revision diff' in report and 'thin_role' not in report  # readable messages, not just codes
    with pytest.raises(ValueError):
        export(store, m['id'], career, tmp_path)
    approve(store, m['id'], career, True)
    paths = export(store, m['id'], career, tmp_path)
    resume = Document(next(p for p in paths if p.name=='resume.docx'))
    text = '\n'.join(p.text for p in resume.paragraphs)
    assert 'Publications' in text and 'Synthetic Pipeline Study' in text
    assert 'Education' in text and 'Technical Skills' in text
    assert 'Azure Data Factory (training)' in text and 'Oct 2023' in text
    assert 'Analyst III' not in text and 'Data Engineer' in text
    assert not any(i in text for i in ['job-1','evidence_ids','synthetic://'])
    assert store.career_snapshot(m['id']).employments[0].start == '2023-10'

@pytest.mark.parametrize('value',['2024-00','2024-13','0000-01','2024-2','2024-02-31'])
def test_invalid_months(value):
    with pytest.raises(ValidationError):
        Employment(id='x',employer='Example',official_title='Engineer',start=value)

def test_month_precision_and_reversed_dates(career):
    encoded = career.model_dump_json()
    assert '2023-10-01' not in encoded
    assert Career.model_validate_json(encoded).employments[0].start=='2023-10'
    with pytest.raises(ValidationError, match='precedes'):
        Employment(id='x',employer='Example',official_title='Engineer',start='2024-06',end='2024-05')

def test_reviewer_error_is_not_waived(monkeypatch, career, store):
    original = MockProvider.complete
    def provider(self, task, payload, model):
        result = original(self, task, payload, model)
        if task=='review' and payload['role']=='evidence':
            result['findings'].append({'role':'evidence','claim_id':(payload['packet']['resume']+payload['packet']['cover_letter'])[0]['id'],
                'severity':'error','code':'ambiguous_scope','message':'Clarify source scope.'})
        return result
    monkeypatch.setattr(MockProvider,'complete',provider)
    m=run(JD,career,store)
    assert m['status']=='needs_review' and not m['validation']
    with pytest.raises(ValueError,match='errors'):
        approve(store,m['id'],career,True)

def test_review_failure_retains_candidate_and_blocks_approval(monkeypatch, career, store, tmp_path):
    original=MockProvider.complete
    def provider(self,task,payload,model):
        if task=='review' and payload['role']=='voice':
            raise ConnectionError('synthetic failure')
        return original(self,task,payload,model)
    monkeypatch.setattr(MockProvider,'complete',provider)
    with pytest.raises(ConnectionError):run(JD,career,store)
    m=store.history()[0]
    assert m['status']=='failed' and m['versions'][0]['packet']['resume']
    assert m['versions'][0]['reviews']['evidence']['status']=='passed'
    assert m['versions'][0]['reviews']['voice']['status']=='failed'
    assert m['estimated_cost'] is None
    with pytest.raises(ValueError):approve(store,m['id'],career,True)
    assert export(store,m['id'],career,tmp_path,draft=True)

def test_auditor_requires_complete_receipt(monkeypatch,career,store):
    original=MockProvider.complete
    def provider(self,task,payload,model):
        result=original(self,task,payload,model)
        if task=='review' and payload['role']=='evidence':result['reviewed_claim_ids']=[]
        return result
    monkeypatch.setattr(MockProvider,'complete',provider)
    with pytest.raises(ValueError,match='every claim'):run(JD,career,store)
    assert store.history()[0]['versions'][0]['reviews']['evidence']['status']=='failed'
    assert next(s for s in store.history()[0]['stages'] if s['name']=='review_evidence')['status']=='failed'

def test_zero_revisions_keeps_findings(career,store):
    m=run(JD,career,store,Settings(max_revisions=0),seed_packet=thin(career))
    assert len(m['versions'])==1 and m['stopping_reason']=='revision_limit'
    assert any(f['code']=='thin_role' for f in m['unresolved_findings'])

def test_inline_preferred_does_not_leak_to_next_requirement():
    rows=extract('Qualifications\n- Snowflake preferred.\n- Python required.\n- Documentation and SQL.')
    assert [r.priority for r in rows]==['preferred','required','required']


def test_anthropic_sdk_contract_without_network(monkeypatch):
    import anthropic
    import httpx
    calls=[]
    real_client=anthropic.Anthropic
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        assert body['tool_choice']=={'type':'tool','name':'return_result'}
        assert body['tools'][0]['input_schema']['type']=='object'
        output={'findings':[],'reviewed_claim_ids':['r1','c1']}
        return httpx.Response(200,json={'id':'msg_synthetic','type':'message','role':'assistant',
          'model':'synthetic-reviewer','content':[{'type':'tool_use','id':'tool_synthetic','name':'return_result','input':output}],
          'stop_reason':'tool_use','stop_sequence':None,'usage':{'input_tokens':30,'output_tokens':20}})
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-not-a-real-key')
    monkeypatch.setattr(anthropic,'Anthropic',lambda **kwargs: real_client(**kwargs,
        http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    for role in ('evidence','recruiter','voice'):
        result=AnthropicProvider().complete('review',{'role':role,'style':'APPROVED_GUIDANCE','packet':{}},'synthetic-reviewer')
        assert result['input_tokens']==30 and result['output_tokens']==20
    assert len(calls)==3
    assert 'adversarial evidence auditor' in calls[0]['system']
    assert 'skeptical recruiter' in calls[1]['system']
    assert 'voice editor' in calls[2]['system']
    assert all('APPROVED_GUIDANCE' not in c['messages'][0]['content'] for c in calls)


def test_private_intake_does_not_promote_proposed_or_uncertain_claims(tmp_path):
    from career_pipeline.intake import import_intake
    root=tmp_path/'intake';root.mkdir()
    draft={'display_name':'Morgan Example (Synthetic)','records':[
      {'id':'r1','topic':'Legacy queries','record_type':'employment','employment_as_reported':{
       'employer_as_written':'Example Co','official_title':'Analyst III','start_month':'2023-10',
       'end_month':'2026-08','month_range_status':'user_confirmed','resume_display_title':'Data Engineer',
       'resume_display_title_status':'user_approved_descriptive_label'}},
      {'id':'p1','topic':'Source citation','record_type':'publication','candidate_wording_variants':[{'text':'Example publication citation.'}]}]}
    ledger={'confirmations':[{'id':'confirmation-1','status':'user_confirmed_for_listed_facts_only',
      'record_ids':['r1'],'confirmed_facts':{'technology':'SQL Server','personally_performed':['Wrote queries']},
      'candidate_wording':'Led 50 engineers and saved $8 million.'}]}
    (root/'career.evidence-draft.json').write_text(json.dumps(draft))
    (root/'user-confirmations.json').write_text(json.dumps(ledger))
    career=import_intake(root,tmp_path/'career.json')
    assert career.employments[0].start=='2023-10'
    confirmed=[e for e in career.evidence if e.eligible]
    assert len(confirmed)==1 and confirmed[0].confirmed_statements==['SQL Server: Wrote queries.']
    assert all(not e.approved_wording for e in career.evidence)
    assert not next(e for e in career.evidence if e.id=='p1').eligible
    assert '50 engineers' not in career.model_dump_json()
    with pytest.raises(ValueError,match='overwrite'):import_intake(root,tmp_path/'career.json')


def test_ui_historical_preview_uses_saved_snapshot(monkeypatch,tmp_path):
    import shutil
    from streamlit.testing.v1 import AppTest
    root=Path(__file__).resolve().parents[1]
    shutil.copytree(root/'fixtures',tmp_path/'fixtures')
    shutil.copytree(root/'writing_style',tmp_path/'writing_style')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('CAREER_DB',str(tmp_path/'ui.sqlite'))
    app=AppTest.from_file(str(root/'career_pipeline/ui.py')).run(timeout=20)
    next(b for b in app.button if b.label=='Load synthetic example').click().run(timeout=20)
    next(t for t in app.text_area if t.label=='Paste the job description').set_value((tmp_path/'fixtures/job.txt').read_text()).run(timeout=20)
    next(b for b in app.button if b.label=='Create my draft').click().run(timeout=20)
    assert not app.exception
    next(t for t in app.text_input if t.label=='Name').set_value('Different Synthetic Editor Name')
    next(b for b in app.button if b.label=='Save contact details').click().run(timeout=20)
    assert not app.exception
    previews='\n'.join(m.value for m in app.markdown)
    assert 'Morgan Example (Synthetic)' in previews
    assert 'Different Synthetic Editor Name' not in previews


def test_anthropic_transient_retries_are_bounded(monkeypatch):
    import anthropic,httpx
    from career_pipeline import providers
    real=anthropic.Anthropic
    attempts=[]
    def handler(request):
        attempts.append(1)
        return httpx.Response(429,json={'type':'error','error':{'type':'rate_limit_error','message':'synthetic'}})
    monkeypatch.setenv('ANTHROPIC_API_KEY','synthetic-not-a-real-key')
    monkeypatch.setattr(anthropic,'Anthropic',lambda **kwargs:real(**kwargs,
        http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    monkeypatch.setattr(providers.time,'sleep',lambda _:None)
    with pytest.raises(anthropic.RateLimitError):
        AnthropicProvider().complete('review',{'role':'evidence'},'synthetic-reviewer')
    assert len(attempts)==3


def assessment(claim,quote,evidence_id='e0'):
    return {'claim_id':claim.id,'evidence_ids':[evidence_id],
       'quotes':[{'evidence_id':evidence_id,'text':quote}],
       'wording_supported':True,'metrics_consistent':True,'technology_consistent':True,
       'scope_consistent':True,'dates_titles_consistent':True}


@pytest.mark.parametrize('provider',['anthropic','openai'])
def test_live_assessed_paraphrase_uses_quotes_and_independent_guards(career,store,monkeypatch,provider):
    from career_pipeline.providers import AnthropicProvider, OpenAIProvider
    text='Implemented Python ingestion.'
    seed=Packet(resume=[Claim(id='r1',text=text,evidence_ids=['e0'])],
                cover_letter=[Claim(id='c1',text=text,evidence_ids=['e0'])])
    def fake_live(self,task,payload,model,max_tokens=6000):
        packet=Packet.model_validate(payload['packet'])
        result={'findings':[],'reviewed_claim_ids':[c.id for c in packet.resume+packet.cover_letter],
                'assessments':[assessment(c,career.evidence[0].supported_wording[0]) for c in packet.resume+packet.cover_letter]
                    if payload['role']=='evidence' else []}
        return {'result':result,'input_tokens':100,'output_tokens':100}
    monkeypatch.setattr(AnthropicProvider if provider=='anthropic' else OpenAIProvider,'complete',fake_live)
    m=run(JD,career,store,Settings(reviewer=provider,factual_mode='model_reviewed',max_revisions=0),seed_packet=seed)
    assert not m['validation']
    assert len(m['versions'][0]['support_assessments'])==2
    assert m['status']=='draft'  # Presentation objections remain, but semantic support isn't faked as exact equality.
    approve(store,m['id'],career,True)
    assert store.get(m['id'])['approved']
    with pytest.raises(ValidationError,match='live reviewer'):
        Settings(reviewer='mock',factual_mode='model_reviewed')

@pytest.mark.parametrize('text',[
    'Saved 200 hours per month.',
    'Saved 20 hours per month.',
    'Saved an estimated $20 per month.',
    'Reduced costs by an estimated 20%.',
    'Managed a team of 20 engineers.',
    'Used Terraform to save an estimated 20 hours per month.'
])
def test_positive_model_verdict_cannot_override_guardrails(text):
    from career_pipeline.grounding import accepted_assessments
    e=Evidence(id='e0',project='Synthetic estimate',actions=[],ownership='contributed',
      technologies=[],sources=[{'reference':'synthetic://facts','status':'user_confirmed'}],
      confirmed_statements=['Estimated savings of 20 hours per month.'],
      metrics=[{'value':20,'unit':'hours per month','qualifier':'estimated'}])
    career=Career(display_name='Synthetic',evidence=[e])
    claim=Claim(id='r1',text=text,evidence_ids=['e0'])
    accepted,rejected=accepted_assessments(Packet(resume=[claim],cover_letter=[]),career,
        [assessment(claim,e.supported_wording[0])])
    assert not accepted and 'r1' in rejected


def test_fabricated_quote_and_training_upgrade_rejected(career):
    from career_pipeline.grounding import accepted_assessments
    claim=Claim(id='r1',text='Operated Azure Data Factory in production.',evidence_ids=['training'])
    packet=Packet(resume=[claim],cover_letter=[])
    accepted,rejected=accepted_assessments(packet,career,[assessment(claim,'Completed Azure Data Factory training.','training')])
    assert not accepted and rejected
    accepted,rejected=accepted_assessments(packet,career,[assessment(claim,'Built production Azure Data Factory pipelines.','training')])
    assert not accepted and 'supporting quote is not present in the source' in rejected['r1']


def test_metric_numbers_cannot_be_swapped_between_units():
    from career_pipeline.grounding import accepted_assessments
    records=[]
    for ident,value,unit,text in [('e0',30,'Snowflake credits/day','Estimated reduction of 30 credits per day.'),
                                  ('e1',10000,'USD/month','Canceled a vendor contract costing $10,000 per month.')]:
        records.append(Evidence(id=ident,project='Synthetic metric',actions=[],ownership='contributed',
          technologies=[],sources=[{'reference':'synthetic://facts','status':'user_confirmed'}],
          confirmed_statements=[text],metrics=[{'value':value,'unit':unit,'qualifier':'estimated' if ident=='e0' else 'realized'}]))
    career=Career(display_name='Synthetic',evidence=records)
    claim=Claim(id='r1',text='Saved an estimated $30 per month.',evidence_ids=['e0','e1'])
    raw=assessment(claim,records[0].supported_wording[0]);raw['evidence_ids']=['e0','e1']
    raw['quotes'].append({'evidence_id':'e1','text':records[1].supported_wording[0]})
    accepted,rejected=accepted_assessments(Packet(resume=[claim],cover_letter=[]),career,[raw])
    assert not accepted and any('pairing' in reason for reason in rejected['r1'])

@pytest.mark.parametrize('statement,claim_text,context',[
    ('Contributed to a pipeline.','Owned the entire platform.','professional'),
    ('Used npm packages.','Published npm packages.','professional'),
    ('Doctor of Information Technology | in progress, dissertation phase','Doctor of Information Technology','academic'),
])
def test_scope_and_credential_upgrades_rejected(statement,claim_text,context):
    from career_pipeline.grounding import accepted_assessments
    e=Evidence(id='e0',project='Synthetic scope',actions=[],ownership='contributed',technologies=[],
       sources=[{'reference':'synthetic://facts','status':'user_confirmed'}],confirmed_statements=[statement])
    career=Career(display_name='Synthetic',evidence=[e])
    claim=Claim(id='r1',text=claim_text,evidence_ids=['e0'])
    accepted,rejected=accepted_assessments(Packet(resume=[claim],cover_letter=[]),career,[assessment(claim,statement)])
    assert not accepted and rejected

@pytest.mark.parametrize('persistent',[False,True])
def test_live_review_contract_correction_is_bounded_and_saved(monkeypatch,career,store,persistent):
    from career_pipeline.providers import OpenAIProvider
    calls=[]
    def complete(self,task,payload,model,max_tokens=6000):
        result=MockProvider().complete(task,payload,model)
        if task=='review' and payload['role']=='evidence':
            calls.append(payload)
            if persistent or len(calls)==1:
                result['reviewed_claim_ids']=result['reviewed_claim_ids'][:-1]
        return {'result':result,'input_tokens':100,'output_tokens':50}
    monkeypatch.setattr(OpenAIProvider,'complete',complete)
    settings=Settings(generator='openai',reviewer='openai',max_revisions=0)
    if persistent:
        with pytest.raises(ValueError,match='every claim'):run(JD,career,store,settings)
        m=store.history()[0]
        assert m['status']=='failed'
        with pytest.raises(ValueError):approve(store,m['id'],career,True)
    else:
        m=run(JD,career,store,settings)
        assert m['versions'][0]['reviews']['evidence']['status']=='passed'
    assert len(calls)==(2 if persistent else 4)
    assert 'contract_correction' in calls[1]
    attempts=m['versions'][0]['reviews']['evidence']['attempts']
    assert attempts[0]['status']=='rejected'
    assert attempts[0]['response']['reviewed_claim_ids']
    assert attempts[1]['status']==('rejected' if persistent else 'accepted')
    assert len([t for t in m['telemetry'] if t.get('role')=='evidence'])==len(calls)


def test_live_negative_verdict_is_not_retried_or_waived(monkeypatch,career,store):
    from career_pipeline.providers import OpenAIProvider
    def complete(self,task,payload,model,max_tokens=6000):
        result=MockProvider().complete(task,payload,model)
        if task=='review' and payload['role']=='evidence':
            result['findings'].append({'role':'evidence','claim_id':(payload['packet']['resume']+payload['packet']['cover_letter'])[0]['id'],
                'severity':'error','code':'unsupported_scope','message':'Scope is unsupported.'})
        return {'result':result,'input_tokens':100,'output_tokens':50}
    monkeypatch.setattr(OpenAIProvider,'complete',complete)
    m=run(JD,career,store,Settings(generator='openai',reviewer='openai',max_revisions=0))
    assert m['status']=='needs_review'
    assert all(a['status']=='accepted' for a in m['versions'][0]['reviews']['evidence']['attempts'])
    assert len(m['versions'][0]['reviews']['evidence']['attempts']) == len(m['versions'][0]['reviews']['evidence']['batches'])
    with pytest.raises(ValueError):approve(store,m['id'],career,True)


def test_intake_scopes_each_education_record_to_its_own_degree(tmp_path):
    from career_pipeline.intake import import_intake
    root=tmp_path/'intake';root.mkdir()
    degrees=[{'degree':'MS Data Analytics','institution':'Example University','completed_month':'2023-06'},
             {'degree':'BS Nursing','institution':'Example College','completed_month':'2015-06'},
             {'degree':'Doctor Information Technology','institution':'Example Institute','status':'in progress; dissertation phase'}]
    draft={'display_name':'Synthetic Candidate','records':[
        {'id':'education','topic':'MS Data Analytics','record_type':'education'}]}
    ledger={'confirmations':[{'id':'degrees-confirmed','status':'user_confirmed_for_listed_facts_only',
        'record_ids':['education'],'confirmed_facts':{'degrees':degrees}}]}
    (root/'career.evidence-draft.json').write_text(json.dumps(draft))
    (root/'user-confirmations.json').write_text(json.dumps(ledger))
    result=import_intake(root,tmp_path/'career.json')
    assert len(result.evidence)==3
    for evidence,degree in zip(result.evidence,degrees):
        assert evidence.project==degree['degree']
        assert evidence.actions==evidence.confirmed_statements
        assert evidence.confirmed_statements[0].startswith(evidence.project+' | ')
        assert evidence.fact_details['degrees']==[degree]
        assert evidence.eligible
    assert 'in progress; dissertation phase' in result.evidence[-1].confirmed_statements[0]
    assert len({e.id for e in result.evidence})==3


def test_failed_run_persists_safe_stage_diagnostic(monkeypatch,career,store):
    def broken(*args,**kwargs):
        raise ValueError('OpenAI response incomplete; no candidate or review accepted')
    monkeypatch.setattr(MockProvider,'complete',broken)
    with pytest.raises(ValueError):run(JD,career,store)
    failure=store.history()[0]['failure']
    assert failure['stage']=='generate'
    assert failure['code']=='response_incomplete'
    assert 'per-call output limit' in failure['message']


def test_presentation_revision_cannot_replace_passing_packet_with_unsupported_claim(monkeypatch, career, store):
    original = MockProvider.complete
    def provider(self, task, payload, model):
        result = original(self, task, payload, model)
        if task == 'review' and payload['role'] == 'voice':
            result['findings'].append({'role': 'voice', 'claim_id': payload['packet']['resume'][0]['id'],
                'severity': 'suggestion', 'code': 'style', 'message': 'Improve clarity without adding facts.'})
        if task == 'revise':
            result['resume'][0]['text'] = 'Managed 500 engineers and saved $900 million.'
        return result
    monkeypatch.setattr(MockProvider, 'complete', provider)
    m = run(JD, career, store)
    assert m['stopping_reason'] == 'factual_regression_rollback'
    assert m['revision_count'] == 1 and len(m['versions']) == 3
    assert m['versions'][-1]['restored_from_version'] == 0
    assert m['versions'][-1]['packet'] == m['versions'][0]['packet']
    assert any(f['severity'] == 'error' for f in m['versions'][1]['findings'])
    assert not m['validation'] and not m['approved']


@pytest.mark.parametrize('jd', [
    'Required: Kubernetes production administration.',
    'About the job\nWelcome to our wonderful company.',
    'Experience building Python data ingestion.\nKnowledge of documentation.',
])
def test_retrieval_never_erases_confirmed_employment_history(career, store, jd):
    extra = career.evidence[0].model_copy(deep=True)
    extra.id = 'second-role-evidence'
    extra.employment_ids = ['job-2']
    extra.confirmed_statements = ['Documented reporting definitions.']
    career.employments.append(Employment(id='job-2', employer='Second Synthetic Co',
        official_title='Analyst', start='2021-01', end='2023-09'))
    career.evidence.append(extra)
    m = run(jd, career, store, Settings(include_cover_letter=False))
    packet = Packet.model_validate(m['versions'][-1]['packet'])
    text, letter = preview(packet, career)
    assert 'Synthetic Warehouse Co' in text and 'Second Synthetic Co' in text
    assert 'Professional Experience' in text and 'Python' in text
    assert 'Education' in text and 'Publications' in text
    assert not letter and not m['validation']
    assert 'second-role-evidence' in m['selected_evidence']


def test_education_and_publications_only_cannot_pass_as_complete_resume(career, store, tmp_path):
    packet = Packet(resume=[Claim(id=e.id, text=e.supported_wording[0], evidence_ids=[e.id])
                           for e in career.evidence if e.kind in ('education', 'publication')],
                    cover_letter=[])
    m = run('Required: Kubernetes administration.', career, store,
            Settings(include_cover_letter=False, max_revisions=0), seed_packet=packet)
    assert m['status'] == 'draft'
    assert m['baseline_restored_claims']
    assert any(c['id'].startswith('baseline-') for c in m['versions'][-1]['packet']['resume'])
    assert not m['validation']
    approve(store, m['id'], career, True)
    assert export(store, m['id'], career, tmp_path/'final')


def test_uncertain_employment_is_not_forced_into_resume(career, store):
    uncertain = career.evidence[0].model_copy(deep=True)
    uncertain.id = 'uncertain-role'
    uncertain.employment_ids = []
    uncertain.employer = 'Unverified Synthetic Co'
    uncertain.sources[0].status = 'uncertain'
    career.evidence.append(uncertain)
    m = run('Required: Kubernetes administration.', career, store)
    assert 'uncertain-role' not in m['selected_evidence']
    assert not any('uncertain-role' in f.get('evidence_ids', [])
                   for f in m['validation'] if f['code'] == 'missing_employment_history')

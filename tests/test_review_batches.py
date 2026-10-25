"""Long reviews and truncated responses use synthetic sources and no network."""
import pytest
from career_pipeline.models import Career, Evidence, Employment, Packet, Claim, Settings
from career_pipeline.pipeline import run
from career_pipeline.providers import OpenAIProvider, IncompleteResponse
from career_pipeline.export import approve
from career_pipeline.store import Store


def source_packet():
    job = Employment(id='job', employer='Synthetic Co', official_title='Engineer', start='2020-01')
    records = [Evidence(id=f'e{i}', employment_ids=['job'], project='Ingestion', actions=[], ownership='contributed', technologies=[],
        confirmed_statements=[f'Built pipeline number {i} using Python.'],
        sources=[{'reference': 'synthetic', 'status': 'user_provided'}]) for i in range(12)]
    career = Career(display_name='Synthetic Example', employments=[job], evidence=records)
    packet = Packet(resume=[Claim(id=f'r{i}', text=e.supported_wording[0], evidence_ids=[e.id])
                            for i, e in enumerate(records)],
                    cover_letter=[Claim(id=f'c{i}', text=e.supported_wording[0], evidence_ids=[e.id])
                                  for i, e in enumerate(records[:3])])
    return career, packet


@pytest.mark.parametrize('truncate', [False, True])
def test_full_review_batches_cover_every_claim_and_save_progress(monkeypatch, tmp_path, truncate):
    career, packet = source_packet()
    calls = []
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        claims = payload['packet']['resume'] + payload['packet']['cover_letter']
        calls.append((payload['role'], len(claims)))
        if payload['role'] == 'evidence':
            assert len(claims) <= 4
            assert payload['style'] == ''  # Writing preferences must not override factual policy.
            assert {e['id'] for e in payload['career']['evidence']} == {i for c in claims for i in c['evidence_ids']}
            if truncate and len(claims) > 2:
                raise IncompleteResponse('OpenAI response incomplete; no candidate or review accepted')
        else:
            assert len(claims) == 15  # Other editors still see the complete document.
        return {'result': {'findings': [], 'reviewed_claim_ids': [c['id'] for c in claims], 'assessments': []},
                'input_tokens': 100, 'output_tokens': 100}
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)
    with Store(str(tmp_path/'runs.sqlite')) as store:
        m = run('Required: Python pipeline development.', career, store,
                Settings(reviewer='openai', max_revisions=0, max_calls=20), seed_packet=packet)
        review = m['versions'][0]['reviews']['evidence']
        assert review['status'] == 'passed'
        assert set(review['reviewed_claim_ids']) == {c.id for c in packet.resume + packet.cover_letter}
        assert len(review['reviewed_claim_ids']) == 15
        assert any(b['status'] == 'incomplete' for b in review['batches']) == truncate
        assert all(len(b['claim_ids']) <= (2 if truncate else 4) for b in review['batches'] if b['status'] == 'passed')
        assert store.get(m['id'])['versions'][0]['reviews']['evidence'] == review
        assert not m['validation']


def test_single_claim_truncation_stops_and_blocks_approval(monkeypatch, tmp_path):
    career, packet = source_packet()
    calls = []
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        calls.append(len(payload['packet']['resume']))
        raise IncompleteResponse('OpenAI response incomplete; no candidate or review accepted')
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)
    with Store(str(tmp_path/'runs.sqlite')) as store:
        with pytest.raises(IncompleteResponse):
            run('Required: Python pipeline development.', career, store,
                Settings(reviewer='openai', max_revisions=0), seed_packet=packet)
        assert calls == [4, 2, 1]
        m = store.history()[0]
        assert m['status'] == 'failed'
        assert m['versions'][0]['reviews']['evidence']['status'] == 'failed'
        with pytest.raises(ValueError):
            approve(store, m['id'], career, True)


def test_batches_respect_call_budget(monkeypatch, tmp_path):
    career, packet = source_packet()
    calls = []
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        calls.append(task)
        claims = payload['packet']['resume'] + payload['packet']['cover_letter']
        return {'result': {'findings': [], 'reviewed_claim_ids': [c['id'] for c in claims], 'assessments': []},
                'input_tokens': 100, 'output_tokens': 100}
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)
    with Store(str(tmp_path/'runs.sqlite')) as store:
        with pytest.raises(ValueError, match='budget exhausted'):
            run('Required: Python pipeline development.', career, store,
                Settings(reviewer='openai', max_revisions=0, max_calls=1), seed_packet=packet)
        assert calls == ['review']
        m = store.history()[0]
        assert len(m['versions'][0]['reviews']['evidence']['attempts']) == 1
        with pytest.raises(ValueError):
            approve(store, m['id'], career, True)


def test_positive_assessment_with_invented_quote_requires_contract_correction():
    from career_pipeline.pipeline import validate_review_contract
    career, packet = source_packet()
    claim = packet.resume[0]
    packet = Packet(resume=[claim], cover_letter=[])
    assessment = {'claim_id':claim.id, 'evidence_ids':claim.evidence_ids,
        'quotes':[{'evidence_id':claim.evidence_ids[0], 'text':'Invented source quotation.'}],
        'wording_supported':True, 'metrics_consistent':True, 'technology_consistent':True,
        'scope_consistent':True, 'dates_titles_consistent':True}
    raw = {'findings':[], 'reviewed_claim_ids':[claim.id], 'assessments':[assessment]}
    with pytest.raises(ValueError, match='supporting quotes'):
        validate_review_contract(raw,'evidence',packet,[],career,'model_reviewed')
    assessment['quotes'][0]['text'] = career.evidence[0].supported_wording[0]
    assert validate_review_contract(raw,'evidence',packet,[],career,'model_reviewed')[1] == {claim.id}


def test_known_factual_errors_are_revised_before_paid_reviews(monkeypatch, tmp_path):
    from career_pipeline.providers import MockProvider
    career, packet = source_packet()
    packet.resume[0].text = 'Managed 50 engineers and administered Kubernetes clusters.'
    calls = []
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        assert all('Managed 50' not in c['text'] for c in payload['packet']['resume'])
        calls.append(task)
        result = MockProvider().complete(task, payload, model)
        return {'result': result, 'input_tokens': 10, 'output_tokens': 10}
    monkeypatch.setattr(OpenAIProvider,'complete',complete)
    with Store(str(tmp_path/'runs.sqlite')) as store:
        m = run('Required: Python pipeline development.', career, store,
                Settings(reviewer='openai', factual_mode='model_reviewed', max_revisions=1), seed_packet=packet)
        assert m['versions'][0]['reviews']['evidence']['reason'] == 'deterministic_factual_errors'
        assert m['telemetry'][0]['stage'] == 'revise'
        assert calls and all(c == 'review' for c in calls)
        assert not m['validation']


def test_partial_revision_restores_a_passed_claim_if_new_wording_invents_facts(monkeypatch, tmp_path):
    career, original = source_packet()
    packet = Packet(resume=original.resume[:2], cover_letter=[])
    packet.resume[1].text = 'Production pipeline number 1 using Python.'
    index = {e.id:e for e in career.evidence}
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        if task == 'revise':
            candidate = Packet.model_validate(payload['packet'])
            candidate.resume[0].text = 'Managed 50 engineers.'
            candidate.resume[1].text = index['e1'].supported_wording[0]
            result = candidate.model_dump()
        else:
            claims = payload['packet']['resume'] + payload['packet']['cover_letter']
            assessments = []
            if payload['role'] == 'evidence':
                for c in claims:
                    assessments.append({'claim_id':c['id'], 'evidence_ids':c['evidence_ids'],
                        'quotes':[{'evidence_id':i,'text':index[i].supported_wording[0]} for i in c['evidence_ids']],
                        'wording_supported':not c['text'].startswith('Production'), 'metrics_consistent':True,
                        'technology_consistent':True, 'scope_consistent':True, 'dates_titles_consistent':True})
            result = {'findings':[], 'reviewed_claim_ids':[c['id'] for c in claims], 'assessments':assessments}
        return {'result':result,'input_tokens':10,'output_tokens':10}
    monkeypatch.setattr(OpenAIProvider,'complete',complete)
    with Store(str(tmp_path/'runs.sqlite')) as store:
        m = run('Required: Python pipeline development.',career,store,
            Settings(generator='openai',reviewer='openai',factual_mode='model_reviewed',max_revisions=1,include_cover_letter=False),seed_packet=packet)
        assert m['revision_restored_claims'][0]['claim_id'] == 'r0'
        assert m['versions'][-1]['packet']['resume'][0]['text'] == index['e0'].supported_wording[0]
        assert not m['validation']


def test_verbatim_user_inputs_use_exact_comparison_not_model_reverification(monkeypatch, tmp_path):
    career, packet = source_packet()
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        assert payload['role'] != 'evidence'
        claims = payload['packet']['resume'] + payload['packet']['cover_letter']
        return {'result':{'findings':[], 'reviewed_claim_ids':[c['id'] for c in claims], 'assessments':[]},
                'input_tokens':10,'output_tokens':10}
    monkeypatch.setattr(OpenAIProvider,'complete',complete)
    with Store(str(tmp_path/'runs.sqlite')) as store:
        m = run('Required: Python pipeline development.',career,store,
            Settings(reviewer='openai',factual_mode='model_reviewed',max_revisions=0),seed_packet=packet)
        receipt = m['versions'][0]['reviews']['evidence']
        assert len(receipt['deterministic_claim_ids']) == 15
        assert receipt['model_reviewed_claim_ids'] == []
        assert receipt['status'] == 'passed'
        assert not m['validation']


def test_budget_stop_restores_a_fully_reviewed_packet(monkeypatch, tmp_path):
    from career_pipeline.providers import Gateway
    career, original = source_packet()
    packet = Packet(resume=original.resume[:1],cover_letter=original.cover_letter[:1])
    original_call = Gateway.call
    def call(self, task, payload):
        if task == 'revise':
            raise ValueError('provider call/token budget exhausted before request')
        return original_call(self,task,payload)
    def complete(self,task,payload,model,max_tokens):
        self.requests_made = 1
        claims=payload['packet']['resume']+payload['packet']['cover_letter']
        return {'result':{'findings':[], 'reviewed_claim_ids':[c['id'] for c in claims], 'assessments':[]},
                'input_tokens':10,'output_tokens':10}
    monkeypatch.setattr(Gateway,'call',call)
    monkeypatch.setattr(OpenAIProvider,'complete',complete)
    with Store(str(tmp_path/'runs.sqlite')) as store:
        m=run('Required: Python pipeline development.',career,store,
            Settings(reviewer='openai',factual_mode='model_reviewed',max_revisions=2),seed_packet=packet)
        assert m['status']=='draft' and not m['validation']
        assert m['stopping_reason']=='budget_limit_restored_reviewed_version'
        assert m['versions'][-1]['restored_from_version']==0
        assert not m['approved']
        assert approve(store,m['id'],career,True)['approved']

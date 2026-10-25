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

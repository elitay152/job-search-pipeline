"""Citation repair, verb forms, capped reviewer advice and the letter focus; synthetic data only."""
from pathlib import Path
from career_pipeline.models import Career, Claim, Employment, Evidence, Packet, Settings
from career_pipeline.grounding import deterministic_objections, repair_citations
from career_pipeline.pipeline import run, validate_review_contract
from career_pipeline.providers import MockProvider
from career_pipeline.store import Store

JD = Path('fixtures/job.txt').read_text()
ORIGINAL = MockProvider.complete  # Unpatched, so repeated patches never stack.


def record(ident, text, project='Pipelines', jobs=('acme',)):
    return Evidence(id=ident, project=project, employment_ids=list(jobs), confirmed_statements=[text], actions=[],
                    ownership='contributed', technologies=[], sources=[{'reference': ident, 'status': 'user_provided'}])


def library():
    jobs = [Employment(id='acme', employer='Acme Health', official_title='Engineer', start='2022-01'),
            Employment(id='beta', employer='Beta Labs', official_title='Analyst', start='2019-01', end='2021-12')]
    return Career(display_name='Synthetic', employments=jobs, evidence=[
        record('a1', 'Built Python ingestion pipelines with duplicate checks.'),
        record('a2', 'Wrote PySpark notebooks for the ingestion pipelines.'),
        record('a3', 'Used PySpark for one-off reporting.', project='Reporting'),
        record('b1', 'Lead weekly production deployments.', project='Releases', jobs=('beta',))])


def test_any_form_of_a_verb_in_the_source_supports_the_past_tense():
    career = library()
    b1 = next(e for e in career.evidence if e.id == 'b1')
    assert not deterministic_objections('Led weekly production deployments.', [b1])
    objection = deterministic_objections('Led the reporting redesign.', [career.evidence[0]])[0]
    assert objection.startswith('unestablished ownership verb: led') and 'use the source' in objection


def test_citation_repair_stays_within_the_same_work():
    career = library()
    packet = Packet(
        resume=[Claim(id='r1', text='Built Python ingestion pipelines in PySpark.', evidence_ids=['a1', 'context-0123456789abcdef']),
                Claim(id='r2', text='Built Python ingestion pipelines and led the redesign.', evidence_ids=['a1'])],
        cover_letter=[Claim(id='c1', text='I build pipelines in Python and PySpark.', evidence_ids=['a1']),
                      Claim(id='c2', text='At Beta Labs I used PySpark.', evidence_ids=['b1'])])
    fixed, repairs = repair_citations(packet, career)
    claims = {c.id: c for c in fixed.resume + fixed.cover_letter}
    assert claims['r1'].evidence_ids == ['a1', 'a2']  # Same project and job; unknown ID dropped.
    assert claims['r2'].evidence_ids == ['a1']  # A verb is never repaired by citing other work.
    assert claims['c1'].evidence_ids == ['a1', 'a2']  # Letter summaries may use any record.
    assert claims['c2'].evidence_ids == ['b1']  # Never move a skill to another named employer.
    assert {'claim_id': 'r1', 'removed_unknown': ['context-0123456789abcdef']} in repairs
    strict, _ = repair_citations(packet, career, augment=False)
    assert [c.evidence_ids for c in strict.resume] == [['a1'], ['a1']]


def test_presentation_reviewers_are_capped():
    career = library()
    packet = Packet(resume=[Claim(id='r1', text='Built Python ingestion pipelines with duplicate checks.', evidence_ids=['a1'])],
                    cover_letter=[])
    raw = {'findings': [{'role': 'voice', 'claim_id': 'r1', 'severity': 'suggestion', 'code': 'rewrite',
                         'message': f'Tighten wording {i}.'} for i in range(20)], 'reviewed_claim_ids': ['r1']}
    parsed, _ = validate_review_contract(raw, 'voice', packet, [], career, 'strict')
    assert len(parsed) == 6


def count_revisions(monkeypatch, code):
    original = ORIGINAL
    calls = []
    def provider(self, task, payload, model):
        if task == 'revise':
            calls.append(task)
        result = original(self, task, payload, model)
        if task == 'review' and payload['role'] == 'voice':
            result['findings'].append({'role': 'voice', 'claim_id': payload['packet']['resume'][0]['id'],
                'severity': 'suggestion', 'code': code, 'message': 'Lead with the action.'})
        return result
    monkeypatch.setattr(MockProvider, 'complete', provider)
    return calls


def test_rewrite_suggestions_are_applied_but_questions_are_not(monkeypatch, tmp_path):
    career = Career.model_validate_json(Path('fixtures/career.json').read_text())
    calls = count_revisions(monkeypatch, 'rewrite')
    run(JD, career, Store(str(tmp_path / 'a.sqlite')), Settings(max_revisions=2))
    assert calls == ['revise']
    calls = count_revisions(monkeypatch, 'needs_info')
    m = run(JD, career, Store(str(tmp_path / 'b.sqlite')), Settings(max_revisions=2))
    assert calls == [] and m['stopping_reason'] == 'material_issues_resolved'


def test_rewrites_are_applied_in_one_pass_only(monkeypatch, tmp_path):
    career = Career.model_validate_json(Path('fixtures/career.json').read_text())
    original = ORIGINAL
    revisions = []
    def provider(self, task, payload, model):
        result = original(self, task, payload, model)
        if task == 'revise':
            revisions.append(task)
            result['cover_letter'] = result['cover_letter'][::-1] if len(revisions) % 2 else result['cover_letter']
        if task == 'review' and payload['role'] == 'voice':
            result['findings'].append({'role': 'voice', 'claim_id': payload['packet']['resume'][0]['id'],
                'severity': 'suggestion', 'code': 'rewrite', 'message': f'Tighten wording {len(revisions)}.'})
        return result
    monkeypatch.setattr(MockProvider, 'complete', provider)
    m = run(JD, career, Store(str(tmp_path / 'c.sqlite')), Settings(max_revisions=3))
    assert len(revisions) == 1 and m['stopping_reason'] == 'material_issues_resolved'


def test_letter_focus_uses_matched_work_not_degrees(tmp_path):
    career = Career.model_validate_json(Path('fixtures/career.json').read_text())
    jd = JD + "\nRequired: Bachelor's degree in computer science\nRequired: 3 years of Python experience"
    m = run(jd, career, Store(str(tmp_path / 'd.sqlite')))
    focus = [item['requirement'] for item in m['composition_plan']['letter_focus']]
    assert focus and not any('degree' in f.lower() or 'years' in f.lower() for f in focus)
    m = run(jd, career, Store(str(tmp_path / 'e.sqlite')), Settings(include_cover_letter=False))
    assert 'letter_focus' not in m['composition_plan']


def test_unquoted_positive_verdict_gets_one_correction_instead_of_failing(monkeypatch, tmp_path):
    from career_pipeline.providers import OpenAIProvider
    career = library()
    source = 'Built Python ingestion pipelines with duplicate checks.'
    packet = Packet(resume=[Claim(id='r1', text='Developed Python ingestion pipelines with duplicate checks.', evidence_ids=['a1'])],
                    cover_letter=[])
    evidence_calls = []
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        if task == 'match':
            return {'result': {'matches': []}, 'input_tokens': 1, 'output_tokens': 1}
        claims = payload['packet']['resume'] + payload['packet']['cover_letter']
        result = {'findings': [], 'reviewed_claim_ids': [c['id'] for c in claims], 'assessments': []}
        if payload['role'] == 'evidence':
            evidence_calls.append(bool(payload.get('contract_correction')))
            # After a stray quote is dropped, the first verdict is positive but has no quote.
            quotes = [{'evidence_id': 'a1', 'text': source}] if payload.get('contract_correction') else []
            result['assessments'] = [dict(claim_id=c['id'], evidence_ids=c['evidence_ids'], quotes=quotes,
                wording_supported=True, metrics_consistent=True, technology_consistent=True,
                scope_consistent=True, dates_titles_consistent=True) for c in claims if c['id'] == 'r1']
        return {'result': result, 'input_tokens': 1, 'output_tokens': 1}
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)
    m = run(JD, career, Store(str(tmp_path / 'f.sqlite')),
            Settings(generator='openai', reviewer='openai', factual_mode='model_reviewed', max_revisions=0), seed_packet=packet)
    assert evidence_calls == [False, True]
    assert m['status'] != 'failed'
    assert [a['status'] for a in m['versions'][0]['reviews']['evidence']['attempts']] == ['rejected', 'accepted']


def test_error_contradicting_a_supported_verdict_is_dropped(monkeypatch, tmp_path):
    from career_pipeline.providers import OpenAIProvider
    career = library()
    source = 'Built Python ingestion pipelines with duplicate checks.'
    packet = Packet(resume=[Claim(id='r1', text='Developed Python ingestion pipelines with duplicate checks.', evidence_ids=['a1'])],
                    cover_letter=[])
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        if task == 'match':
            return {'result': {'matches': []}, 'input_tokens': 1, 'output_tokens': 1}
        claims = payload['packet']['resume'] + payload['packet']['cover_letter']
        result = {'findings': [], 'reviewed_claim_ids': [c['id'] for c in claims], 'assessments': []}
        if payload['role'] == 'evidence' and any(c['id'] == 'r1' for c in claims):
            result['findings'] = [{'role': 'evidence', 'claim_id': 'r1', 'evidence_ids': ['a1'], 'severity': 'error',
                                   'code': 'EVIDENCE_MATCH', 'message': 'Assessment performed; evidence supports the claim.'}]
            result['assessments'] = [dict(claim_id='r1', evidence_ids=['a1'], quotes=[{'evidence_id': 'a1', 'text': source}],
                wording_supported=True, metrics_consistent=True, technology_consistent=True,
                scope_consistent=True, dates_titles_consistent=True)]
        return {'result': result, 'input_tokens': 1, 'output_tokens': 1}
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)
    m = run(JD, career, Store(str(tmp_path / 'g.sqlite')),
            Settings(generator='openai', reviewer='openai', factual_mode='model_reviewed', max_revisions=0), seed_packet=packet)
    assert not any(f['code'] == 'EVIDENCE_MATCH' for f in m['versions'][0]['findings'])
    assert not any(f['claim_id'] == 'r1' and f['severity'] == 'error' for f in m['versions'][0]['findings'])

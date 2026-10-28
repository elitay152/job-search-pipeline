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

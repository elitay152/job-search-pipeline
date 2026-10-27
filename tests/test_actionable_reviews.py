"""Requirement matching, coverage percentages and actionable review notes; synthetic data, no network."""
from pathlib import Path
import pytest
from career_pipeline.models import Career, Claim, Packet, Requirement, Settings
from career_pipeline.pipeline import extract, apply_matches, run
from career_pipeline.providers import OpenAIProvider
from career_pipeline.export import preview
from career_pipeline.review import audit, reviews
from career_pipeline.grounding import deterministic_objections
from career_pipeline.store import Store
from career_pipeline.workbench import fit_report


@pytest.fixture
def career():
    return Career.model_validate_json(Path('fixtures/career.json').read_text())


def test_reference_codes_are_errors_and_never_rendered(career):
    letter = Claim(id='c1', text='I built Python ingestion with checks (fact-c93c86543e7374f3, ev-pipeline).',
                   evidence_ids=['ev-pipeline'])
    packet = Packet(resume=[Claim(id='r1', text=career.evidence[0].supported_wording[0], evidence_ids=['ev-pipeline'])],
                    cover_letter=[letter])
    finding = next(f for f in audit(packet, career) if f.code == 'reference_in_text')
    assert finding.claim_id == 'c1' and 'fact-c93c86543e7374f3' in finding.message and 'ev-pipeline' in finding.message
    _, rendered = preview(packet, career)
    assert 'fact-' not in rendered and 'ev-pipeline' not in rendered and '()' not in rendered
    assert 'I built Python ingestion with checks.' in rendered


def test_fact_check_names_the_new_number_and_role_heading_prefix(career):
    e = next(e for e in career.evidence if e.id == 'ev-pipeline')
    e.employer = 'Synthetic Analytics Co'
    objections = deterministic_objections(f'Synthetic Analytics Co — Data Engineer (Jan 2022–Jun 2024): {e.supported_wording[0]}', [e])
    assert any(o.startswith('starts with the employer/title/dates') for o in objections)
    dates = next(o for o in objections if o.startswith('new or altered number'))
    assert '2022' in dates and '2024' in dates and 'look like dates' in dates


def test_extract_skips_headings_hashtags_and_apply_lines():
    jd = '\n'.join([
        'Responsibilities', '2. Data Engineering and Automated Quality Control',
        '- Develop data-ingestion and validation workflows for clinical data',
        'Required Qualifications:Education and Experience',
        '- Proficiency in Python for automation and testing',
        'Required Technical Skills', '- Working knowledge of Linux development environments',
        'Preferred Qualifications:', '- Experience with Microsoft Copilot Studio',
        '📩 Interested in this opportunity? Apply through LinkedIn or get in touch to learn more.',
        '#Hiring #Python #DataEngineering #LifeSciences',
        'Requirements added by the job poster', '• 1+ years of work experience with R (Programming Language)',
        'Employment Type: W2 Contract. ' + 'The engineer will work closely with data scientists and product owners. ' * 8])
    found = {q.text: q.priority for q in extract(jd)}
    assert found == {'Develop data-ingestion and validation workflows for clinical data': 'ambiguous',
                     'Proficiency in Python for automation and testing': 'required',
                     'Working knowledge of Linux development environments': 'required',
                     'Experience with Microsoft Copilot Studio': 'preferred',
                     '1+ years of work experience with R (Programming Language)': 'required'}


def test_model_matches_replace_word_overlap_and_drop_non_requirements(career):
    requirements = [Requirement(id='q1', text='Python ingestion', excerpt='Python ingestion', priority='required',
                                classification='transferable', evidence_ids=['ev-orchestration']),
                    Requirement(id='q2', text='Microsoft Copilot Studio', excerpt='x', priority='preferred',
                                classification='transferable', evidence_ids=['ev-pipeline']),
                    Requirement(id='q3', text='Required Technical Skills', excerpt='x', priority='required'),
                    Requirement(id='q4', text='Location: hybrid', excerpt='x', priority='ambiguous', kind='constraint')]
    result = {'matches': [
        {'requirement_id': 'q1', 'classification': 'direct', 'evidence_ids': ['ev-pipeline', 'unknown-id'],
         'rationale': 'Built Python ingestion with duplicate checks (ev-pipeline).'},
        {'requirement_id': 'q2', 'classification': 'unsupported', 'evidence_ids': ['ev-pipeline'],
         'rationale': 'No Copilot Studio evidence; closest is Python automation.'},
        {'requirement_id': 'q3', 'classification': 'not_a_requirement', 'evidence_ids': [], 'rationale': 'Heading.'}]}
    kept, dropped = apply_matches(requirements, result, career)
    assert dropped == ['q3'] and [q.id for q in kept] == ['q1', 'q2', 'q4']
    assert kept[0].classification == 'direct' and kept[0].evidence_ids == ['ev-pipeline']
    assert 'ev-pipeline' not in kept[0].rationale
    assert kept[1].classification == 'unsupported' and kept[1].evidence_ids == []
    gap = next(f for f in reviews(Packet(resume=[], cover_letter=[]), kept, career) if f.code == 'experience_gap')
    assert 'Microsoft Copilot Studio' in gap.message and 'closest is Python automation' in gap.message


def test_coverage_percentages_count_only_cited_requirements():
    reqs = [Requirement(id=f'q{i}', text='x', excerpt='x', priority='required' if i < 2 else 'preferred',
                        classification='direct' if i < 3 else 'unsupported', evidence_ids=[f'e{i}'] if i < 3 else [])
            for i in range(4)]
    packet = Packet(resume=[Claim(id='r', text='t', evidence_ids=['e0'])], cover_letter=[])
    before, after = fit_report(reqs), fit_report(reqs, packet)
    assert before['coverage_percent'] == 75 and before['required_coverage_percent'] == 100
    assert after['coverage_percent'] == 25 and after['required_coverage_percent'] == 50


def live(monkeypatch, handler):
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        return {'result': handler(task, payload), 'input_tokens': 10, 'output_tokens': 10}
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)


def test_live_run_records_model_matching_or_falls_back(monkeypatch, tmp_path, career):
    def answer(fail):
        def handler(task, payload):
            if task == 'match':
                if fail:
                    raise ValueError('synthetic matching failure')
                return {'matches': [{'requirement_id': q['id'], 'classification': 'unsupported', 'evidence_ids': [],
                                     'rationale': 'No synthetic evidence.'} for q in payload['requirements']]}
            from career_pipeline.providers import MockProvider
            result = MockProvider().complete(task, payload, 'synthetic')
            if task == 'review':
                result['assessments'] = []
            return result
        return handler
    settings = Settings(generator='openai', reviewer='openai', max_revisions=0)
    live(monkeypatch, answer(fail=False))
    m = run(Path('fixtures/job.txt').read_text(), career, Store(str(tmp_path / 'a.sqlite')), settings)
    assert m['requirement_matching']['method'] == 'model'
    assert all(q['rationale'] == 'No synthetic evidence.' for q in m['requirements'] if q['kind'] == 'skill')
    live(monkeypatch, answer(fail=True))
    m = run(Path('fixtures/job.txt').read_text(), career, Store(str(tmp_path / 'b.sqlite')), settings)
    assert m['requirement_matching']['method'] == 'word_overlap' and m['requirement_matching']['model_failure']
    assert m['status'] != 'failed'


def test_final_version_gets_presentation_reviews_despite_fact_errors(monkeypatch, tmp_path, career):
    stuck = Packet(resume=[Claim(id='r1', text='Built Python ingestion for 999 sources.', evidence_ids=['ev-pipeline'])],
                   cover_letter=[Claim(id='c1', text='I built Python ingestion.', evidence_ids=['ev-pipeline'])])
    roles = []
    def handler(task, payload):
        if task == 'match':
            return {'matches': []}
        if task in ('generate', 'revise'):
            return stuck.model_dump()  # The rewriter never fixes the unsupported number.
        roles.append(payload['role'])
        claims = payload['packet']['resume'] + payload['packet']['cover_letter']
        return {'findings': [{'role': payload['role'], 'claim_id': 'r1', 'severity': 'suggestion', 'code': 'clarity',
                              'message': 'Name the data sources.'}],
                'reviewed_claim_ids': [c['id'] for c in claims], 'assessments': []}
    live(monkeypatch, handler)
    m = run(Path('fixtures/job.txt').read_text(), career, Store(str(tmp_path / 'c.sqlite')),
            Settings(generator='openai', reviewer='openai', factual_mode='model_reviewed', max_revisions=1), seed_packet=stuck)
    final = m['versions'][-1]
    assert roles == ['recruiter', 'voice']  # Only the final version, and never the fact auditor.
    assert final['reviews']['evidence']['status'] == 'skipped'
    assert final['reviews']['recruiter']['status'] == 'passed' and final['reviews']['voice']['status'] == 'passed'
    assert any('999' in f['message'] for f in final['findings'] if f['severity'] == 'error')
    assert any(f['message'] == 'Name the data sources.' for f in final['findings'])
    assert m['status'] == 'needs_review'

"""Resume-to-job match report; synthetic resume and posting, no network."""
from pathlib import Path
import pytest
from career_pipeline.match_report import build_report, check_report, report_markdown, score
from career_pipeline.models import Requirement
from career_pipeline.providers import OpenAIProvider
from career_pipeline.store import Store
from test_ui import workspace, field, open_app

RESUME = '''Morgan Example — Data Engineer, Synthetic Analytics Co (2021–2024)
- Built Python and SQL batch ingestion pipelines with data quality checks in Snowflake.
- Scheduled Airflow orchestration for daily jobs.'''
JD = Path('fixtures/job.txt').read_text()


def requirement(ident, text, priority='required'):
    return Requirement(id=ident, text=text, excerpt=text, priority=priority)


def test_quotes_must_come_from_the_resume_and_scores_count_partial_as_half():
    reqs = [requirement('q1', 'Python ingestion'), requirement('q2', 'Kubernetes'),
            requirement('q3', 'Airflow', 'preferred'), requirement('q4', 'Spark')]
    raw = {'verdicts': [
        {'requirement_id': 'q1', 'match': 'strong', 'resume_quote': 'Built Python and SQL batch ingestion pipelines', 'note': 'Clear.'},
        {'requirement_id': 'q2', 'match': 'strong', 'resume_quote': 'Ran production Kubernetes clusters', 'note': 'Invented.'},
        {'requirement_id': 'q3', 'match': 'partial', 'resume_quote': '“Scheduled Airflow orchestration”', 'note': 'Some.'}],
        'recommendations': [{'kind': 'question', 'action': 'Have you used Spark?', 'reason': 'Spark', 'requirement_ids': ['q4', 'q99']}]}
    rows, recommendations = check_report(raw, reqs, RESUME)
    by_id = {r['id']: r for r in rows}
    assert by_id['q1']['match'] == 'strong'
    assert by_id['q2']['match'] == 'partial' and by_id['q2']['resume_quote'] == '' and 'not found' in by_id['q2']['note']
    assert by_id['q3']['resume_quote'] == 'Scheduled Airflow orchestration'  # Curly quotes around an exact excerpt are fine.
    assert by_id['q4']['match'] == 'missing'  # Skipped by the model.
    assert recommendations[0]['requirement_ids'] == ['q4']
    s = score(rows)
    assert (s['strong'], s['partial'], s['missing']) == (1, 2, 1)
    assert s['overall'] == 50 and s['required'] == 50  # (1 + 0.5 + 0.5 + 0) / 4; required: (1 + 0.5 + 0) / 3.


def test_live_report_uses_one_call_and_saves(monkeypatch, tmp_path):
    calls = []
    def complete(self, task, payload, model, max_tokens):
        self.requests_made = 1
        calls.append(task)
        assert set(payload) >= {'requirements', 'resume'} and 'career' not in payload
        verdicts = [{'requirement_id': q['id'], 'match': 'partial', 'resume_quote': '', 'note': 'Related.'}
                    for q in payload['requirements']]
        return {'result': {'summary': 'Good fit.', 'verdicts': verdicts, 'recommendations': []},
                'input_tokens': 4000, 'output_tokens': 1000}
    monkeypatch.setenv('CAREER_OPENAI_API_KEY', 'synthetic')
    monkeypatch.setattr(OpenAIProvider, 'complete', complete)
    store = Store(str(tmp_path / 'reports.sqlite'))
    report = build_report(JD, RESUME, store, 'openai', application={'company': 'Example Co', 'role': 'Data Engineer'})
    assert calls == ['report'] and report['model'] == 'gpt-5-mini'
    assert report['estimated_cost'] == pytest.approx((4000 * 0.25 + 1000 * 2.00) / 1e6)
    assert report['practical_constraints'] == ['Location: hybrid, two days onsite']
    assert store.reports()[0]['id'] == report['id']
    text = report_markdown(report)
    assert text.startswith('# Example Co — Data Engineer') and '**Match: 50%**' in text


def test_report_needs_a_resume_and_requirements(tmp_path):
    store = Store(str(tmp_path / 'r.sqlite'))
    with pytest.raises(ValueError, match='resume'):
        build_report(JD, 'short', store, 'mock')
    with pytest.raises(ValueError, match='No job requirements'):
        build_report('About the job\nWelcome to our wonderful company.', RESUME, store, 'mock')


def test_match_report_page_runs_a_practice_report(workspace):
    app = open_app('Match report', generator=False)
    assert not app.exception
    assert [o for o in field(app, 'radio', 'Go to').options] == ['Match report', 'Report history', 'Compare jobs']
    assert field(app, 'button', 'Create match report').disabled  # No resume yet.
    field(app, 'text_area', 'Resume text').set_value(RESUME).run()
    field(app, 'button', 'Use pasted text').click().run()
    field(app, 'text_area', 'Paste the job description').set_value(JD)
    field(app, 'radio', 'Model').set_value('Practice (free, word matching only)').run()
    field(app, 'button', 'Create match report').click().run()
    assert not app.exception
    assert any('score-card' in m.value for m in app.markdown)
    assert (workspace / 'local/report_resume.json').exists()
    field(app, 'radio', 'Go to').set_value('Report history').run()
    assert any('% match' in m.value for m in app.markdown)


def test_reworded_quote_maps_to_the_real_line_and_ids_become_words():
    reqs = [requirement('q1', 'Python and SQL ingestion pipelines'), requirement('q2', 'Kubernetes administration')]
    raw = {'verdicts': [{'requirement_id': 'q1', 'match': 'strong',
                         'resume_quote': 'Built Python and SQL batch ingestion pipelines with data quality checks in Snowflake',
                         'note': 'Covers q1.'}],
           'recommendations': [{'kind': 'edit', 'action': 'Move the ingestion bullet first.', 'reason': 'Supports q1 and q2',
                                'requirement_ids': ['q1']}]}
    rows, recommendations = check_report(raw, reqs, RESUME.replace('Snowflake.', 'Snowflake (daily).'))
    assert rows[0]['match'] == 'strong'
    assert rows[0]['resume_quote'].startswith('Built Python and SQL batch ingestion pipelines')
    assert 'q1' not in rows[0]['note'] and '"Python and SQL ingestion pipelines…"' in rows[0]['note']
    assert 'q2' not in recommendations[0]['reason'] and 'Kubernetes administration' in recommendations[0]['reason']


def test_rescore_records_what_changed_and_compare_ranks_jobs(tmp_path):
    from career_pipeline.match_report import compare_reports
    store = Store(str(tmp_path / 'r.sqlite'))
    first = build_report(JD, RESUME, store, 'mock', application={'company': 'Example Co'})
    edited = RESUME + '\n- Administered Kubernetes production clusters for batch ingestion services.'
    second = build_report(JD, edited, store, 'mock', application={'company': 'Example Co'}, previous=first)
    changes = second['changes']
    assert changes['previous_id'] == first['id'] and changes['score_change'] > 0
    assert any('Kubernetes' in m['requirement'] and m['from'] == 'missing' for m in changes['improved'])
    assert '## Since the previous version' in report_markdown(second)
    other = build_report('Required: Terraform infrastructure as code\nRequired: Go services', RESUME, store, 'mock',
                         application={'company': 'Other Co'})
    rows = compare_reports([first, other, second])
    assert [row['id'] for row in rows][0] == second['id'] and rows[-1]['id'] == other['id']
    assert rows[-1]['required_gaps']


def test_rescore_and_compare_pages(workspace):
    app = open_app('Match report', generator=False)
    field(app, 'text_area', 'Resume text').set_value(RESUME).run()
    field(app, 'button', 'Use pasted text').click().run()
    field(app, 'text_area', 'Paste the job description').set_value(JD)
    field(app, 'radio', 'Model').set_value('Practice (free, word matching only)').run()
    field(app, 'button', 'Create match report').click().run()
    assert field(app, 'button', 'Re-score with my current resume').disabled  # Same resume as the report.
    field(app, 'text_area', 'Resume text').set_value(RESUME + '\n- Administered Kubernetes production clusters.').run()
    field(app, 'button', 'Use pasted text').click().run()
    field(app, 'button', 'Re-score with my current resume').click().run()
    assert not app.exception
    assert any('since your previous version' in m.value for m in app.markdown)
    field(app, 'radio', 'Go to').set_value('Compare jobs').run()
    assert not app.exception
    assert any('bar-row' in m.value for m in app.markdown)

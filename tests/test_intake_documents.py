from pathlib import Path
import pytest
from career_pipeline.models import Career, Settings, Packet
from career_pipeline.pipeline import extract, run
from career_pipeline.store import Store
from career_pipeline.workbench import analyze_job, fit_report
from career_pipeline.export import approve, export
from career_pipeline.review import audit


@pytest.mark.parametrize('job', [
    'Experience building Python and SQL pipelines.\nKnowledge of Airflow scheduling.',
    '**Required Qualifications**\nExperience building Python and SQL pipelines.\n**Preferred Qualifications**\nKnowledge of Airflow scheduling.',
    'Required Qualifications\n1. Python and SQL pipelines\n2) Airflow scheduling',
])
def test_plain_and_formatted_jobs_produce_evidence_counts(job):
    career = Career.model_validate_json(Path('fixtures/career.json').read_text(encoding='utf-8'))
    rows = analyze_job(job, career)
    assert len(rows) == 2
    assert all(row.excerpt in job for row in rows)
    summary = fit_report(rows)
    assert summary['direct'] + summary['transferable'] > 0
    if '**Preferred' in job:
        assert [r.priority for r in rows] == ['required', 'preferred']


def test_headings_alone_are_not_requirements():
    assert not extract('## Required Qualifications\n**Preferred Qualifications**')


def test_resume_only_is_persisted_reviewed_and_exported(tmp_path):
    career = Career.model_validate_json(Path('fixtures/career.json').read_text(encoding='utf-8'))
    with Store(str(tmp_path/'runs.sqlite')) as store:
        m = run(Path('fixtures/job.txt').read_text(encoding='utf-8'), career, store,
                Settings(include_cover_letter=False))
        assert not m['validation']
        assert not m['composition_plan']['cover_letter_paragraphs']
        assert all(not v['packet']['cover_letter'] for v in m['versions'])
        assert all(r['status'] == 'passed' for r in m['versions'][-1]['reviews'].values())
        approve(store, m['id'], career, True)
        paths = export(store, m['id'], career, tmp_path/'exports')
        assert {p.name for p in paths} == {'resume.docx', 'resume.md', 'audit.json'}
        packet = Packet.model_validate(m['versions'][-1]['packet'])
        assert any(f.code == 'empty_packet' for f in audit(packet, career))  # default still requires both

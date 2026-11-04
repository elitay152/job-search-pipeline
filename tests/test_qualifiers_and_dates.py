"""Approximation symbols, follow-up answer names and dates for years requirements; synthetic data only."""
from career_pipeline.models import Career, Employment, Evidence, Requirement
from career_pipeline.grounding import deterministic_objections
from career_pipeline.pipeline import match_payload
from career_pipeline.workbench import add_gap_answer, answer_title


def registry_record():
    return Evidence(id='e1', project='Registry', actions=[], ownership='contributed', technologies=[],
                    confirmed_statements=['Led monthly registry ingestion for approximately 600000 members.'],
                    metrics=[{'value': 600000, 'unit': 'members', 'qualifier': 'estimated'}],
                    sources=[{'reference': 'synthetic', 'status': 'user_provided'}])


def test_tilde_and_approx_symbol_keep_the_approximate_qualifier():
    e = registry_record()
    for text in ('Led monthly registry ingestion for ~600,000 members.', 'Led monthly registry ingestion for ≈600K members.'):
        assert 'lost estimated/approximate qualifier' not in deterministic_objections(text, [e])
    assert 'lost estimated/approximate qualifier' in deterministic_objections(
        'Led monthly registry ingestion for 600,000 members.', [e])


def test_follow_up_answers_are_named_by_what_was_done(tmp_path):
    assert answer_title('Used PySpark within Databricks to tune queries. Also more detail.') == 'Used PySpark within Databricks to tune queries'
    assert answer_title('Tuned cluster queries.', 'PySpark') == 'PySpark: Tuned cluster queries'
    career = Career(display_name='Synthetic', evidence=[])
    requirement = Requirement(id='q1', text='Highly Preferred: Spark', excerpt='Highly Preferred: Spark', priority='preferred')
    saved = add_gap_answer(career, requirement, 'Used PySpark within Databricks', path=str(tmp_path / 'career.json'))
    assert saved.evidence[0].project == 'Used PySpark within Databricks'
    assert saved.evidence[0].fact_details['requirement_excerpt'] == 'Highly Preferred: Spark'


def test_matcher_receives_job_dates_for_years_requirements():
    job = Employment(id='j1', employer='Acme', official_title='Analyst', start='2021-03', end='2024-02')
    e = registry_record().model_copy(update={'employment_ids': ['j1']})
    payload = match_payload([Requirement(id='q1', text='3+ years of SQL', excerpt='x', priority='required')],
                            Career(display_name='Synthetic', employments=[job], evidence=[e]))
    assert payload['employment_history'] == [{'employer': 'Acme', 'title': 'Analyst', 'start': '2021-03', 'end': '2024-02'}]
    assert payload['evidence'][0]['jobs'][0]['start'] == '2021-03'

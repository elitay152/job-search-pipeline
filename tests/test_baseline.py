from pathlib import Path
from docx import Document
from career_pipeline.models import Career, Employment, Packet, Settings
from career_pipeline.baseline import employment_baseline
from career_pipeline.export import preview, export
from career_pipeline.pipeline import run
from career_pipeline.store import Store


def career():
    c = Career.model_validate_json(Path('fixtures/career.json').read_text(encoding='utf-8'))
    c.employments = [Employment(id='older', employer='Older Example Co', official_title='Analyst', start='2020-01', end='2021-12'),
                     Employment(id='newer', employer='Newer Example Co', official_title='Analyst III', start='2024-07',
                                resume_display_title='Data Engineer', resume_display_title_approved=True)]
    c.evidence[0].employment_ids = ['older']
    c.evidence[1].employment_ids = ['newer']
    return c


def test_headers_exist_without_any_generated_claims_and_keep_approved_titles():
    c = career()
    text, _ = preview(Packet(resume=[], cover_letter=[]), c)
    assert 'Data Engineer — Newer Example Co' in text
    assert 'Jul 2024 – Present' in text
    assert 'Analyst — Older Example Co' in text
    assert text.index('Newer Example Co') < text.index('Older Example Co')
    assert c.employments[1].official_title == 'Analyst III'


def test_generated_bullet_order_cannot_reorder_jobs_or_change_the_baseline():
    c = career()
    packet = Packet(resume=[dict(id=e.id, text=e.supported_wording[0], evidence_ids=[e.id]) for e in c.evidence], cover_letter=[])
    before = employment_baseline(c)
    a, _ = preview(packet, c)
    packet.resume.reverse()
    b, _ = preview(packet, c)
    assert [line for line in a.splitlines() if line.startswith('### ')] == [line for line in b.splitlines() if line.startswith('### ')]
    assert employment_baseline(c) == before


def test_shared_work_retains_explicit_scope_under_each_saved_job():
    c = career()
    c.evidence[0].employment_ids = ['older', 'newer']
    text = c.evidence[0].supported_wording[0]
    rendered, _ = preview(Packet(resume=[dict(id='shared', text=text, evidence_ids=[c.evidence[0].id])], cover_letter=[]), c)
    assert rendered.count(text) == 2
    assert rendered.count('Shared across ') == 2
    assert rendered.index('Shared across ') < rendered.index(text)


def test_history_without_source_bullets_stops_before_model_generation(tmp_path):
    import pytest
    c = career()
    c.employments.append(Employment(id='no-evidence', employer='Earliest Example Co', official_title='Assistant', start='2018-01', end='2019-12'))
    with Store(str(tmp_path/'runs.sqlite')) as store:
        with pytest.raises(ValueError, match='source bullets'):
            run('Required: Python data ingestion.', c, store, Settings(include_cover_letter=False))
        m = store.history()[0]
        assert m['failure']['code'] == 'missing_source_bullets'
        assert not m['versions']
        assert not any(stage['name']=='generate' for stage in m['stages'])


def test_shared_roles_at_same_employer_print_bullets_once_with_both_dates():
    c = career()
    for job in c.employments:
        job.employer = 'Synthetic Shared Co'
    c.evidence[0].employment_ids = ['older', 'newer']
    text = c.evidence[0].supported_wording[0]
    rendered, _ = preview(Packet(resume=[dict(id='shared', text=text, evidence_ids=[c.evidence[0].id])], cover_letter=[]), c)
    assert rendered.count(text) == 1
    assert 'Data Engineer | Jul 2024 – Present' in rendered
    assert 'Analyst | Jan 2020 – Dec 2021' in rendered
    assert 'Selected accomplishments across these roles:' in rendered
    assert 'Shared across ' not in rendered


def test_baseline_restores_education_and_publications_before_review():
    from career_pipeline.baseline import ensure_history_bullets
    from career_pipeline.models import Evidence
    c = career()
    for kind in ('education', 'publication'):
        c.evidence.append(Evidence(id=kind, kind=kind, project=kind, actions=[],
            ownership='unspecified', technologies=[], confirmed_statements=[f'Synthetic {kind}.'],
            sources=[{'reference':'synthetic','status':'user_provided'}]))
    packet = ensure_history_bullets(Packet(resume=[], cover_letter=[]), c)
    assert {kind for kind in ('education','publication')} <= {i for claim in packet.resume for i in claim.evidence_ids}
    assert ensure_history_bullets(packet, c) == packet


def test_numeric_rendering_preserves_scientific_and_magnitude_values():
    from career_pipeline.grounding import numbers, deterministic_objections
    assert numbers('2e+07') == numbers('20 million') == numbers('20,000,000')
    assert numbers('600000.') == numbers('600 thousand.')
    c = career()
    e = c.evidence[0].model_copy(update={'confirmed_statements':['Database size: approximately 2e+07 claims.'],
        'approved_wording':[], 'fact_details':{}, 'metrics':[], 'sources':[]})
    assert 'new or altered number' not in deterministic_objections('Database size: approximately 20 million claims.', [e])
    assert 'new or altered number' in deterministic_objections('Database size: approximately 30 million claims.', [e])


def test_led_to_describes_an_outcome_not_personal_leadership():
    from career_pipeline.grounding import deterministic_objections
    c = career()
    e = c.evidence[0].model_copy(update={'confirmed_statements':['Project completion resulted in cancellation of a vendor contract.'],
        'approved_wording':[], 'sources':[], 'fact_details':{}, 'metrics':[]})
    assert 'unestablished ownership verb: led' not in deterministic_objections('Project completion led to cancellation of a vendor contract.', [e])
    assert 'unestablished ownership verb: led' in deterministic_objections('Led the vendor cancellation project.', [e])


def test_reduction_cannot_be_rewritten_as_daily_usage_even_when_numbers_match():
    from career_pipeline.models import Metric
    from career_pipeline.grounding import deterministic_objections
    from career_pipeline.intake import statements_from_facts
    c = career()
    e = c.evidence[0].model_copy(update={'confirmed_statements':['Estimated reduction of approximately 30 credits/day.'],
        'approved_wording':[], 'sources':[], 'fact_details':{},
        'metrics':[Metric(value=30,unit='credits/day',qualifier='estimated',meaning='reduction')]})
    for text in ('Estimated usage at 30 credits/day.', 'Estimated usage reduction to 30 credits/day.'):
        assert 'reduction presented as a usage level' in deterministic_objections(text,[e])
    assert not deterministic_objections('Estimated a reduction of approximately 30 credits/day.',[e])
    facts={'metric':{'value':30,'unit':'credits/day','qualifier':'estimated','basis':'Dashboard'},
           'comparison':{'interpretation':'An estimated typical reduction.'}}
    assert 'Reduction' in statements_from_facts(facts)[0]
    e.metrics[0].meaning='unspecified'
    e.fact_details=facts
    assert 'reduction presented as a usage level' in deterministic_objections('Estimated usage at 30 credits/day.',[e])


def test_uncertainty_on_one_metric_does_not_qualify_a_different_metric():
    from career_pipeline.grounding import qualified_number
    assert not qualified_number('A 20 million-record database and approximately 600,000 members.', 20000000, 'approximately')
    assert qualified_number('An approximately 20 million-record database and approximately 600,000 members.', 20000000, 'approximately')
    assert qualified_number('An approximately 20 million-record database and approximately 600,000 members.', 600000, 'approximately')


def test_baseline_credentials_cannot_be_corrupted_by_generated_rewrites():
    from career_pipeline.baseline import ensure_history_bullets
    from career_pipeline.models import Evidence, Claim
    c = career()
    citation='Example, M. (2026). Synthetic study, 26–37.'
    c.evidence.append(Evidence(id='publication',kind='publication',project='Study',actions=[],
        ownership='unspecified',technologies=[],confirmed_statements=[citation],
        sources=[{'reference':'synthetic','status':'user_provided'}]))
    packet=Packet(resume=[Claim(id='pub',text='Example, M. (2026). Synthetic study, 26\x1137.',evidence_ids=['publication'])],cover_letter=[])
    recovered=ensure_history_bullets(packet,c)
    assert next(claim.text for claim in recovered.resume if claim.id=='pub') == citation
    assert '\x11' in packet.resume[0].text  # The model candidate remains unchanged for inspection.
